from typing import Any, Dict, List

WEAK_PATTERNS = [
    '0 transitions detected',
    'unknown kickout',
    'unknown restart',
    'no clips available',
    '0 transition positives',
    '0 turnovers for',
    '0 turnovers against',
    'unassessed + n/a',
]


def evidence_quality(match_evidence: Dict[str, Any]) -> str:
    surfaced = int(match_evidence.get('surfacedEvents', 0) or 0)
    sequences = int(match_evidence.get('sequenceCount', 0) or 0)
    clips = int(match_evidence.get('clipsAvailable', 0) or 0)
    high_value = int(match_evidence.get('highValueEvents', 0) or 0)

    if high_value >= 5 and sequences >= 4:
        return 'strong'

    if surfaced >= 4 or sequences >= 2 or clips >= 2:
        return 'medium'

    return 'limited'


def should_use_limited_report(match_evidence: Dict[str, Any]) -> bool:
    return evidence_quality(match_evidence) == 'limited'


def limited_evidence_notice(match_evidence: Dict[str, Any]) -> str:
    return (
        'Limited tactical evidence was extracted from the available footage. '
        f"Windows analysed: {match_evidence.get('eventsAnalysed', 0)}, "
        f"sequences built: {match_evidence.get('sequenceCount', 0)}, "
        f"review clips: {match_evidence.get('clipsAvailable', 0)}. "
        'This report should be treated as a scoreline-supported review rather than a full tactical analysis.'
    )


def quality_gate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []

    for row in rows:
        text = ' '.join([str(v).lower() for v in row.values()])

        blocked = False

        for pattern in WEAK_PATTERNS:
            if pattern in text:
                blocked = True
                break

        if blocked:
            continue

        cleaned.append(row)

    return cleaned
