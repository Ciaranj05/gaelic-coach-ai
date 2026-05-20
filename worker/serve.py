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


def build_event_candidates_with_cv(url, metadata, profile, client=None, job_id=None, facts=None):
    # Keep the original non-CV path when the OpenAI client is not present.
    if not client:
        return ORIGINAL_BUILD_EVENT_CANDIDATES(url, metadata, profile, client, job_id, facts)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            main.set_job_stage(job_id, 'download', 'Downloading match video for full-match scan')
            video_path = main.download_match_video(url, tmpdir, profile)
            if not video_path:
                return main.fallback_event_candidates(metadata)

            main.set_job_stage(job_id, 'full_match_scan', 'Extracting low-res scan frames and comparing movement changes')
            differences = main.scan_video_frame_differences(video_path, profile)

            main.set_job_stage(job_id, 'event_selection', 'Selecting dense tactical review windows')
            candidates = main.select_event_candidates_from_differences(
                differences,
                int(profile.get('candidateCount', 36)),
                int(profile.get('minEventGapSeconds', 60))
            ) or main.fallback_event_candidates(metadata)

            main.set_job_stage(job_id, 'event_analysis', 'Classifying windows and adding YOLO player/shape cues')
            enriched = []
            classified_count = int(profile.get('classifiedEventCount', 24))
            clip_count = int(profile.get('clipCount', 8))
            first_frames = []
            facts = facts or main.build_match_facts({})
            cached_colours = None

            for index, event in enumerate(candidates[:classified_count], start=1):
                frames = main.extract_event_frames(video_path, event, tmpdir, index, profile)
                if frames and len(first_frames) < 10:
                    first_frames += frames[:2]

                if not cached_colours or cached_colours.get('confidence') == 'low':
                    cached_colours = main.detect_team_colours(client, first_frames or frames, facts)

                scoreboard_ocr = main.read_scoreboard_ocr(
                    client,
                    main.extract_scoreboard_crops(video_path, event, tmpdir, index)
                )
                classification = main.classify_event_frames(client, frames, event, scoreboard_ocr, cached_colours, facts)

                if not classification.get('keepForReport') and classification.get('coachingValue') == 'low':
                    continue

                event_type = classification.get('eventType', event.get('type'))
                clip = main.extract_event_clip(video_path, {**event, 'type': event_type}, job_id, index) if index <= clip_count else None
                cv_result = run_cv_on_event(video_path, event.get('startSecond', 0), event.get('endSecond', event.get('startSecond', 0) + 30))
                cv_note = cv_summary_sentence(cv_result)

                visual_summary = classification.get('visualSummary', '')
                if cv_note:
                    visual_summary = f'{visual_summary} {cv_note}'.strip()

                enriched.append({
                    **event,
                    'type': event_type,
                    'classification': classification,
                    'visualAnalysis': visual_summary,
                    'scoreboard': classification.get('scoreboard'),
                    'scoreOutcome': classification.get('scoreOutcome'),
                    'teamColours': classification.get('teamColours'),
                    'matchIntelligence': classification.get('matchIntelligence'),
                    'possessionColour': classification.get('possessionColour'),
                    'likelyTeamInPossession': classification.get('likelyTeamInPossession'),
                    'framesAnalysed': len(frames),
                    'clip': clip,
                    'cvPlayerDetection': cv_result,
                    'cvShapeCue': cv_shape_label(cv_result),
                    'cvSummary': cv_note,
                })

            return enriched + candidates[classified_count:]
    except Exception:
        return main.fallback_event_candidates(metadata)


def aggregate_evidence_with_cv(events, facts, sequences=None, possession=None, zones=None, momentum=None):
    evidence = ORIGINAL_AGGREGATE_EVIDENCE(events, facts, sequences, possession, zones, momentum)
    cv_enabled_events = []
    total_players = 0
    shape_votes = {}
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
        for key in ['width', 'compactness', 'overloadCue']:
            value = shape.get(key, 'unknown')
            if value and value != 'unknown':
                shape_votes[value] = shape_votes.get(value, 0) + 1

        for colour, count in (cv_result.get('teamColourCounts') or {}).items():
            colour_counts[colour] = colour_counts.get(colour, 0) + int(count)

    def top_vote(values):
        return max(values, key=values.get) if values else 'unknown'

    evidence['cvEnabledEvents'] = len(cv_enabled_events)
    evidence['cvPlayersDetected'] = total_players
    evidence['cvTopShapeCue'] = top_vote(shape_votes)
    evidence['cvTeamColourCounts'] = dict(sorted(colour_counts.items(), key=lambda item: item[1], reverse=True))

    if cv_enabled_events:
        evidence['evidenceBullets'].append(
            f"YOLO CV added player/shape evidence on {len(cv_enabled_events)} event window(s), detecting {total_players} player instances."
        )

    return evidence


def build_report_prompt_with_cv(coached, opposition, facts, rules, metadata, events, timeline, sequences, possession_continuity, field_zones, momentum_phases, match_evidence, notes, profile):
    cv_events = [
        {
            'time': event.get('time'),
            'type': event.get('type'),
            'cvShapeCue': event.get('cvShapeCue'),
            'cvSummary': event.get('cvSummary'),
        }
        for event in events
        if isinstance(event, dict) and event.get('cvSummary')
    ][:10]

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

YOLO CV PLAYER/SHAPE EVIDENCE: {cv_events}
YOLO CV AGGREGATE COUNTERS: {{'cvEnabledEvents': {match_evidence.get('cvEnabledEvents', 0)}, 'cvPlayersDetected': {match_evidence.get('cvPlayersDetected', 0)}, 'cvTopShapeCue': '{match_evidence.get('cvTopShapeCue', 'unknown')}', 'cvTeamColourCounts': {match_evidence.get('cvTeamColourCounts', {})}}}
Additional CV rules:
- If YOLO CV evidence is enabled, use it to support shape language: compact, stretched, wide, narrow, central overload, left-channel overload, right-channel overload.
- Do not say YOLO proves possession or score outcomes. Use it only for player counts, team-colour grouping, width, compactness and overload cues.
- Prefer phrases such as "CV shape cue suggests" or "player-detection evidence showed" rather than absolute claims.
- Add one CV-informed observation where useful in Evidence Summary, Tactical Sequences or Estimated Key Match Stats.
'''


main.build_event_candidates = build_event_candidates_with_cv
main.aggregate_evidence = aggregate_evidence_with_cv
main.build_report_prompt = build_report_prompt_with_cv
