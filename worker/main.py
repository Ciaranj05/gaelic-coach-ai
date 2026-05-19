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
You are an elite Gaelic football tactical analyst.

Create a clean coaching dashboard, not a long essay.
The output must be concise, comparative, visual and coach-friendly.

MATCH FACTS:
{match_facts}

VIDEO METADATA:
{metadata}

COACH NOTES:
{request.notes}

PROCESSING PROFILE:
{profile}

NON-NEGOTIABLE RULES:
- Do not contradict the final score.
- Do not invent draws, equalisers, scorers or exact events.
- Use actual team names throughout.
- Avoid generic filler such as spatial awareness, dynamic movement, communication gaps or momentum unless clearly supported.
- Reason from Gaelic football scoring logic.
- Goals are high-value events; points-heavy teams can lose if they concede goals.
- Keep analysis short, sharp and useful for coaches.
- Prefer dashboard tables over paragraphs.
- If evidence is limited, say so in confidence notes.

Return this exact markdown structure:

# Match Dashboard
2 concise sentences explaining the result and the core tactical story.

# Key Coach Takeaway
One memorable coaching conclusion, maximum 35 words.

# Tactical Comparison
| Area | {coached_team} | {opposition_team} |
|---|---|---|
| Scoring Profile |  |  |
| Goal Threat |  |  |
| Attacking Style |  |  |
| Transition Play |  |  |
| Defensive Shape |  |  |
| Kickout / Restart Battle |  |  |
| Match Control |  |  |

Use ✅, ⚠️ and ❌ where helpful.

# Key Moments To Review
| Time | Moment | Coach Review |
|---|---|---|
| 06:00 approx |  |  |
| 12:00 approx |  |  |
| 30:00 approx |  |  |
| 54:00 approx |  |  |

If exact evidence is weak, label the moment as approximate / medium confidence.

# Strengths To Keep
| Strength | Why It Mattered |
|---|---|
|  |  |
|  |  |
|  |  |

# Issues To Fix
| Issue | Match Impact | Coaching Fix |
|---|---|---|
|  |  |  |
|  |  |  |
|  |  |  |

# Training Priorities
| Priority | Drill / Session Focus | Outcome |
|---|---|---|
|  |  |  |
|  |  |  |
|  |  |  |

# Confidence Notes
| Confidence | What We Can Trust |
|---|---|
| High | Scoreline, winner, margin and goal difference. |
| Medium | Tactical inferences from score profile, coach context and sampled footage. |
| Low | Player-specific actions or exact events not visible/timestamped. |
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'You produce concise Gaelic games coaching dashboards, comparison tables and actionable training recommendations.'},
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
