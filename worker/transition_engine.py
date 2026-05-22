from __future__ import annotations

from typing import Any, Dict, List


POSITIVE_EVENTS = {
    'scoring_chance',
    'fast_transition',
    'attack_overlap',
    'line_break',
    'inside_run'
}

NEGATIVE_EVENTS = {
    'turnover',
    'turned_over',
    'slow_possession',
    'blocked_attack',
    'forced_reset'
}

NEUTRAL_EVENTS = {
    'defensive_setup',
    'game_management',
    'kickout_restart'
}


def classify_transition_outcome(chain: Dict[str, Any]) -> Dict[str, Any]:
    types = [str(t or '').lower() for t in chain.get('types', [])]

    positive_hits = sum(1 for t in types if t in POSITIVE_EVENTS)
    negative_hits = sum(1 for t in types if t in NEGATIVE_EVENTS)
    neutral_hits = sum(1 for t in types if t in NEUTRAL_EVENTS)

    duration = int(chain.get('durationSeconds') or 0)
    event_count = int(chain.get('eventCount') or 0)

    if positive_hits >= 2:
        outcome = 'successful_transition'
        coaching = 'Transition created attacking momentum.'
    elif negative_hits >= 2:
        outcome = 'failed_transition'
        coaching = 'Transition broke down under pressure.'
    elif duration >= 45 and event_count >= 3:
        outcome = 'controlled_possession_phase'
        coaching = 'Team sustained possession and controlled tempo.'
    elif neutral_hits >= 2:
        outcome = 'structured_reset'
        coaching = 'Play recycled into a structured shape.'
    else:
        outcome = 'neutral_transition'
        coaching = 'No strong tactical outcome inferred.'

    confidence = 'medium'
    if event_count <= 1:
        confidence = 'low'
    if positive_hits >= 3 or negative_hits >= 3:
        confidence = 'high'

    return {
        'owner': chain.get('owner'),
        'time': chain.get('time'),
        'durationSeconds': duration,
        'eventCount': event_count,
        'outcome': outcome,
        'positiveSignals': positive_hits,
        'negativeSignals': negative_hits,
        'neutralSignals': neutral_hits,
        'confidence': confidence,
        'coachingInterpretation': coaching,
    }


def analyse_transition_patterns(chains: List[Dict[str, Any]]) -> Dict[str, Any]:
    outcomes = [classify_transition_outcome(chain) for chain in chains]

    successful = [o for o in outcomes if o['outcome'] == 'successful_transition']
    failed = [o for o in outcomes if o['outcome'] == 'failed_transition']
    controlled = [o for o in outcomes if o['outcome'] == 'controlled_possession_phase']
    resets = [o for o in outcomes if o['outcome'] == 'structured_reset']

    return {
        'successfulTransitions': len(successful),
        'failedTransitions': len(failed),
        'controlledPossessionPhases': len(controlled),
        'structuredResets': len(resets),
        'transitionOutcomes': outcomes[:25],
        'mainCoachingTheme': determine_theme(successful, failed, controlled),
        'confidence': 'medium' if len(outcomes) >= 6 else 'low'
    }


def determine_theme(successful: List[Dict[str, Any]], failed: List[Dict[str, Any]], controlled: List[Dict[str, Any]]) -> str:
    if len(successful) > len(failed) + 2:
        return 'Strong transition execution and attacking flow.'
    if len(failed) > len(successful):
        return 'Transition play frequently broke down under pressure.'
    if len(controlled) >= 3:
        return 'Sustained possession used to manage tempo.'
    return 'Mixed transition outcomes across the match.'
