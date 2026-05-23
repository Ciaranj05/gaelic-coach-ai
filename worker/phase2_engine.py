from __future__ import annotations

from typing import Any, Dict, List


FORWARD_ZONES = {
    'defensive_third': 1,
    'middle_third': 2,
    'attacking_third': 3,
    'scoring_zone': 4,
    'unknown': 0,
}


def _norm(value: Any) -> str:
    return str(value or '').strip()


def _unknown(value: Any) -> bool:
    return _norm(value).lower() in {'', 'unknown', 'none', 'null'}


def event_team(event: Dict[str, Any], facts: Dict[str, Any]) -> str:
    mi = event.get('matchIntelligence') or {}
    candidates = [
        event.get('likelyTeamInPossession'),
        mi.get('transitionTeam'),
        mi.get('turnoverTeam'),
        mi.get('kickoutTeam'),
        mi.get('possessionStart'),
        mi.get('possessionEnd'),
    ]
    teams = {facts.get('teamA'), facts.get('teamB'), facts.get('coachedTeam')}
    for candidate in candidates:
        value = _norm(candidate)
        if value in teams:
            return value
    return 'unknown'


def zone_direction(start_zone: str, end_zone: str) -> str:
    start = FORWARD_ZONES.get(_norm(start_zone), 0)
    end = FORWARD_ZONES.get(_norm(end_zone), 0)
    if not start or not end:
        return 'unknown'
    if end > start:
        return 'advanced'
    if end < start:
        return 'forced_back'
    return 'held_zone'


def possession_outcome(event: Dict[str, Any]) -> str:
    mi = event.get('matchIntelligence') or {}
    so = event.get('scoreOutcome') or {}
    for key in ['possessionOutcome', 'transitionOutcome', 'kickoutOutcome']:
        value = _norm(mi.get(key))
        if not _unknown(value) and value not in {'not_transition', 'not_kickout', 'unclear'}:
            return value
    value = _norm(so.get('outcome'))
    return value if not _unknown(value) else 'unknown'


def build_possession_chains(events: List[Dict[str, Any]], facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    usable = sorted([e for e in events if isinstance(e, dict)], key=lambda e: int(e.get('startSecond') or 0))
    chains: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    for event in usable:
        team = event_team(event, facts)
        mi = event.get('matchIntelligence') or {}
        start = int(event.get('startSecond') or 0)
        end = int(event.get('endSecond') or start + 30)
        outcome = possession_outcome(event)
        phase = {
            'time': event.get('time'),
            'type': event.get('type'),
            'team': team,
            'startSecond': start,
            'endSecond': end,
            'startZone': mi.get('startZone', 'unknown'),
            'endZone': mi.get('endZone', 'unknown'),
            'fieldZone': mi.get('fieldZone', 'unknown'),
            'direction': zone_direction(mi.get('startZone'), mi.get('endZone')),
            'outcome': outcome,
            'clip': event.get('clip'),
        }

        should_extend = bool(current and (team == current['team'] or team == 'unknown' or current['team'] == 'unknown') and start - current['endSecond'] <= 110)
        if should_extend:
            current['phases'].append(phase)
            current['endSecond'] = max(current['endSecond'], end)
            if current['team'] == 'unknown' and team != 'unknown':
                current['team'] = team
        else:
            if current:
                chains.append(current)
            current = {'team': team, 'startSecond': start, 'endSecond': end, 'phases': [phase]}

    if current:
        chains.append(current)

    for index, chain in enumerate(chains, start=1):
        phases = chain.get('phases', [])
        chain['chainId'] = index
        chain['durationSeconds'] = max(0, int(chain['endSecond']) - int(chain['startSecond']))
        chain['phaseCount'] = len(phases)
        chain['phaseChain'] = ' → '.join([_norm(p.get('type')) for p in phases[:6]])
        chain['startZone'] = next((p.get('startZone') for p in phases if not _unknown(p.get('startZone'))), 'unknown')
        chain['endZone'] = next((p.get('endZone') for p in reversed(phases) if not _unknown(p.get('endZone'))), 'unknown')
        chain['direction'] = zone_direction(chain['startZone'], chain['endZone'])
        chain['finalOutcome'] = next((p.get('outcome') for p in reversed(phases) if not _unknown(p.get('outcome'))), 'unknown')
        chain['clipCount'] = len([p for p in phases if p.get('clip')])
    return chains[:20]


def analyse_transition_ownership(events: List[Dict[str, Any]], facts: Dict[str, Any]) -> Dict[str, Any]:
    transitions = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = _norm(event.get('type')).lower()
        mi = event.get('matchIntelligence') or {}
        transition_outcome = _norm(mi.get('transitionOutcome'))
        if event_type != 'fast_transition' and transition_outcome in {'', 'unknown', 'not_transition'}:
            continue
        team = event_team(event, facts)
        direction = zone_direction(mi.get('startZone'), mi.get('endZone'))
        transitions.append({
            'time': event.get('time'),
            'team': team,
            'outcome': transition_outcome if transition_outcome else 'unknown',
            'direction': direction,
            'startZone': mi.get('startZone', 'unknown'),
            'endZone': mi.get('endZone', 'unknown'),
            'clip': event.get('clip'),
            'confidence': mi.get('confidence', event.get('confidence', 'low')),
        })

    coached = facts.get('coachedTeam')
    coached_positive = len([t for t in transitions if t['team'] == coached and t['direction'] == 'advanced'])
    opposition_positive = len([t for t in transitions if t['team'] not in {coached, 'unknown'} and t['direction'] == 'advanced'])
    return {
        'items': transitions[:20],
        'coachedPositive': coached_positive,
        'oppositionPositive': opposition_positive,
        'unknownOwnership': len([t for t in transitions if t['team'] == 'unknown']),
        'confidence': 'medium' if len(transitions) >= 3 else 'low',
    }


def analyse_kickout_direction(events: List[Dict[str, Any]], facts: Dict[str, Any]) -> Dict[str, Any]:
    kickouts = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = _norm(event.get('type')).lower()
        mi = event.get('matchIntelligence') or {}
        ko = _norm(mi.get('kickoutOutcome'))
        if event_type != 'kickout_restart' and ko in {'', 'unknown', 'not_kickout'}:
            continue
        team = event_team(event, facts)
        direction = zone_direction(mi.get('startZone'), mi.get('endZone'))
        kickouts.append({
            'time': event.get('time'),
            'team': team,
            'outcome': ko if ko else 'unknown',
            'direction': direction,
            'startZone': mi.get('startZone', 'unknown'),
            'endZone': mi.get('endZone', 'unknown'),
            'clip': event.get('clip'),
            'confidence': mi.get('confidence', event.get('confidence', 'low')),
        })
    return {
        'items': kickouts[:20],
        'advanced': len([k for k in kickouts if k['direction'] == 'advanced']),
        'heldZone': len([k for k in kickouts if k['direction'] == 'held_zone']),
        'forcedBack': len([k for k in kickouts if k['direction'] == 'forced_back']),
        'unknownDirection': len([k for k in kickouts if k['direction'] == 'unknown']),
        'confidence': 'medium' if len(kickouts) >= 3 else 'low',
    }


def build_clip_evidence(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    clips = []
    for event in events:
        clip = event.get('clip') if isinstance(event, dict) else None
        if not clip:
            continue
        clips.append({
            'time': event.get('time'),
            'type': event.get('type'),
            'summary': event.get('visualAnalysis') or event.get('reason') or 'Review clip',
            'clip': clip,
        })
    return {'available': len(clips), 'items': clips[:12]}


def build_phase2_insights(events: List[Dict[str, Any]], facts: Dict[str, Any]) -> Dict[str, Any]:
    chains = build_possession_chains(events, facts)
    transitions = analyse_transition_ownership(events, facts)
    kickouts = analyse_kickout_direction(events, facts)
    clips = build_clip_evidence(events)
    coached = facts.get('coachedTeam')
    coached_chains = len([c for c in chains if c.get('team') == coached])
    opposition_chains = len([c for c in chains if c.get('team') not in {coached, 'unknown'}])
    return {
        'possessionChains': chains,
        'possessionChainSummary': {
            'total': len(chains),
            'coached': coached_chains,
            'opposition': opposition_chains,
            'unknown': len([c for c in chains if c.get('team') == 'unknown']),
            'longestSeconds': max([c.get('durationSeconds', 0) for c in chains], default=0),
        },
        'transitionOwnership': transitions,
        'kickoutDirection': kickouts,
        'clipEvidence': clips,
    }
