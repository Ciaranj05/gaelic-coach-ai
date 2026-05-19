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
                        'text': f'You are reviewing batch {batch_number} of sampled frames from a Gaelic football or hurling match. Identify visible tactical patterns only: pitch shape, player spacing, defensive structure, attacking width, restarts, pressure, transition spacing, and obvious coaching observations. Do not invent exact events, scores, or player identities.'
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

    prompt = f'''
You are an elite Gaelic football and hurling performance analyst.

Create a professional coaching report from the available video-derived data.

VIDEO INFORMATION
Title: {metadata['title']}
Uploader: {metadata['uploader']}
Duration: {metadata['duration']} seconds
Description: {metadata['description']}

MATCH URL
{request.url}

TRANSCRIPT / COMMENTARY
{transcript[:12000]}

VISUAL FRAME OBSERVATIONS FROM UP TO 60 SAMPLED FRAMES
{visual_observations[:14000]}

COACH NOTES
{request.notes}

IMPORTANT:
- Use transcript, metadata, coach notes and sampled frame observations.
- Be clear about themes rather than pretending perfect player tracking.
- Focus on practical coaching value.
- Include specific sections and actionable training recommendations.

Return:
- executive summary
- attacking analysis
- defensive analysis
- transition analysis
- kickout/restart observations
- visible tactical themes
- training priorities
- coach recommendations
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {
                'role': 'system',
                'content': 'You are an expert Gaelic games analyst. Be practical, specific, and coach-focused.'
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
        'next_stage': 'Future upgrade: event detection, clip creation, player tracking and persistent report storage.'
    }
