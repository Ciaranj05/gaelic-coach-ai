from __future__ import annotations

from typing import Any, Dict, List

try:
    from cv_player_detection import analyse_player_detection, yolo_available
except Exception:
    analyse_player_detection = None

    def yolo_available() -> bool:
        return False

try:
    from possession_tracker import infer_possession_sequences
except Exception:
    def infer_possession_sequences(events: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            'dominantTeamColour': 'unknown',
            'possessionPercentages': {},
            'estimatedTurnovers': 0,
            'longestPossessionChain': 0,
            'transitionMoments': [],
            'confidence': 'low'
        }


def cv_status() -> Dict[str, Any]:
    return {
        "enabled": yolo_available(),
        "phase": "player_detection_team_colour_shape_possession_tracking",
        "features": [
            "player_detection",
            "team_colour_grouping",
            "width_estimation",
            "compactness_estimation",
            "overload_cues",
            "persistent_team_tracking",
            "possession_inference",
            "transition_detection",
            "turnover_estimation",
        ],
    }


def run_cv_on_event(video_path: str, start_second: int, end_second: int) -> Dict[str, Any]:
    if analyse_player_detection is None or not yolo_available():
        return {
            "enabled": False,
            "status": "unavailable",
            "reason": "CV dependencies are not available in this worker runtime.",
        }

    duration = max(8, int(end_second) - int(start_second))
    return analyse_player_detection(video_path, int(start_second), duration)


def attach_cv_summary(event: Dict[str, Any], video_path: str) -> Dict[str, Any]:
    start_second = int(event.get("startSecond", 0) or 0)
    end_second = int(event.get("endSecond", start_second + 30) or start_second + 30)
    event["cvPlayerDetection"] = run_cv_on_event(video_path, start_second, end_second)
    return event


def build_match_possession_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    return infer_possession_sequences(events)
