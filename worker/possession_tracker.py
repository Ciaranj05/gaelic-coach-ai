from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


TEAM_COLOURS = [
    'red', 'maroon', 'green', 'blue', 'yellow', 'white', 'black', 'orange',
    'purple', 'navy', 'sky', 'gold', 'grey', 'gray'
]


def normalise_colour(colour: str) -> str:
    colour = str(colour or '').lower().strip()
    for known in TEAM_COLOURS:
        if known in colour:
            return 'grey' if known == 'gray' else known
    return colour or 'unknown'


def colour_score_map(cv_result: Dict[str, Any]) -> Dict[str, int]:
    colours = (cv_result or {}).get('teamColourCounts') or {}
    mapped: Counter[str] = Counter()
    for colour, count in colours.items():
        mapped[normalise_colour(colour)] += int(count or 0)
    mapped.pop('unknown', None)
    return dict(mapped)


def extract_primary_colour(cv_result: Dict[str, Any]) -> str:
    mapped = colour_score_map(cv_result)
    if not mapped:
        return 'unknown'
    return max(mapped, key=mapped.get)


def map_colour_to_team(colour: str, facts: Optional[Dict[str, Any]] = None) -> str:
    facts = facts or {}
    colour = normalise_colour(colour)
    if colour == 'unknown':
        return 'unknown'

    team_a_colour = normalise_colour(facts.get('teamAColour') or facts.get('teamAColours') or '')
    team_b_colour = normalise_colour(facts.get('teamBColour') or facts.get('teamBColours') or '')

    if team_a_colour and team_a_colour != 'unknown' and colour in team_a_colour:
        return str(facts.get('teamA') or 'Team A')
    if team_b_colour and team_b_colour != 'unknown' and colour in team_b_colour:
        return str(facts.get('teamB') or 'Team B')
    return colour


def build_team_timeline(events: List[Dict[str, Any]], facts: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    timeline = []

    for event in sorted([e for e in events if isinstance(e, dict)], key=lambda e: int(e.get('startSecond') or 0)):
        cv_result = event.get('cvPlayerDetection') or {}
        colour_scores = colour_score_map(cv_result)
        colour = extract_primary_colour(cv_result)
        owner = map_colour_to_team(colour, facts)

        start_second = int(event.get('startSecond') or 0)
        end_second = int(event.get('endSecond') or start_second + 30)

        timeline.append({
            'time': event.get('time'),
            'eventType': event.get('type'),
            'teamColour': colour,
            'owner': owner,
            'colourScores': colour_scores,
            'startSecond': start_second,
            'endSecond': end_second,
            'durationSeconds': max(0, end_second - start_second),
            'confidence': 'medium' if colour_scores else 'low',
        })

    return timeline


def build_possession_chains(timeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chains: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for item in timeline:
        owner = item.get('owner') or 'unknown'
        if owner == 'unknown':
            if current:
                current['events'].append(item)
                current['endSecond'] = max(current['endSecond'], int(item.get('endSecond') or current['endSecond']))
            continue

        if current and current.get('owner') == owner:
            current['events'].append(item)
            current['endSecond'] = max(current['endSecond'], int(item.get('endSecond') or current['endSecond']))
            current['eventCount'] += 1
        else:
            if current:
                chains.append(current)
            current = {
                'owner': owner,
                'teamColour': item.get('teamColour'),
                'startSecond': int(item.get('startSecond') or 0),
                'endSecond': int(item.get('endSecond') or 0),
                'eventCount': 1,
                'events': [item],
            }

    if current:
        chains.append(current)

    for index, chain in enumerate(chains, start=1):
        duration = max(0, int(chain.get('endSecond') or 0) - int(chain.get('startSecond') or 0))
        chain['chainId'] = index
        chain['durationSeconds'] = duration
        chain['time'] = f"{format_seconds(chain['startSecond'])}–{format_seconds(chain['endSecond'])} approx"
        chain['types'] = [event.get('eventType') for event in chain.get('events', []) if event.get('eventType')]

    return chains


def format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def infer_turnover_moments(chains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    moments = []
    for previous, current in zip(chains, chains[1:]):
        if previous.get('owner') != current.get('owner'):
            moments.append({
                'time': f"{format_seconds(current.get('startSecond', 0))} approx",
                'from': previous.get('owner'),
                'to': current.get('owner'),
                'type': 'possession_turnover',
                'confidence': 'estimated',
            })
    return moments


def infer_possession_sequences(events: List[Dict[str, Any]], facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    timeline = build_team_timeline(events, facts)
    chains = build_possession_chains(timeline)
    turnovers = infer_turnover_moments(chains)

    possession_seconds: Counter[str] = Counter()
    possession_windows: Counter[str] = Counter()

    for chain in chains:
        owner = chain.get('owner') or 'unknown'
        if owner == 'unknown':
            continue
        possession_seconds[owner] += int(chain.get('durationSeconds') or 0)
        possession_windows[owner] += int(chain.get('eventCount') or 0)

    total_seconds = sum(possession_seconds.values())
    total_windows = sum(possession_windows.values())

    possession_percentages = {
        owner: round((seconds / max(1, total_seconds)) * 100, 1)
        for owner, seconds in possession_seconds.items()
    }

    window_percentages = {
        owner: round((count / max(1, total_windows)) * 100, 1)
        for owner, count in possession_windows.items()
    }

    dominant_owner = 'unknown'
    if possession_seconds:
        dominant_owner = max(possession_seconds, key=possession_seconds.get)

    longest_chain = max(chains, key=lambda c: int(c.get('durationSeconds') or 0), default={})
    reliable_windows = len([item for item in timeline if item.get('owner') != 'unknown'])

    return {
        'timeline': timeline,
        'chains': chains[:30],
        'dominantOwner': dominant_owner,
        'dominantTeamColour': longest_chain.get('teamColour') or 'unknown',
        'possessionPercentages': possession_percentages,
        'windowPercentages': window_percentages,
        'estimatedTurnovers': len(turnovers),
        'turnoverMoments': turnovers[:20],
        'longestPossessionChain': {
            'owner': longest_chain.get('owner', 'unknown'),
            'time': longest_chain.get('time', 'Unknown'),
            'durationSeconds': longest_chain.get('durationSeconds', 0),
            'eventCount': longest_chain.get('eventCount', 0),
        },
        'chainCount': len(chains),
        'reliableWindows': reliable_windows,
        'confidence': 'medium' if reliable_windows >= 8 else 'low'
    }
