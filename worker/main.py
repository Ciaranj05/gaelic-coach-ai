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
    coached_goals = a_goals if coached_team == team_a else b_goals
    opposition_goals = b_goals if coached_team == team_a else a_goals
    coached_points = a_points if coached_team == team_a else b_points
    opposition_points = b_points if coached_team == team_a else a_points
    coached_total = a_total if coached_team == team_a else b_total
    opposition_total = b_total if coached_team == team_a else a_total

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
        'coachedGoals': coached_goals,
        'oppositionGoals': opposition_goals,
        'coachedPoints': coached_points,
        'oppositionPoints': opposition_points,
        'coachedTotal': coached_total,
        'oppositionTotal': opposition_total,
        'goalDifference': coached_goals - opposition_goals,
        'scoreline': f'{team_a} {a_goals}-{a_points} ({a_total}) vs {team_b} {b_goals}-{b_points} ({b_total})'
    }


def build_scoreline_rules(match_facts: dict):
    coached_team = match_facts['coachedTeam']
    rules = []

    if match_facts['coachedGoals'] >= 5:
        rules.append(f'{coached_team} scored {match_facts["coachedGoals"]} goals. Treat goal scoring, finishing and attacking penetration as major strengths. Do NOT recommend finishing practice, goal-scoring drills, shot conversion, or improving goal threat as a main focus unless coach notes explicitly say chances were wasted.')
        rules.append(f'For {coached_team}, focus on sustaining the attacking patterns that created goals, game management, rest defence, kickout control, and protecting against counterattacks rather than more scoring practice.')
    elif match_facts['coachedGoals'] <= 1 and match_facts['coachedTeamResult'] != 'won':
        rules.append(f'{coached_team} had limited goal output. It is valid to focus on penetration, high-value chance creation and earlier delivery into scoring zones.')

    if match_facts['oppositionGoals'] >= 3:
        rules.append(f'{coached_team} conceded {match_facts["oppositionGoals"]} goals. Prioritise defensive transition, protecting central goal channels, sweeper cover, and recovery shape.')
    elif match_facts['oppositionGoals'] <= 1:
        rules.append(f'{coached_team} conceded {match_facts["oppositionGoals"]} goals. Do not overstate defensive collapse; defensive work should be framed as refinement, not crisis.')

    if match_facts['coachedTeamResult'] == 'won' and match_facts['margin'] >= 10:
        rules.append(f'{coached_team} won comfortably. Main focus areas should be about sustaining strengths and tightening risk areas, not implying the performance was poor.')

    if match_facts['coachedTeamResult'] == 'lost' and match_facts['margin'] <= 3:
        rules.append(f'{coached_team} lost narrowly. Focus on small swing factors: one goal chance, one kickout spell, one transition concession, or late-game decision-making.')

    return '\n'.join(f'- {rule}' for rule in rules) or '- Apply normal Gaelic football scoreline reasoning.'


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
    scoreline_rules = build_scoreline_rules(match_facts)

    prompt = f'''
You are an elite Gaelic football performance analyst working directly for {coached_team}.

This report is FOR the coaching group of {coached_team}.
The entire analysis should be biased toward helping {coached_team} improve.

Create a short manager debrief. Do not write an essay.
The report must compare the two teams, include an estimated key stats table, identify the match-deciding factor, and give three sharp coaching priorities specifically designed to help {coached_team} improve.

MATCH FACTS:
{match_facts}

SCORELINE-AWARE COACHING RULES:
{scoreline_rules}

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
- Use ✅ for clear strengths, ❌ for clear weaknesses and ⚠️ for mixed areas.
- Keep every table cell useful: never output only ✅, ❌ or ⚠️ by itself.
- Estimated stats must be labelled as estimated and should be plausible from the scoreline/context, not fake precision.
- Use ranges or labels where exact numbers are not reliable, for example “High”, “Low”, “50–55% estimated”, “Strong”, “Limited”.
- Focus primarily on {coached_team}: their strengths, weaknesses, tactical issues and coaching opportunities.
- The opposition analysis should only exist to explain what hurt or exposed {coached_team}.
- Main Focus Areas must be practical, tactical and directly useful for {coached_team} training sessions.
- Do not recommend improving something that was obviously a major strength from the scoreline.
- The Key Manager Takeaway must sound like the manager of {coached_team} speaking internally to players.
- No generic filler such as “communication”, “spatial awareness”, “dynamic movement”, “cohesion”, “target awareness”, “sharpen transitions”, or “maintain structure”.
- No confidence notes.
- No long paragraphs.
- Reason from Gaelic football scoring logic: goals are high-value; points show scoring volume; goal difference often explains the result.

Return this exact markdown structure and nothing else:

# {coached_team} – Match Snapshot
| Item | Detail |
|---|---|
| Scoreline | {match_facts['scoreline']} |
| Result | {coached_team} {match_facts['coachedTeamResult']} by {match_facts['margin']} point(s) |
| Core Story | One direct tactical sentence explaining why the game went this way from the perspective of {coached_team}. |

# {coached_team} – Match-Deciding Factor
One blunt paragraph, maximum 45 words. Explain the one factor that most shaped the result for {coached_team}.

# {coached_team} – Estimated Key Match Stats
| Metric | {coached_team} | {opposition_team} |
|---|---|---|
| Possession | estimated range/label + ✅/⚠️/❌ | estimated range/label + ✅/⚠️/❌ |
| Shot Creation | estimated label + ✅/⚠️/❌ | estimated label + ✅/⚠️/❌ |
| Goal Threat | {match_facts['coachedGoals']} goals + tactical label + ✅/⚠️/❌ | {match_facts['oppositionGoals']} goals + tactical label + ✅/⚠️/❌ |
| Point Output | {match_facts['coachedPoints']} points + tactical label + ✅/⚠️/❌ | {match_facts['oppositionPoints']} points + tactical label + ✅/⚠️/❌ |
| Transition Scores | estimated label + ✅/⚠️/❌ | estimated label + ✅/⚠️/❌ |
| Turnovers Conceded | estimated label + ✅/⚠️/❌ | estimated label + ✅/⚠️/❌ |
| Scores From Turnovers | estimated label + ✅/⚠️/❌ | estimated label + ✅/⚠️/❌ |
| Kickout / Restart Retention | estimated label + ✅/⚠️/❌ | estimated label + ✅/⚠️/❌ |
| Breaking Ball | estimated label + ✅/⚠️/❌ | estimated label + ✅/⚠️/❌ |
| Defensive Scores Conceded | based on opponent total + tactical label + ✅/⚠️/❌ | based on opponent total + tactical label + ✅/⚠️/❌ |

# {coached_team} – Tactical Comparison
| Area | {coached_team} | {opposition_team} |
|---|---|---|
| Possession | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Transition Speed | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Attacking Style | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Kick Passing | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Shot Creation | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Goal Threat | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Turnovers | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Kick-Out Battle | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Breaking Ball | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |
| Defensive Shape | descriptive label + ✅/⚠️/❌ | descriptive label + ✅/⚠️/❌ |

# {coached_team} – Main Focus Areas Going Forward
| Priority | Why It Matters For {coached_team} | Coaching Action |
|---|---|---|
| Specific focus area 1 | Match-specific reason linked to the game | Practical training action for {coached_team} |
| Specific focus area 2 | Match-specific reason linked to the game | Practical training action for {coached_team} |
| Specific focus area 3 | Match-specific reason linked to the game | Practical training action for {coached_team} |

# {coached_team} – Key Manager Takeaway
One short quote, maximum 55 words. Make it direct, honest and tactical. It should sound like the manager of {coached_team} speaking to players after video review.
'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'You produce concise Gaelic games manager debrief reports focused on helping the coached team improve through scoreline-aware tactical insights, estimated key stats and actionable coaching priorities.'},
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
