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
    'event_analysis': {'percent': 72, 'label': 'Classifying tactical and score outcomes'},
    'clip_extraction': {'percent': 82, 'label': 'Creating review clips'},
    'report': {'percent': 92, 'label': 'Building Gaelic football report'},
    'complete': {'percent': 100, 'label': 'Report ready'},
    'failed': {'percent': 100, 'label': 'Analysis failed'}
}

EVENT_TYPES = [
    'kickout_restart', 'turnover', 'fast_transition', 'scoring_chance',
    'score_or_restart_after_score', 'defensive_setup', 'breaking_ball',
    'slow_possession', 'game_management', 'not_useful'
]

SCORE_OUTCOMES = ['point', 'goal', 'wide', 'save', 'blocked', 'unknown']

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
        return {'name': 'quick-veo', 'scanIntervalSeconds': 2, 'eventFramePack': 6, 'videoFormat': 'best[height<=360]/best', 'clipCount': 4}
    return {'name': 'standard', 'scanIntervalSeconds': 1, 'eventFramePack': 8, 'videoFormat': 'best[height<=480]/best', 'clipCount': 6}


def format_timestamp(seconds: int):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def parse_json_safely(text: str):
    try:
        return json.loads(text)
    except Exception:
        try:
            return json.loads(text[text.index('{'):text.rindex('}') + 1])
        except Exception:
            return None


def image_content_from_paths(paths):
    content = []
    for item in paths:
        path = item['path'] if isinstance(item, dict) else item
        with open(path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
        content.append({'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{encoded}', 'detail': 'low'}})
    return content


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


def build_match_facts(ctx: dict):
    team_a = ctx.get('teamA', 'Team A')
    team_b = ctx.get('teamB', 'Team B')
    coached = ctx.get('coachedTeam', team_a)
    ag, ap = int(ctx.get('teamAGoals') or 0), int(ctx.get('teamAPoints') or 0)
    bg, bp = int(ctx.get('teamBGoals') or 0), int(ctx.get('teamBPoints') or 0)
    at, bt = ag * 3 + ap, bg * 3 + bp
    if at > bt:
        winner, margin = team_a, at - bt
    elif bt > at:
        winner, margin = team_b, bt - at
    else:
        winner, margin = 'Draw', 0
    result = 'drew' if winner == 'Draw' else ('won' if winner == coached else 'lost')
    cg, og = (ag, bg) if coached == team_a else (bg, ag)
    cp, op = (ap, bp) if coached == team_a else (bp, ap)
    ct, ot = (at, bt) if coached == team_a else (bt, at)
    return {
        'teamA': team_a, 'teamB': team_b, 'coachedTeam': coached, 'winner': winner, 'margin': margin,
        'coachedTeamResult': result, 'teamAGoals': ag, 'teamBGoals': bg, 'teamAPoints': ap,
        'teamBPoints': bp, 'teamATotal': at, 'teamBTotal': bt, 'coachedGoals': cg,
        'oppositionGoals': og, 'coachedPoints': cp, 'oppositionPoints': op,
        'coachedTotal': ct, 'oppositionTotal': ot, 'goalDifference': cg - og,
        'scoreline': f'{team_a} {ag}-{ap} ({at}) vs {team_b} {bg}-{bp} ({bt})'
    }


def build_scoreline_rules(facts: dict):
    team = facts['coachedTeam']
    rules = []
    if facts['coachedGoals'] >= 5:
        rules.append(f'{team} scored {facts["coachedGoals"]} goals. Treat goal scoring, finishing and attacking penetration as major strengths. Do NOT recommend finishing practice or improving goal threat unless coach notes explicitly say chances were wasted.')
        rules.append(f'For {team}, focus on sustaining attacking patterns, game management, rest defence, kickout control, and protecting against counterattacks.')
    elif facts['coachedGoals'] <= 1 and facts['coachedTeamResult'] != 'won':
        rules.append(f'{team} had limited goal output. It is valid to focus on penetration, high-value chance creation and earlier delivery into scoring zones.')
    if facts['oppositionGoals'] >= 3:
        rules.append(f'{team} conceded {facts["oppositionGoals"]} goals. Prioritise defensive transition, central goal channels, sweeper cover and recovery shape.')
    elif facts['oppositionGoals'] <= 1:
        rules.append(f'{team} conceded {facts["oppositionGoals"]} goals. Do not overstate defensive collapse; frame defensive work as refinement.')
    if facts['coachedTeamResult'] == 'won' and facts['margin'] >= 10:
        rules.append(f'{team} won comfortably. Focus areas should sustain strengths and tighten risk areas, not imply poor performance.')
    if facts['coachedTeamResult'] == 'lost' and facts['margin'] <= 3:
        rules.append(f'{team} lost narrowly. Focus on swing factors: one goal chance, one kickout spell, one transition concession, or late-game decision-making.')
    return '\n'.join(f'- {rule}' for rule in rules) or '- Apply normal Gaelic football scoreline reasoning.'


def normalise_scoreboard(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'visible': bool(raw.get('visible', False)),
        'text': str(raw.get('text', ''))[:160],
        'scoreChangeLikely': bool(raw.get('scoreChangeLikely', False)),
        'possibleScoreEvent': bool(raw.get('possibleScoreEvent', False)),
        'confidence': raw.get('confidence', 'low') if raw.get('confidence') in ['low', 'medium', 'high'] else 'low',
        'ocrText': str(raw.get('ocrText', ''))[:160],
        'ocrZones': raw.get('ocrZones', []) if isinstance(raw.get('ocrZones', []), list) else []
    }


def normalise_score_outcome(raw):
    raw = raw if isinstance(raw, dict) else {}
    outcome = raw.get('outcome') if raw.get('outcome') in SCORE_OUTCOMES else 'unknown'
    confidence = raw.get('confidence') if raw.get('confidence') in ['low', 'medium', 'high'] else 'low'
    evidence = raw.get('evidence', []) if isinstance(raw.get('evidence', []), list) else []
    cues = raw.get('cues', {}) if isinstance(raw.get('cues', {}), dict) else {}
    return {
        'outcome': outcome,
        'confidence': confidence,
        'evidence': evidence[:8],
        'reasoning': str(raw.get('reasoning', ''))[:300],
        'cues': {
            'scoreboardChange': bool(cues.get('scoreboardChange', False)),
            'umpireSignal': str(cues.get('umpireSignal', 'not_visible'))[:80],
            'ballPath': str(cues.get('ballPath', 'unclear'))[:80],
            'netMovement': bool(cues.get('netMovement', False)),
            'goalkeeperRetrieval': bool(cues.get('goalkeeperRetrieval', False)),
            'goalkeeperRestart': bool(cues.get('goalkeeperRestart', False)),
            'playerReaction': str(cues.get('playerReaction', 'unclear'))[:120],
            'cameraReset': bool(cues.get('cameraReset', False)),
            'crowdReaction': str(cues.get('crowdReaction', 'not_available'))[:80]
        }
    }


def fallback_event_candidates(metadata: dict):
    duration = int(metadata.get('duration') or 0)
    times = [360, 1080, 2160, 3240] if duration <= 0 else [int(duration * f) for f in [0.12, 0.25, 0.38, 0.52, 0.68, 0.82]]
    labels = ['kickout_restart', 'fast_transition', 'scoring_chance', 'breaking_ball', 'defensive_setup', 'game_management']
    events = []
    for index, seconds in enumerate(times):
        event_type = labels[index % len(labels)]
        events.append({
            'time': f'{format_timestamp(seconds)} approx',
            'startSecond': max(0, seconds - 15),
            'endSecond': seconds + 15,
            'type': event_type,
            'reason': 'Fallback checkpoint selected from match timeline.',
            'confidence': 'low',
            'classification': {
                'eventType': event_type,
                'confidence': 'low',
                'coachingValue': 'medium',
                'keepForReport': True,
                'visibleCues': ['Fallback timeline checkpoint'],
                'coachingReason': 'Useful broad tactical review window when scan evidence is limited.',
                'scoreboard': normalise_scoreboard({}),
                'scoreOutcome': normalise_score_outcome({})
            },
            'scoreOutcome': normalise_score_outcome({})
        })
    return events


def download_match_video(url: str, tmpdir: str, profile: dict):
    path = os.path.join(tmpdir, 'match.mp4')
    opts = {
        'format': profile.get('videoFormat', 'best[height<=480]/best'),
        'outtmpl': path,
        'quiet': False,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'retries': 2,
        'fragment_retries': 2
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return path if os.path.exists(path) else None


def scan_video_frame_differences(video_path: str, profile: dict, max_scan_seconds: int = 7200):
    interval = int(profile.get('scanIntervalSeconds', 1))
    width, height = 64, 36
    frame_size = width * height
    cmd = ['ffmpeg', '-i', video_path, '-vf', f'fps=1/{interval},scale={width}:{height},format=gray', '-frames:v', str(max_scan_seconds // interval), '-f', 'rawvideo', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    prev, diffs, idx = None, [], 0
    try:
        while True:
            frame = p.stdout.read(frame_size) if p.stdout else b''
            if not frame or len(frame) < frame_size:
                break
            if prev is not None:
                diff = sum(abs(frame[i] - prev[i]) for i in range(frame_size)) / frame_size
                diffs.append({'second': idx * interval, 'difference': round(diff, 2)})
            prev = frame
            idx += 1
    finally:
        try:
            p.kill()
        except Exception:
            pass
    return diffs


def classify_event_window(index: int):
    cycle = ['kickout_restart', 'fast_transition', 'scoring_chance', 'score_or_restart_after_score', 'breaking_ball', 'defensive_setup', 'game_management', 'turnover', 'direct_ball_inside']
    return cycle[index % len(cycle)]


def select_event_candidates_from_differences(differences: list, max_events: int = 10):
    if not differences:
        return []
    selected = []
    for item in sorted(differences, key=lambda x: x['difference'], reverse=True):
        second = int(item['second'])
        if all(abs(second - e['startSecond']) > 150 for e in selected):
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
    return sorted(selected, key=lambda x: x['startSecond'])


def extract_event_frames(video_path: str, event: dict, tmpdir: str, event_index: int, profile: dict):
    count = int(profile.get('eventFramePack', 8))
    start = max(0, int(event.get('startSecond', 0)))
    end = max(start + 1, int(event.get('endSecond', start + 30)))
    duration = max(1, end - start)
    fps = max(0.1, count / duration)
    pattern = os.path.join(tmpdir, f'event_{event_index}_%02d.jpg')
    subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', video_path, '-t', str(duration), '-vf', f'fps={fps},scale=768:-1', '-frames:v', str(count), pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith(f'event_{event_index}_') and f.endswith('.jpg')])[:count]


def extract_scoreboard_crops(video_path: str, event: dict, tmpdir: str, event_index: int):
    start = max(0, int(event.get('startSecond', 0)))
    end = max(start + 1, int(event.get('endSecond', start + 30)))
    timestamp = start + max(1, int((end - start) / 2))
    crop_specs = [
        ('top_left', 'crop=iw*0.42:ih*0.18:0:0,scale=900:-1'),
        ('top_right', 'crop=iw*0.42:ih*0.18:iw*0.58:0,scale=900:-1'),
        ('top_full', 'crop=iw:ih*0.20:0:0,scale=1200:-1')
    ]
    crops = []
    for name, vf in crop_specs:
        output = os.path.join(tmpdir, f'ocr_{event_index}_{name}.jpg')
        subprocess.run(['ffmpeg', '-y', '-ss', str(timestamp), '-i', video_path, '-frames:v', '1', '-vf', vf, output], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if os.path.exists(output):
            crops.append({'zone': name, 'path': output})
    return crops


def extract_event_clip(video_path: str, event: dict, job_id: str | None, event_index: int):
    if not job_id:
        return None
    clip_dir = os.path.join(CLIP_ROOT, job_id)
    os.makedirs(clip_dir, exist_ok=True)
    start = max(0, int(event.get('startSecond', 0)))
    end = max(start + 1, int(event.get('endSecond', start + 30)))
    duration = min(45, max(8, end - start))
    clip_id = f'clip_{event_index:02d}'
    output = os.path.join(clip_dir, f'{clip_id}.mp4')
    subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', video_path, '-t', str(duration), '-vf', 'scale=640:-2', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-an', '-movflags', '+faststart', output], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not os.path.exists(output):
        return None
    return {
        'clipId': clip_id,
        'filename': f'{clip_id}.mp4',
        'startSecond': start,
        'endSecond': start + duration,
        'duration': duration,
        'time': f'{format_timestamp(start)}–{format_timestamp(start + duration)} approx',
        'type': event.get('type', 'review clip'),
        'downloadPath': f'/analysis-jobs/{job_id}/clips/{clip_id}'
    }


def read_scoreboard_ocr(client: OpenAI, crop_items: list):
    if not crop_items:
        return normalise_scoreboard({})
    content = [{'type': 'text', 'text': 'Read any visible Gaelic football scoreboard or score bug from these cropped image zones. Return JSON only: {"visible": true, "ocrText": "exact readable scoreboard text only", "ocrZones": ["top_left"], "confidence": "low|medium|high"}. If no scoreboard is readable, return {"visible": false, "ocrText": "", "ocrZones": [], "confidence": "low"}. Do not guess.'}]
    content += image_content_from_paths(crop_items)
    response = client.chat.completions.create(model='gpt-4o-mini', response_format={'type': 'json_object'}, messages=[{'role': 'user', 'content': content}])
    parsed = parse_json_safely(response.choices[0].message.content or '{}') or {}
    return normalise_scoreboard({'visible': parsed.get('visible'), 'ocrText': parsed.get('ocrText', ''), 'text': parsed.get('ocrText', ''), 'ocrZones': parsed.get('ocrZones', []), 'confidence': parsed.get('confidence', 'low')})


def classify_event_frames(client: OpenAI, frame_paths: list, event: dict, scoreboard_ocr: dict):
    if not frame_paths:
        return {
            'eventType': event.get('type', 'not_useful'),
            'confidence': 'low',
            'coachingValue': 'low',
            'keepForReport': False,
            'visibleCues': [],
            'coachingReason': 'No frames available for classification.',
            'visualSummary': '',
            'scoreboard': scoreboard_ocr,
            'scoreOutcome': normalise_score_outcome({})
        }

    content = [{
        'type': 'text',
        'text': f'''Classify this Gaelic football review window using ONLY visible evidence from the frames.

Candidate time: {event.get('time')}
Initial candidate type: {event.get('type')}
Reason selected: {event.get('reason')}
OCR scoreboard crop result: {scoreboard_ocr}

Return valid JSON only with this exact shape:
{{
  "eventType": "one of {EVENT_TYPES}",
  "confidence": "low|medium|high",
  "coachingValue": "low|medium|high",
  "keepForReport": true,
  "visibleCues": ["short visible cue"],
  "coachingReason": "one sentence",
  "visualSummary": "one concise Gaelic football tactical observation",
  "scoreboard": {{
    "visible": true,
    "text": "scoreboard text you can read or OCR text",
    "scoreChangeLikely": false,
    "possibleScoreEvent": false,
    "confidence": "low|medium|high"
  }},
  "scoreOutcome": {{
    "outcome": "point|goal|wide|save|blocked|unknown",
    "confidence": "low|medium|high",
    "evidence": ["specific visible evidence"],
    "reasoning": "short explanation",
    "cues": {{
      "scoreboardChange": false,
      "umpireSignal": "white_flag|green_flag|wide_signal|not_visible|unclear",
      "ballPath": "between_posts|outside_posts|towards_goal|saved|blocked|unclear",
      "netMovement": false,
      "goalkeeperRetrieval": false,
      "goalkeeperRestart": false,
      "playerReaction": "celebration|frustration|reset|unclear",
      "cameraReset": false,
      "crowdReaction": "spike|normal|not_available"
    }}
  }}
}}

Conservative Gaelic football scoring rules:
- Only classify POINT if there is strong evidence: scoreboard change, umpire white flag, or a clearly visible ball path between the posts.
- Only classify GOAL if there is strong evidence: umpire green flag, ball/net movement in goal, goalkeeper retrieval from net, or scoreboard goal change.
- Classify WIDE if the umpire wide signal is visible, ball path is clearly outside the posts, or player/reset cues strongly support a wide.
- Classify SAVE if goalkeeper/body save is visible or ball is stopped on/near goal line.
- Classify BLOCKED if defender blocks the shot before it reaches scoring zone.
- If the clip only shows a kickout/restart and no clear outcome, use UNKNOWN, not point.
- Scoreboard is helpful but often absent in amateur footage. Do not require it, but do not invent it.
- Never invent scorers, exact scores, player names, or exact possession outcomes.'''
    }]
    content += image_content_from_paths(frame_paths)

    response = client.chat.completions.create(model='gpt-4o-mini', response_format={'type': 'json_object'}, messages=[{'role': 'user', 'content': content}])
    parsed = parse_json_safely(response.choices[0].message.content or '{}') or {}
    parsed_scoreboard = parsed.get('scoreboard', {}) if isinstance(parsed.get('scoreboard'), dict) else {}
    scoreboard = normalise_scoreboard({**scoreboard_ocr, **parsed_scoreboard})
    if not scoreboard.get('text') and scoreboard.get('ocrText'):
        scoreboard['text'] = scoreboard['ocrText']
    score_outcome = normalise_score_outcome(parsed.get('scoreOutcome', {}))

    event_type = parsed.get('eventType') if parsed.get('eventType') in EVENT_TYPES else event.get('type', 'not_useful')
    if score_outcome['outcome'] in ['point', 'goal', 'wide'] or scoreboard['possibleScoreEvent']:
        if event_type not in ['scoring_chance', 'score_or_restart_after_score']:
            event_type = 'score_or_restart_after_score'

    return {
        'eventType': event_type,
        'confidence': parsed.get('confidence', 'low'),
        'coachingValue': parsed.get('coachingValue', 'medium'),
        'keepForReport': bool(parsed.get('keepForReport', event_type != 'not_useful')),
        'visibleCues': parsed.get('visibleCues', []) if isinstance(parsed.get('visibleCues', []), list) else [],
        'coachingReason': parsed.get('coachingReason', ''),
        'visualSummary': parsed.get('visualSummary', ''),
        'scoreboard': scoreboard,
        'scoreOutcome': score_outcome
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
                set_job_stage(job_id, 'event_analysis', 'Classifying tactical events, score outcomes and scoreboard cues')
                enriched = []
                clip_count = int(profile.get('clipCount', 6))
                for index, event in enumerate(candidates[:clip_count], start=1):
                    frame_paths = extract_event_frames(video_path, event, tmpdir, index, profile)
                    scoreboard_ocr = read_scoreboard_ocr(client, extract_scoreboard_crops(video_path, event, tmpdir, index))
                    classification = classify_event_frames(client, frame_paths, event, scoreboard_ocr)
                    if not classification.get('keepForReport') and classification.get('coachingValue') == 'low':
                        continue
                    event_type = classification.get('eventType', event.get('type'))
                    clip = extract_event_clip(video_path, {**event, 'type': event_type}, job_id, index)
                    enriched.append({
                        **event,
                        'type': event_type,
                        'classification': classification,
                        'visualAnalysis': classification.get('visualSummary', ''),
                        'scoreboard': classification.get('scoreboard'),
                        'scoreOutcome': classification.get('scoreOutcome'),
                        'framesAnalysed': len(frame_paths),
                        'clip': clip
                    })
                return enriched + candidates[clip_count:]
            return candidates
    except Exception:
        return fallback_event_candidates(metadata)


def build_report_prompt(coached_team, opposition_team, facts, rules, metadata, events, notes, profile):
    return f'''
You are an elite Gaelic football performance analyst working directly for {coached_team}.
Create a short Gaelic football manager debrief for {coached_team}. Use classified event evidence, score outcome cues, OCR scoreboard reads and clips as approximate review evidence, not absolute proof.

MATCH FACTS:
{facts}
SCORELINE-AWARE COACHING RULES:
{rules}
VIDEO METADATA:
{metadata}
CLASSIFIED EVENT WINDOWS WITH SCORE OUTCOMES, VISUAL ANALYSIS AND CLIPS:
{events}
COACH NOTES:
{notes}
PROCESSING PROFILE:
{profile}

RULES:
- This is Gaelic football. Use GAA language: kickouts, breaking ball, middle third, runners from deep, direct ball inside, support runners, scoring zone, D protection, sweeper cover, counter-press after turnover, kick-pass threat, running game, shot selection, game management, scoring bursts, rest defence.
- scoreOutcome is approximate. Use point/goal/wide/save/blocked only when the event evidence supports it. If unclear, say likely scoring/restart phase or unknown outcome.
- Never contradict the user-provided final scoreline. Never invent scorers.
- Focus primarily on {coached_team}. Keep table cells useful. No confidence notes. No long paragraphs.

Return this exact markdown structure and nothing else:
# {coached_team} – Match Snapshot
| Item | Detail |
|---|---|
| Scoreline | {facts['scoreline']} |
| Result | {coached_team} {facts['coachedTeamResult']} by {facts['margin']} point(s) |
| Core Story | One direct Gaelic football tactical sentence explaining why the game went this way from the perspective of {coached_team}. |

# {coached_team} – Match-Deciding Factor
One blunt Gaelic football paragraph, maximum 45 words. Explain the one factor that most shaped the result for {coached_team}.

# {coached_team} – Estimated Key Match Stats
| Metric | {coached_team} | {opposition_team} |
|---|---|---|
| Possession | estimated range/label + Gaelic football observation + ✅/⚠️/❌ | estimated range/label + Gaelic football observation + ✅/⚠️/❌ |
| Shot Creation | estimated label + Gaelic football observation + ✅/⚠️/❌ | estimated label + Gaelic football observation + ✅/⚠️/❌ |
| Goal Threat | {facts['coachedGoals']} goals + Gaelic football tactical label + ✅/⚠️/❌ | {facts['oppositionGoals']} goals + Gaelic football tactical label + ✅/⚠️/❌ |
| Point Output | {facts['coachedPoints']} points + Gaelic football tactical label + ✅/⚠️/❌ | {facts['oppositionPoints']} points + Gaelic football tactical label + ✅/⚠️/❌ |
| Scoring Bursts | use score outcome cues if available + estimated label | use score outcome cues if available + estimated label |
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
| Clip | Event Type | Score Outcome | Why Review It |
|---|---|---|---|
| Use available clip links from classified events | event type | point/goal/wide/save/blocked/unknown | one specific coaching reason |

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
    events = build_event_candidates(request.url, metadata, profile, client, job_id)
    set_job_stage(job_id, 'clip_extraction', 'Review clips created for selected moments')
    facts = build_match_facts(request.matchContext or {})
    coached = facts['coachedTeam']
    opposition = facts['teamB'] if facts['teamA'] == coached else facts['teamA']
    prompt = build_report_prompt(coached, opposition, facts, build_scoreline_rules(facts), metadata, events, request.notes, profile)
    set_job_stage(job_id, 'report', 'Building final manager debrief report')
    response = client.chat.completions.create(model='gpt-4o-mini', messages=[
        {'role': 'system', 'content': 'You produce concise Gaelic football manager debrief reports using classified event evidence, score outcome cues, scoreline-aware tactical insights and actionable training priorities.'},
        {'role': 'user', 'content': prompt}
    ])
    clips = [e.get('clip') for e in events if isinstance(e, dict) and e.get('clip')]
    classifications = [e.get('classification') for e in events if isinstance(e, dict) and e.get('classification')]
    scoreboard_events = [e for e in events if isinstance(e, dict) and e.get('scoreboard', {}).get('visible')]
    scoring_cues = [e for e in events if isinstance(e, dict) and e.get('scoreOutcome', {}).get('outcome') != 'unknown']
    return {
        'status': 'complete',
        'mode': 'worker',
        'analysis': response.choices[0].message.content,
        'videoMetadata': metadata,
        'matchFacts': facts,
        'processingProfile': profile['name'],
        'eventCandidates': events,
        'eventClassifications': classifications,
        'scoreboardEvents': scoreboard_events,
        'scoringCues': scoring_cues,
        'clips': clips
    }


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
