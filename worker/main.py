from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp

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


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)

    metadata = extract_video_metadata(request.url)

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

COACH NOTES
{request.notes}

IMPORTANT:
- Do NOT pretend you watched the full video.
- Use the metadata and coach notes intelligently.
- Infer likely tactical themes carefully.
- Focus on coaching value.

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
        'next_stage': 'Next upgrade: full transcript extraction and frame analysis.'
    }
