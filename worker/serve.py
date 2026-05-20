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


def cv_summary_sentence(cv_result):
    if not isinstance(cv_result, dict) or not cv_result.get('enabled'):
        return ''

    players = cv_result.get('playersDetected', 0)
    shape = cv_result.get('shape') or {}
    colours = cv_result.get('teamColourCounts') or {}

    top_colours = ', '.join([f'{colour}: {count}' for colour, count in list(colours.items())[:3]]) or 'colour grouping unclear'
    width = shape.get('width', 'unknown')
    compactness = shape.get('compactness', 'unknown')
    overload = shape.get('overloadCue', 'unknown')

    return f'CV detected {players} player instances; colour groups: {top_colours}; width: {width}; compactness: {compactness}; overload cue: {overload}.'


def cv_shape_label(cv_result):
    if not isinstance(cv_result, dict) or not cv_result.get('enabled'):
        return 'unknown'
    shape = cv_result.get('shape') or {}
    return f"{shape.get('width', 'unknown')} / {shape.get('compactness', 'unknown')} / {shape.get('overloadCue', 'unknown')}"


def estimate_gaelic_stats(events, match_evidence):
    score_events = 0
    goal_events = 0
    point_events = 0
    wide_events = 0
    kickout_events = 0
    retained_kickouts = 0
    turnovers_for = 0
    turnovers_against = 0
    transitions = 0
    breaking_balls = 0
    possession_votes = {}

    for event in events:
        if not isinstance(event, dict):
            continue

        classification = event.get('classification') or {}
        score_outcome = classification.get('scoreOutcome') or event.get('scoreOutcome')
        kickout = classification.get('kickoutOutcome')
        possession = event.get('likelyTeamInPossession') or classification.get('likelyTeamInPossession')
        event_type = event.get('type')
        transition = classification.get('transitionOutcome')
        possession_outcome = classification.get('possessionOutcome')

        if possession:
            possession_votes[possession] = possession_votes.get(possession, 0) + 1

        if score_outcome == 'goal':
            goal_events += 1
            score_events += 1
        elif score_outcome == 'point':
            point_events += 1
            score_events += 1
        elif score_outcome == 'wide':
            wide_events += 1

        if event_type == 'kickout_restart':
            kickout_events += 1
            if kickout in ['short_retained', 'won_clean', 'won_breaking_ball']:
                retained_kickouts += 1

        if possession_outcome == 'turnover_for':
            turnovers_for += 1
        elif possession_outcome == 'turnover_against':
            turnovers_against += 1

        if transition in ['created_score', 'created_chance', 'carried_to_scoring_zone']:
            transitions += 1

        if event_type == 'breaking_ball':
            breaking_balls += 1

    total_possession_votes = sum(possession_votes.values())
    top_possession = max(possession_votes, key=possession_votes.get) if possession_votes else 'unknown'
    top_share = int((possession_votes.get(top_possession, 0) / max(1, total_possession_votes)) * 100) if possession_votes else 0

    confidence = 'high' if len(events) >= 10 else 'medium' if len(events) >= 5 else 'low'

    return {
        'estimatedScoresDetected': score_events,
        'estimatedGoalsDetected': goal_events,
        'estimatedPointsDetected': point_events,
        'estimatedWidesDetected': wide_events,
        'estimatedKickoutsTracked': kickout_events,
        'estimatedKickoutRetention': f'{int((retained_kickouts / max(1, kickout_events)) * 100)}%' if kickout_events else 'insufficient evidence',
        'estimatedTurnoversWon': turnovers_for,
        'estimatedTurnoversLost': turnovers_against,
        'estimatedPositiveTransitions': transitions,
        'estimatedBreakingBallEvents': breaking_balls,
        'estimatedPossessionLeader': top_possession,
        'estimatedPossessionShare': f'{top_share}% estimated event control' if top_possession != 'unknown' else 'unclear',
        'confidence': confidence,
        'cvEnabledEvents': match_evidence.get('cvEnabledEvents', 0),
        'cvWidthCue': match_evidence.get('cvWidthCue', 'unknown'),
        'cvCompactnessCue': match_evidence.get('cvCompactnessCue', 'unknown'),
        'cvOverloadCue': match_evidence.get('cvOverloadCue', 'unknown'),
    }


def build_event_candidates_with_cv(url, metadata, profile, client=None, job_id=None, facts=None):
    return ORIGINAL_BUILD_EVENT_CANDIDATES(url, metadata, profile, client, job_id, facts)


def aggregate_evidence_with_cv(events, facts, sequences=None, possession=None, zones=None, momentum=None):
    evidence = ORIGINAL_AGGREGATE_EVIDENCE(events, facts, sequences, possession, zones, momentum)
    cv_enabled_events = []
    total_players = 0
    width_votes = {}
    compactness_votes = {}
    overload_votes = {}
    colour_counts = {}

    for event in events:
        if not isinstance(event, dict):
            continue
        cv_result = event.get('cvPlayerDetection') or {}
        if not cv_result.get('enabled'):
            continue
        cv_enabled_events.append(event)
        total_players += int(cv_result.get('playersDetected') or 0)

        shape = cv_result.get('shape') or {}
        width = shape.get('width', 'unknown')
        compactness = shape.get('compactness', 'unknown')
        overload = shape.get('overloadCue', 'unknown')
        if width and width != 'unknown':
            width_votes[width] = width_votes.get(width, 0) + 1
        if compactness and compactness != 'unknown':
            compactness_votes[compactness] = compactness_votes.get(compactness, 0) + 1
        if overload and overload != 'unknown':
            overload_votes[overload] = overload_votes.get(overload, 0) + 1

        for colour, count in (cv_result.get('teamColourCounts') or {}).items():
            colour_counts[colour] = colour_counts.get(colour, 0) + int(count)

    def top_vote(values):
        return max(values, key=values.get) if values else 'unknown'

    evidence['cvEnabledEvents'] = len(cv_enabled_events)
    evidence['cvPlayersDetected'] = total_players
    evidence['cvWidthCue'] = top_vote(width_votes)
    evidence['cvCompactnessCue'] = top_vote(compactness_votes)
    evidence['cvOverloadCue'] = top_vote(overload_votes)
    evidence['cvTeamColourCounts'] = dict(sorted(colour_counts.items(), key=lambda item: item[1], reverse=True))
    evidence['gaelicStatEngine'] = estimate_gaelic_stats(events, evidence)

    if cv_enabled_events:
        evidence['evidenceBullets'].append(
            f"YOLO CV added player/shape evidence on {len(cv_enabled_events)} event window(s), detecting {total_players} player instances."
        )

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

GAELIC STAT ENGINE V1: {stat_engine}
Additional reporting rules:
- Add this exact section after Evidence Summary if Gaelic Stat Engine data exists:
# {coached} – Estimated Gaelic Match Stats
| Gaelic Stat | Estimated Output | Confidence |
|---|---|---|
| Scores Detected | estimatedScoresDetected | confidence |
| Goals Detected | estimatedGoalsDetected | confidence |
| Points Detected | estimatedPointsDetected | confidence |
| Wides Detected | estimatedWidesDetected | confidence |
| Kickouts Tracked | estimatedKickoutsTracked | confidence |
| Kickout Retention | estimatedKickoutRetention | confidence |
| Turnovers Won | estimatedTurnoversWon | confidence |
| Turnovers Lost | estimatedTurnoversLost | confidence |
| Positive Transitions | estimatedPositiveTransitions | confidence |
| Breaking Ball Events | estimatedBreakingBallEvents | confidence |
| Estimated Possession Leader | estimatedPossessionLeader + estimatedPossessionShare | confidence |
| Width Cue | cvWidthCue | confidence |
| Compactness Cue | cvCompactnessCue | confidence |
| Overload Channel Cue | cvOverloadCue | confidence |
- Clearly label all outputs as estimated unless confirmed by scoreboard OCR or manual match context.
- Omit rows where evidence is too weak.
- Prefer concise statistical presentation over generic tactical commentary.
'''


main.build_event_candidates = build_event_candidates_with_cv
main.aggregate_evidence = aggregate_evidence_with_cv
main.build_report_prompt = build_report_prompt_with_cv
