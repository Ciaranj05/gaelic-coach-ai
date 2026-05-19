from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import os

app = FastAPI(title='Gaelic Coach AI Worker')

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

class AnalyseRequest(BaseModel):
    url: str
    notes: str | None = ''

@app.get('/')
def health():
    return {
        'status': 'running',
        'service': 'gaelic-coach-ai-worker'
    }

@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    prompt = f'''
    You are an elite Gaelic football and hurling performance analyst.

    Analyse this match context and create a coaching report.

    Match URL:
    {request.url}

    Notes:
    {request.notes}

    Return:
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
                'content': 'You are an expert Gaelic games analyst.'
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
