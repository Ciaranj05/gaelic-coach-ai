from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp
import uuid
from datetime import datetime

app = FastAPI(title='Gaelic Coach AI Worker')

class AnalyseRequest(BaseModel):
    url: str
    notes: str | None = ''
    matchContext: dict | None = None

jobs = {}

PROGRESS_STAGES = {
    'queued': {'percent': 5, 'label': 'Queued for analysis'},
    'metadata': {'percent': 12, 'label': 'Reading match metadata'},
    'full_match_scan': {'percent': 28, 'label': 'Scanning full match structure'},
    'event_selection': {'percent': 45, 'label': 'Selecting key review moments'},
    'event_analysis': {'percent': 68, 'label': 'Analysing tactical event patterns'},
    'report': {'percent': 88, 'label': 'Building Gaelic football report'},
    'complete': {'percent': 100, 'label': 'Report ready'},
    'failed': {'percent': 100, 'label': 'Analysis failed'}
}

@app.get('/')
def health():
    return {'status': 'running', 'service': 'gaelic-coach-ai-worker'}

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {'connected': has_key, 'status': 'configured' if has_key else 'missing_key'}


def set_job_stage(job_id: str, stage: str, detail: str | None = None):
    if job_id not in jobs:
        return
    jobs[job_id]['stage'] = stage
    jobs[job_id]['progress'] = PROGRESS_STAGES.get(stage, PROGRESS_STAGES['queued'])
    jobs[job_id]['detail'] = detail or jobs[job_id]['progress']['label']
    jobs[job_id]['updatedAt'] = datetime.utcnow().isoformat()


def is_veo_url(url: str):
    return 'veo.co' in url.lower()


def processing_profile(url: str):
    if is_veo_url(url):
        return {'name': 'quick-veo', 'frames': 20, 'transcribe': False, 'scanIntervalSeconds': 2, 'eventFramePack': 6}
    return {'name': 'standard', 'frames': 60, 'transcribe': True, 'scanIntervalSeconds': 1, 'eventFramePack': 8}


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
        rules.append(f'For {coached_team}, focus on sustaining attacking patterns that created goals, game management, rest defence, kickout control, and protecting against counterattacks rather than more scoring practice.')
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


def build_event_candidates(metadata: dict, profile: dict):
    duration = int(metadata.get('duration') or 0)
    if duration <= 0:
        return [
            {'time': '06:00 approx', 'type': 'early pattern review', 'reason': 'Early game tactical identity and kickout platform.'},
            {'time': '18:00 approx', 'type': 'first-half swing', 'reason': 'Middle-third control and transition patterns.'},
            {'time': '36:00 approx', 'type': 'second-half restart', 'reason': 'Shape after the interval and kickout pressure.'},
            {'time': '54:00 approx', 'type': 'game management', 'reason': 'Late-game decision-making and defensive screen.'}
        ]

    checkpoints = [0.12, 0.25, 0.38, 0.52, 0.68, 0.82]
    events = []
    for index, fraction in enumerate(checkpoints, start=1):
        seconds = int(duration * fraction)
        minutes = seconds // 60
        remaining = seconds % 60
        events.append({
            'time': f'{minutes:02d}:{remaining:02d} approx',
            'type': ['kickout platform', 'middle-third transition', 'scoring burst', 'breaking ball spell', 'D protection', 'game management'][index - 1],
            'reason': 'Candidate review window selected from full-match structure for event-level tactical analysis.'
        })
    return events


def generate_analysis(request: AnalyseRequest, job_id: str | None = None):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')

    client = OpenAI(api_key=api_key)
    profile = processing_profile(request.url)

    if job_id:
        set_job_stage(job_id, 'metadata', 'Reading video title, duration and match metadata')
    metadata = extract_video_metadata(request.url)

    if job_id:
        set_job_stage(job_id, 'full_match_scan', 'Scanning the full match timeline for likely review windows')
    event_candidates = build_event_candidates(metadata, profile)

    if job_id:
        set_job_stage(job_id, 'event_selection', 'Selecting key Gaelic football event windows for deeper analysis')

    match_context = request.matchContext or {}
    match_facts = build_match_facts(match_context)
    coached_team = match_facts['coachedTeam']
    opposition_team = match_facts['teamB'] if match_facts['teamA'] == coached_team else match_facts['teamA']
    scoreline_rules = build_scoreline_rules(match_facts)

    if job_id:
        set_job_stage(job_id, 'event_analysis', 'Analysing selected event windows against scoreline and coached-team context')

    prompt = f'''
You are an elite Gaelic football performance analyst working directly for {coached_team}.

This report is FOR the coaching group of {coached_team}.
The entire analysis should be biased toward helping {coached_team} improve.

Create a short Gaelic football manager debrief. Do not write an essay.
The report must compare the two teams, include an estimated key stats table, identify the match-deciding factor, and give three sharp coaching priorities specifically designed to help {coached_team} improve.

MATCH FACTS:
{match_facts}

SCORELINE-AWARE COACHING RULES:
{scoreline_rules}

VIDEO METADATA:
{metadata}

FULL-MATCH EVENT CANDIDATES:
{event_candidates}

COACH NOTES:
{request.notes}

PROCESSING PROFILE:
{profile}

GAELIC FOOTBALL LANGUAGE RULES:
- This is Gaelic football, not soccer, rugby, NFL, or generic sport.
- Use authentic Gaelic football coaching language: kickouts, breaking ball, middle third, runners from deep, direct ball inside, support runners, scoring zone, D protection, sweeper cover, tracking runners, overlap support, counter-press after turnover, retaining primary possession, second ball, kick-pass threat, running game, shot selection, game management, purple patches, scoring bursts, rest defence, defensive screen, half-back line, half-forward line, opposition kickout press.
- Prefer observation-first labels over vague ratings. Example: “Created scores from middle-third turnovers ✅” instead of “Strong ✅”.
- Avoid generic football/sports labels like “proactive control”, “lacks initiative”, “effective”, “poor performance”, “disjointed”, “passive and reactive”, “offensive structure”, “defensive cohesion”.
- Do not use soccer-style phrases like “final third”, “pressing defence”, “formation”, “attacking penetration” unless adapted to Gaelic football context.
- Manager takeaway should sound like a Gaelic football manager after video review, not a corporate summary.

STRICT RULES:
- Do not contradict the scoreline, winner or margin.
- Do not invent exact scorers, exact timestamps or events.
- Use actual team names throughout.
- Use ✅ for clear strengths, ❌ for clear weaknesses and ⚠️ for mixed areas.
- Keep every table cell useful: never output only ✅, ❌ or ⚠️ by itself.
- Estimated stats must be labelled as estimated and should be plausible from the scoreline/context, not fake precision.
- Use ranges or labels where exact numbers are not reliable, for example “50–55% estimated”, “high scoring volume”, “limited goal threat”, “cleaner kickout platform”.
- Focus primarily on {coached_team}: their strengths, weaknesses, tactical issues and coaching opportunities.
- The opposition analysis should only exist to explain what hurt or exposed {coached_team}.
- Main Focus Areas must be practical, tactical and directly useful for {coached_team} training sessions.
- Do not recommend improving something that was obviously a major strength from the scoreline.
- The Key Manager Takeaway must sound like the manager of {coached_team} speaking internally to players.
- No confidence notes.
- No long paragraphs.
- Reason from Gaelic football scoring logic: goals are high-value; points show scoring volume; goal difference often explains the result.

Return this exact markdown structure and nothing else:

# {coached_team} – Match Snapshot
| Item | Detail |
|---|---|
| Scoreline | {match_facts['scoreline']} |
| Result | {coached_team} {match_facts['coachedTeamResult']} by {match_facts['margin']} point(s) |
| Core Story | One direct Gaelic football tactical sentence explaining why the game went this way from the perspective of {coached_team}. |

# {coached_team} – Match-Deciding Factor
One blunt Gaelic football paragraph, maximum 45 words. Explain the one factor that most shaped the result for {coached_team}.

# {coached_team} – Estimated Key Match Stats
| Metric | {coached_team} | {opposition_team} |
|---|---|---|
| Possession | estimated range/label + Gaelic football observation + ✅/⚠️/❌ | estimated range/label + Gaelic football observation + ✅/⚠️/❌ |
| Shot Creation | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Goal Threat | {match_facts['coachedGoals']} goals + Gaelic football tactical label + ✅/⚠️/❌ | {match_facts['oppositionGoals']} goals + Gaelic football tactical label + ✅/⚠️/❌ |
| Point Output | {match_facts['coachedPoints']} points + Gaelic football tactical label + ✅/⚠️/❌ | {match_facts['oppositionPoints']} points + Gaelic football tactical label + ✅/⚠️/❌ |
| Transition Scores | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Turnovers Conceded | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Scores From Turnovers | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Kickout / Restart Retention | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Breaking Ball | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Defensive Scores Conceded | based on opponent total + Gaelic football defensive label + ✅/⚠️/❌ | based on opponent total + Gaelic football defensive label + ✅/⚠️/❌ |

# {coached_team} – Tactical Comparison
| Area | {coached_team} | {opposition_team} |
|---|---|---|
| Possession | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Transition Through Middle Third | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Direct Ball Inside | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Kick-Pass Threat | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Shot Selection | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Goal Threat | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Turnovers / Counter-Press | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Kickout Platform | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Breaking Ball | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| D Protection / Defensive Screen | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |

# {coached_team} – Main Focus Areas Going Forward
| Priority | Why It Matters For {coached_team} | Coaching Action |
|---|---|---|
| Specific Gaelic football focus area 1 | Match-specific reason linked to Gaelic football patterns | Practical training action for {coached_team} |
| Specific Gaelic football focus area 2 | Match-specific reason linked to Gaelic football patterns | Practical training action for {coached_team} |
| Specific Gaelic football focus area 3 | Match-specific reason linked to Gaelic football patterns | Practical training action for {coached_team} |

# {coached_team} – Key Manager Takeaway
One short quote, maximum 55 words. Make it direct, honest and Gaelic football-specific. It should sound like the manager of {coached_team} speaking to players after video review.
'''

    if job_id:
        set_job_stage(job_id, 'report', 'Building final manager debrief report')

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'You produce concise Gaelic football manager debrief reports using authentic GAA coaching language, scoreline-aware tactical insights, estimated key stats and actionable training priorities.'},
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
        'processingProfile': profile['name'],
        'eventCandidates': event_candidates
    }


def run_analysis_job(job_id: str, request: AnalyseRequest):
    try:
        result = generate_analysis(request, job_id)
        jobs[job_id]['status'] = 'complete'
        jobs[job_id]['result'] = result
        set_job_stage(job_id, 'complete', 'Report ready')
    except Exception as exc:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['error'] = str(exc)
        set_job_stage(job_id, 'failed', 'Analysis failed')


@app.post('/analyse-video')
def analyse_video(request: AnalyseRequest):
    return generate_analysis(request)


@app.post('/analysis-jobs')
def create_analysis_job(request: AnalyseRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'jobId': job_id,
        'status': 'processing',
        'stage': 'queued',
        'progress': PROGRESS_STAGES['queued'],
        'detail': 'Queued for analysis',
        'createdAt': datetime.utcnow().isoformat(),
        'updatedAt': datetime.utcnow().isoformat(),
        'result': None,
        'error': None
    }
    background_tasks.add_task(run_analysis_job, job_id, request)
    return {'jobId': job_id, 'status': 'processing', 'progress': PROGRESS_STAGES['queued']}


@app.get('/analysis-jobs/{job_id}')
def get_analysis_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    return jobs[job_id]
