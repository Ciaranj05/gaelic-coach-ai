from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List


TEAM_COLOURS = [
    'red', 'maroon', 'green', 'blue', 'yellow', 'white', 'black', 'orange'
]


def normalise_colour(colour: str) -> str:
    colour = str(colour or '').lower().strip()
    for known in TEAM_COLOURS:
        if known in colour:
            return known
    return colour or 'unknown'


def extract_primary_colour(cv_result: Dict[str, Any]) -> str:
    colours = (cv_result or {}).get('teamColourCounts') or {}
    if not colours:
        return 'unknown'

    ordered = sorted(colours.items(), key=lambda item: item[1], reverse=True)
    return normalise_colour(ordered[0][0])


def build_team_timeline(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    timeline = []

    for event in events:
        if not isinstance(event, dict):
            continue

        cv_result = event.get('cvPlayerDetection') or {}
        colour = extract_primary_colour(cv_result)

        timeline.append({
            'time': event.get('time'),
            'eventType': event.get('type'),
            'teamColour': colour,
            'startSecond': event.get('startSecond'),
            'endSecond': event.get('endSecond'),
        })

    return timeline


def infer_possession_sequences(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    timeline = build_team_timeline(events)

    possession_windows = Counter()
    turnovers = 0
    longest_chain = 0
    current_chain = 0
    previous_colour = None

    transitions = []

    for item in timeline:
        colour = item.get('teamColour', 'unknown')

        if colour != 'unknown':
            possession_windows[colour] += 1

        if previous_colour and colour != 'unknown' and colour != previous_colour:
            turnovers += 1
            transitions.append({
                'time': item.get('time'),
                'from': previous_colour,
                'to': colour,
                'type': 'possession_turnover'
            })
            current_chain = 1
        else:
            current_chain += 1

        longest_chain = max(longest_chain, current_chain)
        previous_colour = colour if colour != 'unknown' else previous_colour

    total_windows = sum(possession_windows.values())

    possession_percentages = {
        colour: round((count / max(1, total_windows)) * 100, 1)
        for colour, count in possession_windows.items()
    }

    dominant_team = None
    if possession_windows:
        dominant_team = max(possession_windows, key=possession_windows.get)

    return {
        'timeline': timeline,
        'dominantTeamColour': dominant_team or 'unknown',
        'possessionPercentages': possession_percentages,
        'estimatedTurnovers': turnovers,
        'longestPossessionChain': longest_chain,
        'transitionMoments': transitions[:20],
        'confidence': 'medium' if total_windows >= 8 else 'low'
    }
