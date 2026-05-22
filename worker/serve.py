import tempfile
import uuid
from datetime import datetime

import main
from main import app, HTTPException

try:
    from video_ingestion import extract_video_metadata as robust_extract_video_metadata
    from video_ingestion import download_match_video as robust_download_match_video
except Exception:
    robust_extract_video_metadata = None
    robust_download_match_video = None

try:
    from cv_integration import cv_status, run_cv_on_event
except Exception:
    def cv_status():
        return {
            'enabled': False,
            'phase': 'player_detection_team_colour_shape',
            'reason': 'cv_integration module unavailable'
        }

    def run_cv_on_event(video_path, start_second, end_second):
        return {
            'enabled': False,
            'status': 'unavailable',
            'reason': 'cv_integration module unavailable'
        }


ORIGINAL_BUILD_EVENT_CANDIDATES = main.build_event_candidates
ORIGINAL_AGGREGATE_EVIDENCE = main.aggregate_evidence
ORIGINAL_BUILD_REPORT_PROMPT = main.build_report_prompt
ORIGINAL_GENERATE_ANALYSIS = main.generate_analysis
ORIGINAL_FALLBACK_EVENT_CANDIDATES = main.fallback_event_candidates
ORIGINAL_SCAN_VIDEO_FRAME_DIFFERENCES = main.scan_video_frame_differences
DEBUG_REPORTS = {}
LATEST_DEBUG_REPORT_ID = None
VIDEO_INGESTION_STATUS = {
    'enabled': bool(robust_extract_video_metadata and robust_download_match_video),
    'metadataPatch': bool(robust_extract_video_metadata),
    'downloadPatch': bool(robust_download_match_video),
}
LAST_DOWNLOAD_DEBUG = {}
LAST_SCAN_DEBUG = {}
PROCESS_LOG = []


def log_step(stage, detail=None):
    entry = {'time': datetime.utcnow().isoformat(), 'stage': stage, 'detail': detail or ''}
    PROCESS_LOG.append(entry)
    if len(PROCESS_LOG) > 80:
        del PROCESS_LOG[:-80]
    print(f"[GAELIC_AI] {stage}: {detail or ''}", flush=True)


def is_uploaded_storage_url(url):
    lower = (url or '').lower()
    return 'storage.googleapis.com' in lower or 'googleapis.com' in lower


@app.get('/cv-status')
def get_cv_status():
    status = cv_status()
    status['videoIngestion'] = VIDEO_INGESTION_STATUS
    return status


@app.get('/debug-report/latest')
def get_latest_debug_report():
    if not LATEST_DEBUG_REPORT_ID or LATEST_DEBUG_REPORT_ID not in DEBUG_REPORTS:
        raise HTTPException(status_code=404, detail='No debug report has been generated since the worker last restarted.')
    return DEBUG_REPORTS[LATEST_DEBUG_REPORT_ID]


@app.get('/debug-report/{report_id}')
def get_debug_report(report_id: str):
    if report_id not in DEBUG_REPORTS:
        raise HTTPException(status_code=404, detail='Debug report not found. Generate a fresh report after this endpoint is deployed.')
    return DEBUG_REPORTS[report_id]


def download_match_video_with_debug(url, tmpdir, profile):
    global LAST_DOWNLOAD_DEBUG
    log_step('download_start', {'url': url, 'tmpdir': tmpdir, 'format': (profile or {}).get('videoFormat')})
    LAST_DOWNLOAD_DEBUG = {'attempted': True, 'ok': False, 'error': '', 'path': '', 'tmpdir': tmpdir, 'profileFormat': (profile or {}).get('videoFormat')}
    if not robust_download_match_video:
        LAST_DOWNLOAD_DEBUG['error'] = 'robust_download_match_video unavailable'
        log_step('download_unavailable', LAST_DOWNLOAD_DEBUG)
        return None
    try:
        path = robust_download_match_video(url, tmpdir, profile or {})
        LAST_DOWNLOAD_DEBUG['path'] = path or ''
        LAST_DOWNLOAD_DEBUG['ok'] = bool(path)
        try:
            import os, json
            debug_path = os.path.join(tmpdir, 'download_debug.json')
            if os.path.exists(debug_path):
                with open(debug_path, 'r', encoding='utf-8') as handle:
                    LAST_DOWNLOAD_DEBUG.update(json.load(handle))
        except Exception as exc:
            LAST_DOWNLOAD_DEBUG['debugReadError'] = str(exc)[:500]
        log_step('download_complete' if path else 'download_failed', LAST_DOWNLOAD_DEBUG)
        return path
    except Exception as exc:
        LAST_DOWNLOAD_DEBUG['error'] = str(exc)[:1000]
        log_step('download_exception', LAST_DOWNLOAD_DEBUG)
        return None


def scan_video_frame_differences_with_debug(video_path, profile, max_scan_seconds=7200):
    global LAST_SCAN_DEBUG
    if int((profile or {}).get('maxScanSeconds') or 0) > 0:
        max_scan_seconds = int(profile.get('maxScanSeconds'))
    log_step('scan_start', {'videoPath': video_path, 'interval': (profile or {}).get('scanIntervalSeconds'), 'maxScanSeconds': max_scan_seconds})
    LAST_SCAN_DEBUG = {'attempted': True, 'ok': False, 'error': '', 'videoPath': video_path or '', 'scanIntervalSeconds': (profile or {}).get('scanIntervalSeconds'), 'maxScanSeconds': max_scan_seconds, 'differenceCount': 0}
    try:
        differences = ORIGINAL_SCAN_VIDEO_FRAME_DIFFERENCES(video_path, profile, max_scan_seconds)
        LAST_SCAN_DEBUG['differenceCount'] = len(differences or [])
        LAST_SCAN_DEBUG['ok'] = bool(differences)
        log_step('scan_complete', LAST_SCAN_DEBUG)
        return differences
    except Exception as exc:
        LAST_SCAN_DEBUG['error'] = str(exc)[:1000]
        log_step('scan_exception', LAST_SCAN_DEBUG)
        return []


def dense_fallback_event_candidates(metadata):
    duration = int((metadata or {}).get('duration') or 0) or 4200
    count = 80
    gap = max(30, duration // count)
    log_step('dense_fallback_start', {'duration': duration, 'count': count, 'gap': gap})
    labels = ['kickout_restart','slow_possession','fast_transition','scoring_chance','breaking_ball','defensive_setup','turnover','game_management']
    events = []
    second = 60
    index = 0
    while second < duration - 60 and len(events) < count:
        event_type = labels[index % len(labels)]
        events.append({'time': f'{main.format_timestamp(second)} approx','startSecond': max(0, second - 12),'endSecond': second + 18,'type': event_type,'reason': 'Dense fallback tactical checkpoint selected because video metadata/download scanning was unavailable.','confidence': 'low','scoreOutcome': main.norm_score_outcome({}),'matchIntelligence': main.norm_match_intel({}),'fallbackMode': 'dense_duration_fallback'})
        second += gap
        index += 1
    log_step('dense_fallback_complete', {'events': len(events)})
    return events


def dominant_colour(cv_result):
    colours = (cv_result or {}).get('teamColourCounts') or {}
    if not colours:
        return 'unknown'
    return max(colours, key=colours.get)


def track_possession_and_turnovers(events):
    previous_colour = None
    possessions = {}
    turnovers = 0
    kickout_estimates = 0
    retained_kickouts = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        cv_result = event.get('cvPlayerDetection') or {}
        colour = dominant_colour(cv_result)
        event_type = event.get('type')
        if colour != 'unknown':
            possessions[colour] = possessions.get(colour, 0) + 1
        if previous_colour and colour != 'unknown' and colour != previous_colour:
            turnovers += 1
        if event_type == 'kickout_restart':
            kickout_estimates += 1
            if colour == previous_colour and colour != 'unknown':
                retained_kickouts += 1
        previous_colour = colour if colour != 'unknown' else previous_colour
    total = sum(possessions.values())
    possession_share = {colour: f"{int((count / max(1, total)) * 100)}%" for colour, count in possessions.items()}
    return {'dominantPossessionColours': possession_share,'estimatedTurnoversFromContinuity': turnovers,'estimatedKickoutRetentions': retained_kickouts,'estimatedKickoutsTracked': kickout_estimates,'confidence': 'medium' if total >= 6 else 'low'}


def estimate_gaelic_stats(events, match_evidence):
    tracker = track_possession_and_turnovers(events)
    return {'estimatedTurnoversFromContinuity': tracker.get('estimatedTurnoversFromContinuity', 0),'estimatedKickoutRetentions': tracker.get('estimatedKickoutRetentions', 0),'estimatedKickoutsTracked': tracker.get('estimatedKickoutsTracked', 0),'dominantPossessionColours': tracker.get('dominantPossessionColours', {}),'trackerConfidence': tracker.get('confidence', 'low'),'cvWidthCue': match_evidence.get('cvWidthCue', 'unknown'),'cvCompactnessCue': match_evidence.get('cvCompactnessCue', 'unknown'),'cvOverloadCue': match_evidence.get('cvOverloadCue', 'unknown')}


def value_or_unknown(value, confidence='Estimated'):
    if value in [None, '', 'unknown']:
        return {'value': 'Unknown', 'confidence': 'Low confidence'}
    return {'value': value, 'confidence': confidence}


def build_manager_stat_summary(facts, evidence):
    transition_negative = int(evidence.get('transitionNegative') or 0)
    transition_positive = int(evidence.get('transitionPositive') or 0)
    turnovers_against = int(evidence.get('turnoversAgainst') or 0)
    turnovers_for = int(evidence.get('turnoversFor') or 0)
    breaking_balls = int(evidence.get('breakingBallWinsOrContests') or 0)
    kickout_tracked = int((evidence.get('gaelicStatEngine') or {}).get('estimatedKickoutsTracked') or 0)
    kickout_retained = int(evidence.get('kickoutRetained') or 0)
    kickout_lost = int(evidence.get('kickoutLost') or 0)
    top_zone = 'Unknown'
    try:
        top_zone = (evidence.get('fieldZoneSummary') or {}).get('topSequenceZones', [['Unknown', 0]])[0][0]
    except Exception:
        top_zone = 'Unknown'

    return {
        'score': {'value': facts.get('scoreline'), 'confidence': 'Confirmed'},
        'result': {'value': f"{facts.get('coachedTeam')} {facts.get('coachedTeamResult')} by {facts.get('margin')} point(s)", 'confidence': 'Confirmed'},
        'goalsFor': {'value': facts.get('coachedGoals'), 'confidence': 'Confirmed'},
        'goalsAgainst': {'value': facts.get('oppositionGoals'), 'confidence': 'Confirmed'},
        'pointsFor': {'value': facts.get('coachedPoints'), 'confidence': 'Confirmed'},
        'pointsAgainst': {'value': facts.get('oppositionPoints'), 'confidence': 'Confirmed'},
        'turnoversWon': {'value': turnovers_for if turnovers_for else 'Unknown', 'confidence': 'Estimated' if turnovers_for else 'Low confidence'},
        'turnoversLost': {'value': turnovers_against if turnovers_against else 'Unknown', 'confidence': 'Estimated' if turnovers_against else 'Low confidence'},
        'positiveTransitions': {'value': transition_positive if transition_positive else 'Unknown', 'confidence': 'Estimated' if transition_positive else 'Low confidence'},
        'negativeTransitions': {'value': transition_negative if transition_negative else 'Unknown', 'confidence': 'Estimated' if transition_negative else 'Low confidence'},
        'breakingBallContests': {'value': breaking_balls if breaking_balls else 'Unknown', 'confidence': 'Estimated' if breaking_balls else 'Low confidence'},
        'kickoutsIdentified': {'value': kickout_tracked if kickout_tracked else 'Unknown', 'confidence': 'Low confidence'},
        'kickoutsRetained': {'value': kickout_retained if kickout_retained else 'Unknown', 'confidence': 'Low confidence'},
        'kickoutsLost': {'value': kickout_lost if kickout_lost else 'Unknown', 'confidence': 'Low confidence'},
        'mainBattleZone': {'value': top_zone if top_zone != 'unknown' else 'Unknown', 'confidence': 'Estimated' if top_zone not in ['Unknown', 'unknown'] else 'Low confidence'},
        'scoreDetection': {'value': 'Not reliable from video yet; scoreline comes from user input', 'confidence': 'Low confidence'},
        'managerSummary': [
            'Confirmed scoreboard performance is strong.',
            'Estimated improvement focus is possession security and transition execution.',
            'Kickout outcome quality is not reliable yet; show identified kickout structures but avoid retention percentages until tracking improves.'
        ]
    }


def build_event_candidates_with_cv(url, metadata, profile, client=None, job_id=None, facts=None):
    uploaded = is_uploaded_storage_url(url)
    if uploaded:
        tactical_density_profile = {**(profile or {}),'name': 'uploaded-full-match-safe','scanIntervalSeconds': max(int((profile or {}).get('scanIntervalSeconds', 1)), 5),'maxScanSeconds': 5400,'candidateCount': 48,'classifiedEventCount': 10,'eventFramePack': 3,'minEventGapSeconds': 90,'clipCount': 0,'videoFormat': 'best[height<=360]/best'}
    else:
        tactical_density_profile = {**(profile or {}),'candidateCount': max(int((profile or {}).get('candidateCount', 42)), 80),'classifiedEventCount': max(int((profile or {}).get('classifiedEventCount', 26)), 20),'minEventGapSeconds': min(int((profile or {}).get('minEventGapSeconds', 60)), 45),'clipCount': max(int((profile or {}).get('clipCount', 8)), 8)}
    enriched_metadata = {**(metadata or {})}
    if int(enriched_metadata.get('duration') or 0) <= 0:
        enriched_metadata['duration'] = 4200
        enriched_metadata['durationSource'] = 'defaulted_70_minute_match_due_to_missing_metadata'
    log_step('event_candidates_start', {'duration': enriched_metadata.get('duration'), 'uploadedSafeMode': uploaded, 'profile': tactical_density_profile})
    events = ORIGINAL_BUILD_EVENT_CANDIDATES(url, enriched_metadata, tactical_density_profile, client, job_id, facts)
    log_step('event_candidates_complete', {'events': len(events or []), 'classified': len([e for e in (events or []) if isinstance(e, dict) and e.get('classification')])})
    return events


def aggregate_evidence_with_cv(events, facts, sequences=None, possession=None, zones=None, momentum=None):
    log_step('aggregate_evidence_start', {'events': len(events or []), 'sequences': len(sequences or [])})
    evidence = ORIGINAL_AGGREGATE_EVIDENCE(events, facts, sequences, possession, zones, momentum)
    evidence['gaelicStatEngine'] = estimate_gaelic_stats(events, evidence)
    evidence['managerStatSummary'] = build_manager_stat_summary(facts or {}, evidence)
    evidence['debugDensity'] = {'eventsReturnedToEvidence': len([event for event in events if isinstance(event, dict)]),'targetCandidateWindows': 48,'targetClassifiedWindows': 10,'targetGapSeconds': 90,'fallbackEvents': len([event for event in events if isinstance(event, dict) and event.get('fallbackMode')]),'downloadDebug': LAST_DOWNLOAD_DEBUG,'scanDebug': LAST_SCAN_DEBUG,'processLog': PROCESS_LOG[-40:],'note': 'Debug only. Do not show these engineering stats in the manager report.'}
    log_step('aggregate_evidence_complete', {'eventsAnalysed': evidence.get('eventsAnalysed'), 'fallbackEvents': evidence['debugDensity']['fallbackEvents']})
    return evidence


def build_report_prompt_with_cv(coached, opposition, facts, rules, metadata, events, timeline, sequences, possession_continuity, field_zones, momentum_phases, match_evidence, notes, profile):
    log_step('report_prompt_start', {'events': len(events or []), 'sequences': len(sequences or [])})
    manager_stats = match_evidence.get('managerStatSummary', {})
    base_prompt = ORIGINAL_BUILD_REPORT_PROMPT(coached, opposition, facts, rules, metadata, events, timeline, sequences, possession_continuity, field_zones, momentum_phases, match_evidence, notes, profile)
    log_step('report_prompt_complete', {'promptLength': len(base_prompt or '')})
    return base_prompt + f'''

CRITICAL MANAGER REPORT RULES:
- Do NOT mention engineering/debug metrics such as events analysed, classified windows, scan frames, candidate windows, prompt length, download size, or processing profile.
- Only show manager-facing Gaelic football stats.
- Never show a zero for a stat unless it is confirmed by scoreline or confidently measured. Use "Unknown" for low-confidence detection gaps.
- Confidence must be one of: Confirmed, Estimated, Low confidence.
- Put this section immediately after Match Snapshot: # {coached} – Manager Stats
- Use this exact manager-facing stats object as the source of truth: {manager_stats}

MANAGER STATS TABLE FORMAT:
| Stat | {coached} / Output | Confidence |
|---|---|---|
| Score | managerStatSummary.score.value | Confirmed |
| Result | managerStatSummary.result.value | Confirmed |
| Goals For | managerStatSummary.goalsFor.value | Confirmed |
| Goals Against | managerStatSummary.goalsAgainst.value | Confirmed |
| Points For | managerStatSummary.pointsFor.value | Confirmed |
| Points Against | managerStatSummary.pointsAgainst.value | Confirmed |
| Turnovers Won | managerStatSummary.turnoversWon.value | managerStatSummary.turnoversWon.confidence |
| Turnovers Lost | managerStatSummary.turnoversLost.value | managerStatSummary.turnoversLost.confidence |
| Positive Transitions | managerStatSummary.positiveTransitions.value | managerStatSummary.positiveTransitions.confidence |
| Negative Transitions | managerStatSummary.negativeTransitions.value | managerStatSummary.negativeTransitions.confidence |
| Breaking Ball Contests | managerStatSummary.breakingBallContests.value | managerStatSummary.breakingBallContests.confidence |
| Kickouts Identified | managerStatSummary.kickoutsIdentified.value | managerStatSummary.kickoutsIdentified.confidence |
| Kickouts Retained | managerStatSummary.kickoutsRetained.value | managerStatSummary.kickoutsRetained.confidence |
| Main Battle Zone | managerStatSummary.mainBattleZone.value | managerStatSummary.mainBattleZone.confidence |

REPORT TONE:
- The report is for a manager, not a developer.
- Stats first, then coaching meaning.
- Be honest when a number is low-confidence.
- Avoid saying "tracked" unless it is phrased as "identified from video".
'''


def generate_analysis_with_debug(request, job_id=None):
    global LATEST_DEBUG_REPORT_ID
    PROCESS_LOG.clear()
    log_step('analysis_start', {'jobId': job_id, 'url': getattr(request, 'url', '')})
    result = ORIGINAL_GENERATE_ANALYSIS(request, job_id)
    log_step('analysis_core_complete', {'status': result.get('status'), 'events': len(result.get('eventCandidates') or [])})
    report_id = getattr(request, 'reportId', None) or str(uuid.uuid4())
    result['reportId'] = report_id
    debug_payload = {'reportId': report_id,'status': result.get('status'),'processingProfile': result.get('processingProfile'),'videoIngestionStatus': VIDEO_INGESTION_STATUS,'videoMetadata': result.get('videoMetadata'),'videoMetadataDebug': (result.get('videoMetadata') or {}).get('debug'),'downloadDebug': LAST_DOWNLOAD_DEBUG,'scanDebug': LAST_SCAN_DEBUG,'processLog': PROCESS_LOG[-80:],'matchFacts': result.get('matchFacts'),'matchEvidence': result.get('matchEvidence'),'managerStatSummary': (result.get('matchEvidence') or {}).get('managerStatSummary'),'eventCandidateCount': len(result.get('eventCandidates') or []),'classificationCount': len(result.get('eventClassifications') or []),'sequenceCount': len(result.get('tacticalSequences') or []),'clipCount': len(result.get('clips') or []),'scoringCueCount': len(result.get('scoringCues') or []),'kickoutEventCount': len(result.get('kickoutEvents') or []),'turnoverEventCount': len(result.get('turnoverEvents') or []),'transitionEventCount': len(result.get('transitionEvents') or []),'firstEvents': (result.get('eventCandidates') or [])[:12],'gaelicStatEngine': (result.get('matchEvidence') or {}).get('gaelicStatEngine'),'debugDensity': (result.get('matchEvidence') or {}).get('debugDensity')}
    DEBUG_REPORTS[report_id] = debug_payload
    LATEST_DEBUG_REPORT_ID = report_id
    result['debugReportUrl'] = f'/debug-report/{report_id}'
    result['latestDebugReportUrl'] = '/debug-report/latest'
    result['debug'] = debug_payload
    log_step('analysis_debug_stored', {'reportId': report_id})
    return result


if robust_extract_video_metadata:
    main.extract_video_metadata = robust_extract_video_metadata
if robust_download_match_video:
    main.download_match_video = download_match_video_with_debug
main.scan_video_frame_differences = scan_video_frame_differences_with_debug
main.fallback_event_candidates = dense_fallback_event_candidates
main.build_event_candidates = build_event_candidates_with_cv
main.aggregate_evidence = aggregate_evidence_with_cv
main.build_report_prompt = build_report_prompt_with_cv
main.generate_analysis = generate_analysis_with_debug