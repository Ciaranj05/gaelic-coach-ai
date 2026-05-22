import tempfile
import uuid

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
    LAST_DOWNLOAD_DEBUG = {
        'attempted': True,
        'ok': False,
        'error': '',
        'path': '',
        'tmpdir': tmpdir,
        'profileFormat': (profile or {}).get('videoFormat'),
    }

    if not robust_download_match_video:
        LAST_DOWNLOAD_DEBUG['error'] = 'robust_download_match_video unavailable'
        return None

    try:
        path = robust_download_match_video(url, tmpdir, profile or {})
        LAST_DOWNLOAD_DEBUG['path'] = path or ''
        LAST_DOWNLOAD_DEBUG['ok'] = bool(path)

        try:
            import os
            import json
            debug_path = os.path.join(tmpdir, 'download_debug.json')
            if os.path.exists(debug_path):
                with open(debug_path, 'r', encoding='utf-8') as handle:
                    LAST_DOWNLOAD_DEBUG.update(json.load(handle))
        except Exception as exc:
            LAST_DOWNLOAD_DEBUG['debugReadError'] = str(exc)[:500]

        return path
    except Exception as exc:
        LAST_DOWNLOAD_DEBUG['error'] = str(exc)[:1000]
        return None


def scan_video_frame_differences_with_debug(video_path, profile, max_scan_seconds=7200):
    global LAST_SCAN_DEBUG
    LAST_SCAN_DEBUG = {
        'attempted': True,
        'ok': False,
        'error': '',
        'videoPath': video_path or '',
        'scanIntervalSeconds': (profile or {}).get('scanIntervalSeconds'),
        'differenceCount': 0,
    }
    try:
        differences = ORIGINAL_SCAN_VIDEO_FRAME_DIFFERENCES(video_path, profile, max_scan_seconds)
        LAST_SCAN_DEBUG['differenceCount'] = len(differences or [])
        LAST_SCAN_DEBUG['ok'] = bool(differences)
        return differences
    except Exception as exc:
        LAST_SCAN_DEBUG['error'] = str(exc)[:1000]
        return []


def dense_fallback_event_candidates(metadata):
    duration = int((metadata or {}).get('duration') or 0)
    if duration <= 0:
        duration = 4200

    count = 160
    gap = max(12, duration // count)
    labels = [
        'kickout_restart',
        'slow_possession',
        'fast_transition',
        'scoring_chance',
        'breaking_ball',
        'defensive_setup',
        'turnover',
        'game_management'
    ]

    events = []
    second = 60
    index = 0
    while second < duration - 60 and len(events) < count:
        event_type = labels[index % len(labels)]
        events.append({
            'time': f'{main.format_timestamp(second)} approx',
            'startSecond': max(0, second - 12),
            'endSecond': second + 18,
            'type': event_type,
            'reason': 'Dense fallback tactical checkpoint selected because video metadata/download scanning was unavailable.',
            'confidence': 'low',
            'scoreOutcome': main.norm_score_outcome({}),
            'matchIntelligence': main.norm_match_intel({}),
            'fallbackMode': 'dense_duration_fallback',
        })
        second += gap
        index += 1

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
    possession_share = {
        colour: f"{int((count / max(1, total)) * 100)}%"
        for colour, count in possessions.items()
    }

    return {
        'dominantPossessionColours': possession_share,
        'estimatedTurnoversFromContinuity': turnovers,
        'estimatedKickoutRetentions': retained_kickouts,
        'estimatedKickoutsTracked': kickout_estimates,
        'confidence': 'medium' if total >= 6 else 'low'
    }


def estimate_gaelic_stats(events, match_evidence):
    tracker = track_possession_and_turnovers(events)

    return {
        'estimatedTurnoversFromContinuity': tracker.get('estimatedTurnoversFromContinuity', 0),
        'estimatedKickoutRetentions': tracker.get('estimatedKickoutRetentions', 0),
        'estimatedKickoutsTracked': tracker.get('estimatedKickoutsTracked', 0),
        'dominantPossessionColours': tracker.get('dominantPossessionColours', {}),
        'trackerConfidence': tracker.get('confidence', 'low'),
        'cvWidthCue': match_evidence.get('cvWidthCue', 'unknown'),
        'cvCompactnessCue': match_evidence.get('cvCompactnessCue', 'unknown'),
        'cvOverloadCue': match_evidence.get('cvOverloadCue', 'unknown'),
    }


def build_event_candidates_with_cv(url, metadata, profile, client=None, job_id=None, facts=None):
    tactical_density_profile = {
        **(profile or {}),
        'candidateCount': max(int((profile or {}).get('candidateCount', 42)), 160),
        'classifiedEventCount': max(int((profile or {}).get('classifiedEventCount', 26)), 80),
        'minEventGapSeconds': min(int((profile or {}).get('minEventGapSeconds', 60)), 12),
        'clipCount': max(int((profile or {}).get('clipCount', 8)), 20),
    }

    enriched_metadata = {**(metadata or {})}
    if int(enriched_metadata.get('duration') or 0) <= 0:
        enriched_metadata['duration'] = 4200
        enriched_metadata['durationSource'] = 'defaulted_70_minute_match_due_to_missing_metadata'

    return ORIGINAL_BUILD_EVENT_CANDIDATES(
        url,
        enriched_metadata,
        tactical_density_profile,
        client,
        job_id,
        facts,
    )


def aggregate_evidence_with_cv(events, facts, sequences=None, possession=None, zones=None, momentum=None):
    evidence = ORIGINAL_AGGREGATE_EVIDENCE(events, facts, sequences, possession, zones, momentum)
    evidence['gaelicStatEngine'] = estimate_gaelic_stats(events, evidence)
    evidence['debugDensity'] = {
        'eventsReturnedToEvidence': len([event for event in events if isinstance(event, dict)]),
        'targetCandidateWindows': 160,
        'targetClassifiedWindows': 80,
        'targetGapSeconds': 12,
        'fallbackEvents': len([event for event in events if isinstance(event, dict) and event.get('fallbackMode')]),
        'downloadDebug': LAST_DOWNLOAD_DEBUG,
        'scanDebug': LAST_SCAN_DEBUG,
        'note': 'If fallbackEvents is high, check downloadDebug and scanDebug to see whether video download or ffmpeg frame scanning failed.'
    }
    return evidence


def build_report_prompt_with_cv(coached, opposition, facts, rules, metadata, events, timeline, sequences, possession_continuity, field_zones, momentum_phases, match_evidence, notes, profile):
    stat_engine = match_evidence.get('gaelicStatEngine', {})

    base_prompt = ORIGINAL_BUILD_REPORT_PROMPT(
        coached,
        opposition,
        facts,
        rules,
        metadata,
        events,
        timeline,
        sequences,
        possession_continuity,
        field_zones,
        momentum_phases,
        match_evidence,
        notes,
        profile,
    )

    return base_prompt + f'''

MANAGER MATCH STATS PRIORITY ORDER:
1. Score efficiency
2. Kickout battle
3. Turnovers
4. Possession / territory
5. Transition attacks
6. Defensive compactness
7. Breaking ball
8. Shape / overloads

MANAGER MATCH STATS SECTION RULES:
- Always include a section titled: # {coached} – Manager Match Stats
- Present stats in a fixed table ordered by coaching importance.
- Use Confirmed / Estimated / Low confidence labels.
- Keep stats concise and readable.
- Avoid generic commentary in this section.
- Prefer statistics and evidence cues over narrative.

Required table format:
| Manager Stat | Output | Confidence |
|---|---|---|
| Score Efficiency | goals/points/score margin summary | Confirmed |
| Kickout Battle | estimated kickouts tracked + retention | trackerConfidence |
| Turnovers | estimated turnovers from continuity | trackerConfidence |
| Possession / Territory | dominant possession colours | trackerConfidence |
| Transition Attacks | transition observations if available | Estimated |
| Defensive Compactness | cvCompactnessCue | Estimated |
| Breaking Ball | breaking-ball observations if available | Estimated |
| Shape / Overloads | cvWidthCue + cvOverloadCue | Estimated |

POSSESSION & TURNOVER TRACKER V1: {stat_engine}
Additional tracker rules:
- Use YOLO continuity estimates for likely possession control and turnover shifts.
- Add concise stats for estimated turnovers, possession colour continuity and kickout retention.
- Phrase carefully: estimated control, likely turnover, continuity suggests.
'''


def generate_analysis_with_debug(request, job_id=None):
    global LATEST_DEBUG_REPORT_ID
    result = ORIGINAL_GENERATE_ANALYSIS(request, job_id)
    report_id = getattr(request, 'reportId', None) or str(uuid.uuid4())
    result['reportId'] = report_id
    debug_payload = {
        'reportId': report_id,
        'status': result.get('status'),
        'processingProfile': result.get('processingProfile'),
        'videoIngestionStatus': VIDEO_INGESTION_STATUS,
        'videoMetadata': result.get('videoMetadata'),
        'videoMetadataDebug': (result.get('videoMetadata') or {}).get('debug'),
        'downloadDebug': LAST_DOWNLOAD_DEBUG,
        'scanDebug': LAST_SCAN_DEBUG,
        'matchFacts': result.get('matchFacts'),
        'matchEvidence': result.get('matchEvidence'),
        'eventCandidateCount': len(result.get('eventCandidates') or []),
        'classificationCount': len(result.get('eventClassifications') or []),
        'sequenceCount': len(result.get('tacticalSequences') or []),
        'clipCount': len(result.get('clips') or []),
        'scoringCueCount': len(result.get('scoringCues') or []),
        'kickoutEventCount': len(result.get('kickoutEvents') or []),
        'turnoverEventCount': len(result.get('turnoverEvents') or []),
        'transitionEventCount': len(result.get('transitionEvents') or []),
        'firstEvents': (result.get('eventCandidates') or [])[:12],
        'gaelicStatEngine': (result.get('matchEvidence') or {}).get('gaelicStatEngine'),
        'debugDensity': (result.get('matchEvidence') or {}).get('debugDensity'),
    }
    DEBUG_REPORTS[report_id] = debug_payload
    LATEST_DEBUG_REPORT_ID = report_id
    result['debugReportUrl'] = f'/debug-report/{report_id}'
    result['latestDebugReportUrl'] = '/debug-report/latest'
    result['debug'] = debug_payload
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