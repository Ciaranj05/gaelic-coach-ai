from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp
import tempfile
import subprocess
import base64

app = FastAPI(title='Gaelic Coach AI Worker')

class AnalyseRequest(BaseModel):
    url: str
    notes: str | None = ''
    matchContext: dict | None = None

@app.get('/')
def health():
    return {
        'status': 'running',
        'service': 'gaelic-coach-ai-worker'
    }

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {
        'connected': has_key,
        'status': 'configured' if has_key else 'missing_key'
    }


def extract_video_metadata(url: str):
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'nocheckcertificate': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            return {
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'uploader': info.get('uploader', ''),
                'duration': info.get('duration', 0)
            }
    except Exception:
        return {
            'title': '',
            'description': '',
            'uploader': '',
            'duration': 0
        }


def transcribe_audio_from_youtube(url: str, client: OpenAI):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, 'audio.%(ext)s')

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'quiet': True,
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64'
                }]
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            audio_path = os.path.join(tmpdir, 'audio.mp3')

            if not os.path.exists(audio_path):
                return ''

            with open(audio_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model='whisper-1',
                    file=audio_file
                )

            return transcript.text

    except Exception:
        return ''


def extract_frames_from_youtube(url: str, client: OpenAI):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, 'match.mp4')
            frame_pattern = os.path.join(tmpdir, 'frame_%03d.jpg')

            ydl_opts = {
                'format': 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                'outtmpl': video_path,
                'quiet': True,
                'noplaylist': True,
                'merge_output_format': 'mp4'
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if not os.path.exists(video_path):
                return ''

            subprocess.run(
                [
                    'ffmpeg', '-y', '-i', video_path,
                    '-vf', 'fps=1/60,scale=640:-1',
                    '-frames:v', '60',
                    frame_pattern
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )

            frame_paths = sorted([
                os.path.join(tmpdir, filename)
                for filename in os.listdir(tmpdir)
                if filename.startswith('frame_') and filename.endswith('.jpg')
            ])[:60]

            if not frame_paths:
                return ''

            frame_batches = [frame_paths[i:i + 10] for i in range(0, len(frame_paths), 10)]
            observations = []

            for batch_number, frame_batch in enumerate(frame_batches, start=1):
                content = [
                    {
                        'type': 'text',
                        'text': f'You are reviewing sampled frames from a Gaelic football or hurling match. Only describe visible tactical patterns. Focus on spacing, transitions, kickout structure, attacking shape, overloads, defensive compactness and pressure. Do not invent scores, events or player identities. If evidence is weak, explicitly state uncertainty.'
                    }
                ]

                for frame_path in frame_batch:
                    with open(frame_path, 'rb') as image_file:
                        encoded = base64.b64encode(image_file.read()).decode('utf-8')
                        content.append({
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/jpeg;base64,{encoded}',
                                'detail': 'low'
                            }
                        })

                response = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[
                        {
                            'role': 'user',
                            'content': content
                        }
                    ]
                )

                observations.append(response.choices[0].message.content or '')

            return '\n\n'.join(observations)

    except Exception:
        return ''


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)

    metadata = extract_video_metadata(request.url)
    transcript = transcribe_audio_from_youtube(request.url, client)
    visual_observations = extract_frames_from_youtube(request.url, client)

    match_context = request.matchContext or {}

    coached_team = match_context.get('coachedTeam', 'The coached team')
    opposition_team = match_context.get('teamB', 'the opposition')

    prompt = f'''
You are a senior Gaelic football and hurling performance analyst.

Your task is to produce evidence-based tactical analysis.

IMPORTANT RULES:
- ONLY reference observations supported by transcript, frame observations or match context.
- NEVER invent exact events, scores, possessions or player identities.
- If evidence is weak or uncertain, explicitly state uncertainty.
- Use the actual team names throughout.
- Analyse primarily from the perspective of {coached_team}.
- Explain WHY the result happened.
- Avoid generic coaching clichés.
- Prefer fewer, sharper insights over long generic paragraphs.
- Every recommendation must connect to an observed issue.

MATCH CONTEXT
{match_context}

VIDEO INFORMATION
Title: {metadata['title']}
Uploader: {metadata['uploader']}
Duration: {metadata['duration']} seconds
Description: {metadata['description']}

MATCH URL
{request.url}

TRANSCRIPT / COMMENTARY
{transcript[:10000]}

VISUAL FRAME OBSERVATIONS
{visual_observations[:12000]}

COACH NOTES
{request.notes}

Return a concise but high-quality coaching report with these exact sections:

# Match Flow
- explain momentum and overall tactical story
- explain why {coached_team} won or lost

# Strengths Shown By {coached_team}
- maximum 5 evidence-based strengths

# Weaknesses Shown By {coached_team}
- maximum 5 evidence-based weaknesses

# Tactical Themes
- explain the clearest patterns observed
- mention transitions, kickouts, shape or scoring patterns only if evidence exists

# What Changed The Game
- explain major tactical swing factors

# Training Priorities
- maximum 5 very practical coaching actions
- include drills, structures or session focus ideas

# Confidence Notes
- clearly explain what observations were high confidence vs uncertain

Keep the tone elite-level, concise and tactical.
Do not write generic filler sentences.
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {
                'role': 'system',
                'content': 'You are an elite Gaelic games tactical analyst. You prioritise evidence, specificity and tactical reasoning over generic coaching language.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ]
    )

    analysis = response.choices[0].message.content

    return {
        'status': 'complete',
        'mode': 'worker',
        'analysis': analysis,
        'videoMetadata': metadata,
        'transcriptLength': len(transcript),
        'visualAnalysisLength': len(visual_observations),
        'framesSampledTarget': 60,
        'next_stage': 'Future upgrade: event detection, tactical tagging and clip generation.'
    }
