import tempfile

import main
from main import app

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


@app.get('/cv-status')
def get_cv_status():
    return cv_status()


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

    return ORIGINAL_BUILD_EVENT_CANDIDATES(
        url,
        metadata,
        tactical_density_profile,
        client,
        job_id,
        facts,
    )


def aggregate_evidence_with_cv(events, facts, sequences=None, possession=None, zones=None, momentum=None):
    evidence = ORIGINAL_AGGREGATE_EVIDENCE(events, facts, sequences, possession, zones, momentum)
    evidence['gaelicStatEngine'] = estimate_gaelic_stats(events, evidence)
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


main.build_event_candidates = build_event_candidates_with_cv
main.aggregate_evidence = aggregate_evidence_with_cv
main.build_report_prompt = build_report_prompt_with_cv
