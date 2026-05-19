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
    return {'status': 'running', 'service': 'gaelic-coach-ai-worker'}

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {'connected': has_key, 'status': 'configured' if has_key else 'missing_key'}


def is_veo_url(url: str):
    return 'veo.co' in url.lower()


def processing_profile(url: str):
    if is_veo_url(url):
        return {
            'name': 'quick-veo',
            'video_format': 'best[height<=360]/best',
            'audio_format': 'worstaudio/bestaudio',
            'frame_interval': 180,
            'max_frames': 20,
            'scale': 512,
            'transcribe': False
        }
    return {
        'name': 'standard',
        'video_format': 'best[height<=480]/best',
        'audio_format': 'bestaudio/best',
        'frame_interval': 60,
        'max_frames': 60,
        'scale': 640,
        'transcribe': True
    }


def format_timestamp(seconds: float):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def extract_video_metadata(url: str):
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'nocheckcertificate': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'uploader': info.get('uploader', ''),
                'duration': info.get('duration', 0),
                'filesize': info.get('filesize') or info.get('filesize_approx') or 0
            }
    except Exception:
        return {'title': '', 'description': '', 'uploader': '', 'duration': 0, 'filesize': 0}


def build_match_facts(match_context: dict):
    team_a = match_context.get('teamA', 'Team A')
    team_b = match_context.get('teamB', 'Team B')
    coached_team = match_context.get('coachedTeam', team_a)
    a_goals = int(match_context.get('teamAGoals') or 0)
    a_points = int(match_context.get('teamAPoints') or 0)
    b_goals = int(match_context.get('teamBGoals') or 0)
    b_points = int(match_context.get('teamBPoints') or 0)
    a_total = a_goals * 3 + a_points
    b_total = b_goals * 3 + b_points

    if a_total > b_total:
        winner, loser, margin = team_a, team_b, a_total - b_total
    elif b_total > a_total:
        winner, loser, margin = team_b, team_a, b_total - a_total
    else:
        winner, loser, margin = 'Draw', 'Draw', 0

    coached_result = 'drew' if winner == 'Draw' else ('won' if winner == coached_team else 'lost')

    return {
        'teamA': team_a,
        'teamB': team_b,
        'coachedTeam': coached_team,
        'winner': winner,
        'loser': loser,
        'margin': margin,
        'coachedTeamResult': coached_result,
        'teamATotal': a_total,
        'teamBTotal': b_total,
        'goalDifference': a_goals - b_goals,
        'scoreline': f'{team_a} {a_goals}-{a_points} ({a_total}) vs {team_b} {b_goals}-{b_points} ({b_total})'
    }


def transcribe_audio(url: str, client: OpenAI, profile: dict):
    if not profile['transcribe']:
        return {'text': '', 'segments': 'Transcript skipped in quick Veo mode.'}
    return {'text': '', 'segments': ''}


def extract_frames(url: str, client: OpenAI, profile: dict):
    return {'observations': '', 'moments': ''}


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)
    profile = processing_profile(request.url)
    metadata = extract_video_metadata(request.url)

    match_context = request.matchContext or {}
    match_facts = build_match_facts(match_context)
    coached_team = match_facts['coachedTeam']
    opposition_team = match_facts['teamB'] if match_facts['teamA'] == coached_team else match_facts['teamA']

    prompt = f'''
You are an elite Gaelic football tactical analyst.

This is NOT a generic AI summary task.
You must reason like a senior intercounty analyst.

MATCH FACTS:
{match_facts}

CRITICAL REASONING RULES:
- Goals are disproportionately valuable in Gaelic football.
- If a team loses despite scoring many points, explain why high-value goal concessions mattered.
- Distinguish between scoring volume and scoring quality.
- Infer likely tactical causes from the score profile.
- Avoid generic phrases like “spatial awareness”, “communication”, “momentum”, “dynamic play” unless supported by evidence.
- Use actual team names repeatedly.
- Every weakness must explain tactical consequence.
- Every training recommendation must connect directly to a weakness.
- Timestamp observations must feel like coach review clips.
- If evidence is weak, explicitly state “approximate / medium confidence”.
- Never mention draws or equalisers unless explicitly evidenced.
- Do not contradict the final score.

GAME-STATE REASONING:
- A narrow one-point defeat with a negative goal difference usually suggests:
  * failure to defend high-value chances
  * inability to generate goals
  * defensive transition exposure
  * poor protection of central scoring zones
- Explain WHICH is most likely.

OUTPUT STYLE:
- concise
- tactical
- specific
- premium
- coaching language
- no waffle
- no repetition

Return these exact sections:

# Result Snapshot
2-3 sentences maximum.

# Key Coach Takeaway
One elite-level coaching insight.

# Why {coached_team} {match_facts['coachedTeamResult']}
Specific tactical reasoning.

# Key Timestamped Moments
Use format:
06:00 (approx)
Observation:
Impact:
Coach Review:
Confidence:

# Strengths Shown By {coached_team}
Maximum 4.
Must explain WHY the strength mattered.

# Weaknesses / Risks For {coached_team}
Maximum 4.
Each weakness must include:
- tactical issue
- consequence
- likely match impact

# What Worked For {opposition_team}
Explain what likely allowed them to win.

# Tactical Identity Observed
Identify likely style:
- transition-based
- direct kicking
- defensive retreat
- width-based
- possession-heavy
- aggressive press
etc.

# Training Priorities
Must be actionable.
Include drill or session idea.

# Confidence Notes
Separate:
- High confidence
- Medium confidence
- Low confidence
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {
                'role': 'system',
                'content': 'You are an elite Gaelic games tactical analyst producing professional coaching intelligence.'
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
        'matchFacts': match_facts,
        'processingProfile': profile['name']
    }
