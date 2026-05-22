from __future__ import annotations

from typing import Any, Dict, List


HIGH_VALUE_TYPES = {
    'turnover',
    'turned_over',
    'fast_transition',
    'scoring_chance',
    'kickout_restart',
    'breaking_ball',
}


OUTCOME_PRIORITY = {
    'failed_transition': 3,
    'successful_transition': 3,
    'retained': 2,
    'lost': 2,
    'controlled_possession_phase': 1,
    'structured_reset': 1,
}


def confidence_score(confidence: str) -> int:
    confidence = str(confidence or '').lower()
    if confidence == 'high':
        return 3
    if confidence == 'medium' or confidence == 'estimated':
        return 2
    return 1



def build_clip(event: Dict[str, Any], reason: str, category: str, score: int) -> Dict[str, Any]:
    start_second = max(0, int(event.get('startSecond') or 0) - 8)
    end_second = int(event.get('endSecond') or start_second + 25) + 8

    return {
        'category': category,
        'time': event.get('time'),
        'startSecond': start_second,
        'endSecond': end_second,
        'eventType': event.get('type'),
        'reason': reason,
        'score': score,
        'confidence': event.get('confidence', 'low'),
        'clipLabel': f"{category.replace('_', ' ').title()} – {event.get('time', 'Unknown')}",
    }



def surface_priority_clips(events: List[Dict[str, Any]], transitions: Dict[str, Any], kickouts: Dict[str, Any]) -> Dict[str, Any]:
    surfaced = []

    for event in events:
        if not isinstance(event, dict):
            continue

        event_type = str(event.get('type') or '').lower()
        if event_type not in HIGH_VALUE_TYPES:
            continue

        score = confidence_score(event.get('confidence'))

        if event_type in {'turnover', 'turned_over'}:
            surfaced.append(build_clip(event, 'Potential turnover moment worth review.', 'turnover_review', score + 2))

        elif event_type == 'fast_transition':
            surfaced.append(build_clip(event, 'Transition sequence identified.', 'transition_review', score + 2))

        elif event_type == 'scoring_chance':
            surfaced.append(build_clip(event, 'Potential scoring opportunity detected.', 'scoring_review', score + 3))

        elif event_type == 'kickout_restart':
            surfaced.append(build_clip(event, 'Kickout/restart structure identified.', 'kickout_review', score + 1))

        elif event_type == 'breaking_ball':
            surfaced.append(build_clip(event, 'Breaking-ball contest identified.', 'breaking_ball_review', score + 1))

    for transition in (transitions or {}).get('transitionOutcomes', []):
        outcome = transition.get('outcome')
        if outcome not in OUTCOME_PRIORITY:
            continue

        surfaced.append({
            'category': 'transition_outcome',
            'time': transition.get('time'),
            'eventType': outcome,
            'reason': transition.get('coachingInterpretation'),
            'score': OUTCOME_PRIORITY[outcome] + confidence_score(transition.get('confidence')),
            'confidence': transition.get('confidence'),
            'clipLabel': f"Transition Outcome – {transition.get('time', 'Unknown')}"
        })

    for kickout in (kickouts or {}).get('kickoutOutcomes', []):
        outcome = kickout.get('outcome')
        surfaced.append({
            'category': 'kickout_outcome',
            'time': kickout.get('time'),
            'eventType': outcome,
            'reason': kickout.get('coachingInterpretation'),
            'score': 2 + confidence_score(kickout.get('confidence')),
            'confidence': kickout.get('confidence'),
            'clipLabel': f"Kickout Review – {kickout.get('time', 'Unknown')}"
        })

    surfaced = sorted(surfaced, key=lambda item: item.get('score', 0), reverse=True)

    return {
        'priorityClips': surfaced[:20],
        'highPriorityCount': len([c for c in surfaced if c.get('score', 0) >= 5]),
        'surfacedClipCount': len(surfaced),
        'topThemes': summarise_clip_themes(surfaced[:10]),
    }



def summarise_clip_themes(clips: List[Dict[str, Any]]) -> List[str]:
    themes = []

    categories = [clip.get('category') for clip in clips]

    if categories.count('turnover_review') >= 2:
        themes.append('Multiple turnover review moments surfaced.')

    if categories.count('transition_review') >= 2:
        themes.append('Transition sequences repeatedly identified.')

    if categories.count('kickout_review') >= 2:
        themes.append('Kickout structure repeatedly surfaced.')

    if categories.count('scoring_review') >= 2:
        themes.append('Repeated scoring opportunities surfaced.')

    return themes[:5]
