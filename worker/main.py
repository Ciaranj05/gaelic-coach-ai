from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os
import yt_dlp
import uuid
import tempfile
import subprocess
import base64
import json
from datetime import datetime

app = FastAPI(title='Gaelic Coach AI Worker')
CLIP_ROOT = '/tmp/gaelic-coach-ai-clips'
os.makedirs(CLIP_ROOT, exist_ok=True)

class AnalyseRequest(BaseModel):
    url: str
    notes: str | None = ''
    matchContext: dict | None = None

jobs = {}

PROGRESS_STAGES = {
    'queued': {'percent': 5, 'label': 'Queued for analysis'},
    'metadata': {'percent': 12, 'label': 'Reading match metadata'},
    'download': {'percent': 22, 'label': 'Downloading match video'},
    'full_match_scan': {'percent': 38, 'label': 'Scanning full match frames'},
    'event_selection': {'percent': 55, 'label': 'Selecting key review moments'},
    'event_analysis': {'percent': 72, 'label': 'Classifying tactical and scoring events'},
    'clip_extraction': {'percent': 82, 'label': 'Creating review clips'},
    'report': {'percent': 92, 'label': 'Building Gaelic football report'},
    'complete': {'percent': 100, 'label': 'Report ready'},
    'failed': {'percent': 100, 'label': 'Analysis failed'}
}

EVENT_TYPES = [
    'kickout_restart',
    'turnover',
    'fast_transition',
    'scoring_chance',
    'score_or_restart_after_score',
    'defensive_setup',
    'breaking_ball',
    'slow_possession',
    'game_management',
    'not_useful'
]

@app.get('/')
def health():
    return {'status': 'running', 'service': 'gaelic-coach-ai-worker'}

@app.get('/openai-status')
def openai_status():
    has_key = bool(os.getenv('OPENAI_API_KEY'))
    return {'connected': has_key, 'status': 'configured' if has_key else 'missing_key'}


def set_job_stage(job_id: str | None, stage: str, detail: str | None = None):
    if not job_id or job_id not in jobs:
        return
    jobs[job_id]['stage'] = stage
    jobs[job_id]['progress'] = PROGRESS_STAGES.get(stage, PROGRESS_STAGES['queued'])
    jobs[job_id]['detail'] = detail or jobs[job_id]['progress']['label']
    jobs[job_id]['updatedAt'] = datetime.utcnow().isoformat()


def is_veo_url(url: str):
    return 'veo.co' in url.lower()


def processing_profile(url: str):
    if is_veo_url(url):
        return {'name': 'quick-veo', 'frames': 20, 'transcribe': False, 'scanIntervalSeconds': 2, 'eventFramePack': 6, 'videoFormat': 'best[height<=360]/best', 'clipCount': 4}
    return {'name': 'standard', 'frames': 60, 'transcribe': True, 'scanIntervalSeconds': 1, 'eventFramePack': 8, 'videoFormat': 'best[height<=480]/best', 'clipCount': 6}


def format_timestamp(seconds: int):
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
        winner, margin = team_a, a_total - b_total
    elif b_total > a_total:
        winner, margin = team_b, b_total - a_total
    else:
        winner, margin = 'Draw', 0

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


def fallback_event_candidates(metadata: dict):
    duration = int(metadata.get('duration') or 0)
    times = [360, 1080, 2160, 3240] if duration <= 0 else [int(duration * f) for f in [0.12, 0.25, 0.38, 0.52, 0.68, 0.82]]
    labels = ['kickout_restart', 'fast_transition', 'scoring_chance', 'breaking_ball', 'defensive_setup', 'game_management']
    return [
        {
            'time': f'{format_timestamp(seconds)} approx',
            'startSecond': max(0, seconds - 15),
            'endSecond': seconds + 15,
            'type': labels[index % len(labels)],
            'reason': 'Fallback checkpoint selected from match timeline.',
            'confidence': 'low',
            'classification': {
                'eventType': labels[index % len(labels)],
                'confidence': 'low',
                'coachingValue': 'medium',
                'keepForReport': True,
                'visibleCues': ['Fallback timeline checkpoint'],
                'coachingReason': 'Useful as a broad tactical review window when scan evidence is limited.',
                'scoreboard': {'visible': False, 'text': '', 'scoreChangeLikely': False, 'possibleScoreEvent': False}
            }
        }
        for index, seconds in enumerate(times)
    ]


def download_match_video(url: str, tmpdir: str, profile: dict):
    video_path = os.path.join(tmpdir, 'match.mp4')
    ydl_opts = {
        'format': profile.get('videoFormat', 'best[height<=480]/best'),
        'outtmpl': video_path,
        'quiet': False,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'retries': 2,
        'fragment_retries': 2
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return video_path if os.path.exists(video_path) else None


def scan_video_frame_differences(video_path: str, profile: dict, max_scan_seconds: int = 7200):
    interval = int(profile.get('scanIntervalSeconds', 1))
    width, height = 64, 36
    frame_size = width * height
    command = ['ffmpeg', '-i', video_path, '-vf', f'fps=1/{interval},scale={width}:{height},format=gray', '-frames:v', str(max_scan_seconds // interval), '-f', 'rawvideo', '-']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    previous = None
    differences = []
    frame_index = 0
    try:
        while True:
            frame = process.stdout.read(frame_size) if process.stdout else b''
            if not frame or len(frame) < frame_size:
                break
            if previous is not None:
                diff = sum(abs(frame[i] - previous[i]) for i in range(frame_size)) / frame_size
                differences.append({'second': frame_index * interval, 'difference': round(diff, 2)})
            previous = frame
            frame_index += 1
    finally:
        try:
            process.kill()
        except Exception:
            pass
    return differences


def select_event_candidates_from_differences(differences: list, max_events: int = 10):
    if not differences:
        return []
    sorted_diffs = sorted(differences, key=lambda item: item['difference'], reverse=True)
    selected = []
    minimum_gap_seconds = 150
    for item in sorted_diffs:
        second = int(item['second'])
        if all(abs(second - existing['startSecond']) > minimum_gap_seconds for existing in selected):
            selected.append({
                'time': f'{format_timestamp(second)} approx',
                'startSecond': max(0, second - 20),
                'endSecond': second + 25,
                'type': classify_event_window(len(selected)),
                'reason': f'Large visual change detected during full-match scan (frame difference {item["difference"]}).',
                'confidence': 'medium'
            })
        if len(selected) >= max_events:
            break
    return sorted(selected, key=lambda item: item['startSecond'])


def classify_event_window(index: int):
    cycle = ['kickout_restart', 'fast_transition', 'scoring_chance', 'score_or_restart_after_score', 'breaking_ball', 'defensive_setup', 'game_management', 'turnover', 'direct_ball_inside']
    return cycle[index % len(cycle)]


def extract_event_frames(video_path: str, event: dict, tmpdir: str, event_index: int, profile: dict):
    frame_count = int(profile.get('eventFramePack', 8))
    start = max(0, int(event.get('startSecond', 0)))
    end = max(start + 1, int(event.get('endSecond', start + 30)))
    duration = max(1, end - start)
    fps = max(0.1, frame_count / duration)
    output_pattern = os.path.join(tmpdir, f'event_{event_index}_%02d.jpg')
    subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', video_path, '-t', str(duration), '-vf', f'fps={fps},scale=512:-1', '-frames:v', str(frame_count), output_pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith(f'event_{event_index}_') and f.endswith('.jpg')])[:frame_count]


def extract_event_clip(video_path: str, event: dict, job_id: str | None, event_index: int):
    if not job_id:
        return None
    clip_dir = os.path.join(CLIP_ROOT, job_id)
    os.makedirs(clip_dir, exist_ok=True)
    start = max(0, int(event.get('startSecond', 0)))
    end = max(start + 1, int(event.get('endSecond', start + 30)))
    duration = min(45, max(8, end - start))
    clip_id = f'clip_{event_index:02d}'
    output_path = os.path.join(clip_dir, f'{clip_id}.mp4')
    subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', video_path, '-t', str(duration), '-vf', 'scale=640:-2', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-an', '-movflags', '+faststart', output_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not os.path.exists(output_path):
        return None
    return {'clipId': clip_id, 'filename': f'{clip_id}.mp4', 'startSecond': start, 'endSecond': start + duration, 'duration': duration, 'time': f'{format_timestamp(start)}–{format_timestamp(start + duration)} approx', 'type': event.get('type', 'review clip'), 'downloadPath': f'/analysis-jobs/{job_id}/clips/{clip_id}'}


def parse_json_safely(text: str):
    try:
        return json.loads(text)
    except Exception:
        try:
            return json.loads(text[text.index('{'):text.rindex('}') + 1])
        except Exception:
            return None


def normalise_scoreboard(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'visible': bool(raw.get('visible', False)),
        'text': str(raw.get('text', ''))[:120],
        'scoreChangeLikely': bool(raw.get('scoreChangeLikely', False)),
        'possibleScoreEvent': bool(raw.get('possibleScoreEvent', False)),
        'confidence': raw.get('confidence', 'low') if raw.get('confidence') in ['low', 'medium', 'high'] else 'low'
    }


def classify_event_frames(client: OpenAI, frame_paths: list, event: dict):
    if not frame_paths:
        return {'eventType': event.get('type', 'not_useful'), 'confidence': 'low', 'coachingValue': 'low', 'keepForReport': False, 'visibleCues': [], 'coachingReason': 'No frames available for classification.', 'visualSummary': '', 'scoreboard': normalise_scoreboard({})}

    content = [{
        'type': 'text',
        'text': f'''Classify this approximate Gaelic football review window using ONLY visible evidence from the frames.

Candidate time: {event.get('time')}
Initial candidate type: {event.get('type')}
Reason selected: {event.get('reason')}

Return valid JSON only with this exact shape:
{{
  "eventType": "one of {EVENT_TYPES}",
  "confidence": "low|medium|high",
  "coachingValue": "low|medium|high",
  "keepForReport": true,
  "visibleCues": ["short visible cue 1", "short visible cue 2"],
  "coachingReason": "one sentence on why a Gaelic football coach should review this",
  "visualSummary": "one concise Gaelic football tactical observation",
  "scoreboard": {{
    "visible": true,
    "text": "only scoreboard text you can read, otherwise empty string",
    "scoreChangeLikely": false,
    "possibleScoreEvent": false,
    "confidence": "low|medium|high"
  }}
}}

Scoreboard guidance:
- Only set scoreboard.visible true if a scoreboard or score bug is actually visible.
- Only copy scoreboard text if legible.
- Set possibleScoreEvent true if frames suggest a score, wide, free, restart after score, scoreboard change, umpire/goalkeeper restart, or players resetting after a score.
- Set scoreChangeLikely true only if a scoreboard appears to change within the frame pack or the visual sequence strongly suggests a just-completed score.

Do not invent scorers, exact scores, player names, or exact possession outcomes. Prefer Gaelic football cues: kickout shape, middle-third transition, D protection, support runners, direct ball inside, breaking ball, shot selection, counter-press, runners from deep, defensive screen.'''
    }]

    for frame_path in frame_paths:
        with open(frame_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
        content.append({'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{encoded}', 'detail': 'low'}})

    response = client.chat.completions.create(model='gpt-4o-mini', response_format={'type': 'json_object'}, messages=[{'role': 'user', 'content': content}])
    parsed = parse_json_safely(response.choices[0].message.content or '{}') or {}
    scoreboard = normalise_scoreboard(parsed.get('scoreboard', {}))
    event_type = parsed.get('eventType') if parsed.get('eventType') in EVENT_TYPES else event.get('type', 'not_useful')
    if scoreboard['possibleScoreEvent'] and event_type not in ['scoring_chance', 'score_or_restart_after_score']:
        event_type = 'score_or_restart_after_score'
    return {
        'eventType': event_type,
        'confidence': parsed.get('confidence', 'low'),
        'coachingValue': parsed.get('coachingValue', 'medium'),
        'keepForReport': bool(parsed.get('keepForReport', event_type != 'not_useful')),
        'visibleCues': parsed.get('visibleCues', []) if isinstance(parsed.get('visibleCues', []), list) else [],
        'coachingReason': parsed.get('coachingReason', ''),
        'visualSummary': parsed.get('visualSummary', ''),
        'scoreboard': scoreboard
    }


def build_event_candidates(url: str, metadata: dict, profile: dict, client: OpenAI | None = None, job_id: str | None = None):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            set_job_stage(job_id, 'download', 'Downloading match video for full-match scan')
            video_path = download_match_video(url, tmpdir, profile)
            if not video_path:
                return fallback_event_candidates(metadata)
            set_job_stage(job_id, 'full_match_scan', 'Extracting low-res scan frames and comparing movement changes')
            differences = scan_video_frame_differences(video_path, profile)
            set_job_stage(job_id, 'event_selection', 'Selecting the strongest candidate review windows')
            candidates = select_event_candidates_from_differences(differences) or fallback_event_candidates(metadata)
            if client:
                set_job_stage(job_id, 'event_analysis', 'Classifying visual frame packs and scoreboard/scoring cues')
                enriched = []
                clip_count = int(profile.get('clipCount', 6))
                for index, event in enumerate(candidates[:clip_count], start=1):
                    frame_paths = extract_event_frames(video_path, event, tmpdir, index, profile)
                    classification = classify_event_frames(client, frame_paths, event)
                    if not classification.get('keepForReport') and classification.get('coachingValue') == 'low':
                        continue
                    event_type = classification.get('eventType', event.get('type'))
                    event_for_clip = {**event, 'type': event_type}
                    clip = extract_event_clip(video_path, event_for_clip, job_id, index)
                    enriched.append({**event, 'type': event_type, 'classification': classification, 'visualAnalysis': classification.get('visualSummary', ''), 'scoreboard': classification.get('scoreboard'), 'framesAnalysed': len(frame_paths), 'clip': clip})
                return enriched + candidates[clip_count:]
            return candidates
    except Exception:
        return fallback_event_candidates(metadata)


def build_report_prompt(coached_team, opposition_team, match_facts, scoreline_rules, metadata, event_candidates, notes, profile):
    return f'''
You are an elite Gaelic football performance analyst working directly for {coached_team}.

Create a short Gaelic football manager debrief for {coached_team}. Use classified event evidence, scoreboard/scoring cues and clips as approximate review evidence, not absolute proof.

MATCH FACTS:
{match_facts}

SCORELINE-AWARE COACHING RULES:
{scoreline_rules}

VIDEO METADATA:
{metadata}

CLASSIFIED EVENT WINDOWS WITH SCOREBOARD/SCORING CUES, VISUAL ANALYSIS AND CLIPS:
{event_candidates}

COACH NOTES:
{notes}

PROCESSING PROFILE:
{profile}

RULES:
- This is Gaelic football. Use authentic GAA language: kickouts, breaking ball, middle third, runners from deep, direct ball inside, support runners, scoring zone, D protection, sweeper cover, counter-press after turnover, kick-pass threat, running game, shot selection, game management, scoring bursts, rest defence, defensive screen.
- Scoreboard text and score-event flags are approximate. Never invent exact scorers or exact scores from them.
- Do not contradict the user-provided final scoreline, winner or margin.
- Focus primarily on {coached_team}. Opposition analysis should only explain what hurt or exposed {coached_team}.
- Keep every table cell useful: never output only ✅, ❌ or ⚠️ by itself.
- No confidence notes. No long paragraphs.

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
| Scoring Bursts | use score/scoring-event cues if available + estimated label | use score/scoring-event cues if available + estimated label |
| Kickout / Restart Retention | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Breaking Ball | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Defensive Scores Conceded | based on opponent total + Gaelic football defensive label + ✅/⚠️/❌ | based on opponent total + Gaelic football defensive label + ✅/⚠️/❌ |

# {coached_team} – Tactical Comparison
| Area | {coached_team} | {opposition_team} |
|---|---|---|
| Transition Through Middle Third | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Direct Ball Inside | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Kick-Pass Threat | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Shot Selection | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Goal Threat | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Turnovers / Counter-Press | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| Kickout Platform | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |
| D Protection / Defensive Screen | Gaelic football observation + ✅/⚠️/❌ | Gaelic football observation + ✅/⚠️/❌ |

# {coached_team} – Review Clips
| Clip | Event Type | Why Review It |
|---|---|---|
| Use available clip links from classified events | event type | one specific coaching reason |

# {coached_team} – Main Focus Areas Going Forward
| Priority | Why It Matters For {coached_team} | Coaching Action |
|---|---|---|
| Specific Gaelic football focus area 1 | Match-specific reason linked to Gaelic football patterns | Practical training action for {coached_team} |
| Specific Gaelic football focus area 2 | Match-specific reason linked to Gaelic football patterns | Practical training action for {coached_team} |
| Specific Gaelic football focus area 3 | Match-specific reason linked to Gaelic football patterns | Practical training action for {coached_team} |

# {coached_team} – Key Manager Takeaway
One short quote, maximum 55 words. Make it direct, honest and Gaelic football-specific.
'''


def generate_analysis(request: AnalyseRequest, job_id: str | None = None):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing')
    client = OpenAI(api_key=api_key)
    profile = processing_profile(request.url)
    set_job_stage(job_id, 'metadata', 'Reading video title, duration and match metadata')
    metadata = extract_video_metadata(request.url)
    event_candidates = build_event_candidates(request.url, metadata, profile, client, job_id)
    set_job_stage(job_id, 'clip_extraction', 'Review clips created for selected moments')
    match_facts = build_match_facts(request.matchContext or {})
    coached_team = match_facts['coachedTeam']
    opposition_team = match_facts['teamB'] if match_facts['teamA'] == coached_team else match_facts['teamA']
    prompt = build_report_prompt(coached_team, opposition_team, match_facts, build_scoreline_rules(match_facts), metadata, event_candidates, request.notes, profile)
    set_job_stage(job_id, 'report', 'Building final manager debrief report')
    response = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'system', 'content': 'You produce concise Gaelic football manager debrief reports using classified event evidence, scoreboard/scoring cues, scoreline-aware tactical insights, estimated key stats and actionable training priorities.'}, {'role': 'user', 'content': prompt}])
    analysis = response.choices[0].message.content
    clips = [event.get('clip') for event in event_candidates if isinstance(event, dict) and event.get('clip')]
    classifications = [event.get('classification') for event in event_candidates if isinstance(event, dict) and event.get('classification')]
    scoreboard_events = [event for event in event_candidates if isinstance(event, dict) and event.get('scoreboard', {}).get('visible')]
    scoring_cues = [event for event in event_candidates if isinstance(event, dict) and event.get('scoreboard', {}).get('possibleScoreEvent')]
    return {'status': 'complete', 'mode': 'worker', 'analysis': analysis, 'videoMetadata': metadata, 'matchFacts': match_facts, 'processingProfile': profile['name'], 'eventCandidates': event_candidates, 'eventClassifications': classifications, 'scoreboardEvents': scoreboard_events, 'scoringCues': scoring_cues, 'clips': clips}


def run_analysis_job(job_id: str, request: AnalyseRequest):
    try:
        jobs[job_id]['result'] = generate_analysis(request, job_id)
        jobs[job_id]['status'] = 'complete'
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
    jobs[job_id] = {'jobId': job_id, 'status': 'processing', 'stage': 'queued', 'progress': PROGRESS_STAGES['queued'], 'detail': 'Queued for analysis', 'createdAt': datetime.utcnow().isoformat(), 'updatedAt': datetime.utcnow().isoformat(), 'result': None, 'error': None}
    background_tasks.add_task(run_analysis_job, job_id, request)
    return {'jobId': job_id, 'status': 'processing', 'progress': PROGRESS_STAGES['queued']}

@app.get('/analysis-jobs/{job_id}')
def get_analysis_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail='Job not found')
    return jobs[job_id]

@app.get('/analysis-jobs/{job_id}/clips/{clip_id}')
def download_clip(job_id: str, clip_id: str):
    clip_path = os.path.join(CLIP_ROOT, job_id, f'{clip_id}.mp4')
    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail='Clip not found or expired')
    return FileResponse(clip_path, media_type='video/mp4', filename=f'{clip_id}.mp4')
