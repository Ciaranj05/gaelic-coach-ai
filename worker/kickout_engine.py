from __future__ import annotations

from typing import Any, Dict, List, Optional


KICKOUT_EVENT_TYPES = {
    'kickout_restart',
    'restart',
    'goalkeeper_restart',
    'score_or_restart_after_score'
}


def normalise_owner(owner: Any) -> str:
    value = str(owner or '').strip()
    return value if value else 'unknown'


def is_kickout_chain(chain: Dict[str, Any]) -> bool:
    types = {str(t or '').lower() for t in chain.get('types', [])}
    if types.intersection(KICKOUT_EVENT_TYPES):
        return True

    for event in chain.get('events', []):
        event_type = str(event.get('eventType') or '').lower()
        if event_type in KICKOUT_EVENT_TYPES:
            return True

    return False


def nearest_next_chain(chains: List[Dict[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    if index + 1 < len(chains):
        return chains[index + 1]
    return None


def classify_kickout_outcome(kickout_chain: Dict[str, Any], next_chain: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    taking_team = normalise_owner(kickout_chain.get('owner'))
    next_owner = normalise_owner((next_chain or {}).get('owner'))

    if taking_team == 'unknown' and next_owner == 'unknown':
        outcome = 'unknown'
        confidence = 'low'
        coaching = 'Kickout shape identified but ownership could not be inferred.'
    elif taking_team != 'unknown' and next_owner == taking_team:
        outcome = 'retained'
        confidence = 'estimated'
        coaching = 'Kickout appears to be retained into the next possession phase.'
    elif taking_team != 'unknown' and next_owner != 'unknown' and next_owner != taking_team:
        outcome = 'lost'
        confidence = 'estimated'
        coaching = 'Kickout appears to be lost or turned over after the restart.'
    elif taking_team == 'unknown' and next_owner != 'unknown':
        outcome = 'contested_or_unclear'
        confidence = 'low'
        coaching = f'First possession after the restart appears to favour {next_owner}, but taking team is unclear.'
    else:
        outcome = 'unknown'
        confidence = 'low'
        coaching = 'Kickout outcome could not be inferred.'

    return {
        'time': kickout_chain.get('time'),
        'takingTeam': taking_team,
        'firstPossessionTeam': next_owner,
        'outcome': outcome,
        'confidence': confidence,
        'coachingInterpretation': coaching,
        'durationSeconds': kickout_chain.get('durationSeconds', 0),
    }


def analyse_kickout_patterns(chains: List[Dict[str, Any]]) -> Dict[str, Any]:
    kickouts = []

    for index, chain in enumerate(chains):
        if not is_kickout_chain(chain):
            continue
        kickouts.append(classify_kickout_outcome(chain, nearest_next_chain(chains, index)))

    retained = [item for item in kickouts if item['outcome'] == 'retained']
    lost = [item for item in kickouts if item['outcome'] == 'lost']
    contested = [item for item in kickouts if item['outcome'] == 'contested_or_unclear']
    unknown = [item for item in kickouts if item['outcome'] == 'unknown']

    total_known = len(retained) + len(lost)
    retention_rate = None
    if total_known:
        retention_rate = round((len(retained) / total_known) * 100, 1)

    if len(kickouts) == 0:
        theme = 'No clear kickout pattern detected.'
    elif retention_rate is None:
        theme = 'Kickout structures were identified, but ownership outcomes were unclear.'
    elif retention_rate >= 65:
        theme = 'Kickout platform appears positive from identified restarts.'
    elif retention_rate <= 40:
        theme = 'Kickout retention appears to be a pressure point.'
    else:
        theme = 'Kickout outcomes appear mixed.'

    return {
        'kickoutsIdentified': len(kickouts),
        'retained': len(retained),
        'lost': len(lost),
        'contestedOrUnclear': len(contested),
        'unknown': len(unknown),
        'retentionRate': retention_rate if retention_rate is not None else 'Unknown',
        'kickoutOutcomes': kickouts[:20],
        'mainCoachingTheme': theme,
        'confidence': 'medium' if total_known >= 4 else 'low'
    }
