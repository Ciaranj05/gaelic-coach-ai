from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp

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
        return {'name': 'quick-veo', 'frames': 20, 'transcribe': False}
    return {'name': 'standard', 'frames': 60, 'transcribe': True}


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
        'teamAGoals': a_goals,
        'teamBGoals': b_goals,
        'teamAPoints': a_points,
        'teamBPoints': b_points,
        'teamATotal': a_total,
        'teamBTotal': b_total,
        'goalDifference': a_goals - b_goals,
        'scoreline': f'{team_a} {a_goals}-{a_points} ({a_total}) vs {team_b} {b_goals}-{b_points} ({b_total})'
    }


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
You are an elite Gaelic football performance analyst.

Create the same DEFAULT report format every time. It must feel like a clean manager debrief, not an essay.
Use comparison tables, green ticks, red crosses and short focus points.

MATCH FACTS:
{match_facts}

VIDEO METADATA:
{metadata}

COACH NOTES:
{request.notes}

PROCESSING PROFILE:
{profile}

STRICT RULES:
- Do not contradict the scoreline, winner or margin.
- Do not invent exact scorers, exact timestamps or events.
- Use actual team names throughout.
- Use ✅ for clear strengths, ❌ for clear weaknesses and ⚠️ for mixed/uncertain areas.
- Keep text concise and coach-friendly.
- No long paragraphs.
- No generic filler like “spatial awareness”, “dynamic movement”, “communication gaps”, unless specifically supported.
- If data is estimated, label it as estimated.
- Reason from Gaelic football scoring logic: goals are high-value, points show scoring volume, goal difference often explains match outcome.

Return this exact markdown structure and nothing else:

# Match Snapshot
| Item | Detail |
|---|---|
| Scoreline | {match_facts['scoreline']} |
| Result | {coached_team} {match_facts['coachedTeamResult']} by {match_facts['margin']} point(s) |
| Goal Difference | {coached_team} goal difference: {match_facts['goalDifference']} |
| Core Story | One short sentence explaining why the match went the way it did. |

# Estimated Key Match Stats
| Metric | {coached_team} | {opposition_team} |
|---|---|---|
| Possession | Estimated percentage or balance | Estimated percentage or balance |
| Shot Creation |  |  |
| Goal Threat |  |  |
| Transition Speed |  |  |
| Kick Passing |  |  |
| Turnovers Conceded |  |  |
| Scores From Turnovers |  |  |
| Kickout / Restart Battle |  |  |
| Breaking Ball |  |  |
| Defensive Shape |  |  |

# Match Comparison
| Area | {coached_team} | {opposition_team} |
|---|---|---|
| Possession |  |  |
| Transition Speed |  |  |
| Attacking Style |  |  |
| Kick Passing |  |  |
| Shot Creation |  |  |
| Goal Threat |  |  |
| Turnovers Attacking Third |  |  |
| Kick-Out Battle |  |  |
| Breaking Ball |  |  |
| Defensive Shape |  |  |

# Main Focus Areas Going Forward
1. Focus Area Title
- Coaching action one
- Coaching action two

2. Focus Area Title
- Coaching action one
- Coaching action two

3. Focus Area Title
- Coaching action one
- Coaching action two

4. Focus Area Title
- Coaching action one
- Coaching action two

# Key Manager Takeaway
One short, punchy paragraph in quotation marks. Make it sound like something a manager could say to the team after review.

# Confidence Notes
| Confidence | What We Can Trust |
|---|---|
| High | Scoreline, result, winning margin and goal difference. |
| Medium | Estimated tactical themes from score profile, coach context and available footage. |
| Low | Exact player actions, exact timestamps or event details not directly supplied. |
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'You produce clean Gaelic games manager debrief reports with comparison tables, focus areas and concise coaching takeaways.'},
            {'role': 'user', 'content': prompt}
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
