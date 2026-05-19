from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os

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

@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)

    prompt = f'''
You are an elite Gaelic football and hurling performance analyst.

Analyse this match context and create a coaching report.

Match URL:
{request.url}

Notes:
{request.notes}

Return a practical coaching report with:
- match summary
- key tactical insights
- transition analysis
- kickout observations
- training focus
- coaching recommendations
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
        'next_stage': 'Connect yt-dlp and FFmpeg for real video ingestion.'
    }
