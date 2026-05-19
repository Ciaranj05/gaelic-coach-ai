from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp
import tempfile

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


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)

    metadata = extract_video_metadata(request.url)
    transcript = transcribe_audio_from_youtube(request.url, client)

    prompt = f'''
You are an elite Gaelic football and hurling performance analyst.

Analyse this match context and create a coaching report.

VIDEO INFORMATION
Title: {metadata['title']}
Uploader: {metadata['uploader']}
Duration: {metadata['duration']} seconds
Description: {metadata['description']}

MATCH URL
{request.url}

TRANSCRIPT / COMMENTARY
{transcript[:12000]}

COACH NOTES
{request.notes}

IMPORTANT:
- Use transcript and metadata to infer tactical themes.
- Do NOT claim to visually track players unless explicitly described.
- Focus on practical coaching insights.
- Be structured and professional.

Return:
- executive summary
- attacking analysis
- defensive analysis
- transition analysis
- kickout observations
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
        'next_stage': 'Next upgrade: frame extraction and AI vision analysis.'
    }
