from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import os
import subprocess
import tempfile

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional CV dependency
    cv2 = None
    np = None

try:
    from ultralytics import YOLO  # type: ignore
except Exception:  # pragma: no cover - optional YOLO dependency
    YOLO = None


@dataclass
class PlayerDetectionConfig:
    model_name: str = os.getenv("YOLO_MODEL", "yolov8n.pt")
    confidence: float = float(os.getenv("YOLO_CONFIDENCE", "0.35"))
    max_frames: int = int(os.getenv("YOLO_MAX_FRAMES", "8"))
    frame_width: int = int(os.getenv("YOLO_FRAME_WIDTH", "960"))


def yolo_available() -> bool:
    return YOLO is not None and cv2 is not None and np is not None


def unavailable_result(reason: str = "YOLO dependencies unavailable") -> Dict[str, Any]:
    return {
        "enabled": False,
        "status": "unavailable",
        "reason": reason,
        "framesAnalysed": 0,
        "playersDetected": 0,
        "teamColourCounts": {},
        "shape": {
            "width": "unknown",
            "compactness": "unknown",
            "overloadCue": "unknown"
        },
        "frameSummaries": []
    }


def extract_cv_frames(video_path: str, start_second: int, duration: int, output_dir: str, config: PlayerDetectionConfig) -> List[str]:
    os.makedirs(output_dir, exist_ok=True)
    fps = max(0.1, config.max_frames / max(1, duration))
    pattern = os.path.join(output_dir, "cv_%02d.jpg")
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(max(0, start_second)),
        "-i", video_path,
        "-t", str(max(1, duration)),
        "-vf", f"fps={fps},scale={config.frame_width}:-1",
        "-frames:v", str(config.max_frames),
        pattern
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return sorted([os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.startswith("cv_") and f.endswith(".jpg")])


def dominant_colour_label(crop: Any) -> str:
    if cv2 is None or np is None or crop is None or crop.size == 0:
        return "unknown"

    # Focus on upper torso area, avoiding shorts/legs and background as much as possible.
    h, w = crop.shape[:2]
    torso = crop[int(h * 0.15):int(h * 0.55), int(w * 0.15):int(w * 0.85)]
    if torso.size == 0:
        return "unknown"

    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)
    # Remove very dark/very pale pixels which are often shadows, lines, skin, socks or background.
    pixels = pixels[(pixels[:, 1] > 35) & (pixels[:, 2] > 45)]
    if len(pixels) == 0:
        return "unknown"

    hue = float(np.median(pixels[:, 0]))
    sat = float(np.median(pixels[:, 1]))
    val = float(np.median(pixels[:, 2]))

    if val < 65:
        return "black/dark"
    if sat < 45 and val > 165:
        return "white/light"

    # OpenCV hue is 0-179.
    if hue < 8 or hue >= 170:
        return "red"
    if hue < 22:
        return "orange"
    if hue < 35:
        return "yellow"
    if hue < 85:
        return "green"
    if hue < 105:
        return "cyan"
    if hue < 132:
        return "blue"
    if hue < 160:
        return "purple"
    return "red"


def shape_summary(boxes: List[Tuple[int, int, int, int]], frame_width: int, frame_height: int) -> Dict[str, str]:
    if not boxes:
        return {"width": "unknown", "compactness": "unknown", "overloadCue": "unknown"}

    centres = [((x1 + x2) / 2, (y1 + y2) / 2) for x1, y1, x2, y2 in boxes]
    xs = [c[0] for c in centres]
    ys = [c[1] for c in centres]
    spread_x = (max(xs) - min(xs)) / max(1, frame_width)
    spread_y = (max(ys) - min(ys)) / max(1, frame_height)

    width = "wide" if spread_x > 0.62 else "medium" if spread_x > 0.38 else "narrow"
    compactness = "compact" if spread_x < 0.42 and spread_y < 0.42 else "stretched" if spread_x > 0.68 or spread_y > 0.60 else "medium"

    left = sum(1 for x, _ in centres if x < frame_width / 3)
    centre = sum(1 for x, _ in centres if frame_width / 3 <= x <= frame_width * 2 / 3)
    right = sum(1 for x, _ in centres if x > frame_width * 2 / 3)
    overloadCue = "left_channel" if left >= centre + 2 and left >= right + 2 else "right_channel" if right >= centre + 2 and right >= left + 2 else "central_channel" if centre >= left + 2 and centre >= right + 2 else "balanced"

    return {"width": width, "compactness": compactness, "overloadCue": overloadCue}


def detect_players_in_frame(model: Any, frame_path: str, config: PlayerDetectionConfig) -> Dict[str, Any]:
    if cv2 is None:
        return {"playersDetected": 0, "teamColourCounts": {}, "shape": shape_summary([], 1, 1), "detections": []}

    image = cv2.imread(frame_path)
    if image is None:
        return {"playersDetected": 0, "teamColourCounts": {}, "shape": shape_summary([], 1, 1), "detections": []}

    height, width = image.shape[:2]
    results = model.predict(source=frame_path, conf=config.confidence, verbose=False)
    detections: List[Dict[str, Any]] = []
    boxes: List[Tuple[int, int, int, int]] = []
    colour_counts: Dict[str, int] = {}

    for result in results:
        for box in result.boxes:
            cls = int(box.cls[0]) if box.cls is not None else -1
            # COCO class 0 is person for standard YOLO models.
            if cls != 0:
                continue
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image[y1:y2, x1:x2]
            colour = dominant_colour_label(crop)
            colour_counts[colour] = colour_counts.get(colour, 0) + 1
            boxes.append((x1, y1, x2, y2))
            detections.append({
                "box": [x1, y1, x2, y2],
                "colour": colour,
                "confidence": float(box.conf[0]) if box.conf is not None else None
            })

    return {
        "playersDetected": len(detections),
        "teamColourCounts": colour_counts,
        "shape": shape_summary(boxes, width, height),
        "detections": detections
    }


def summarise_frames(frame_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_players = sum(int(f.get("playersDetected", 0)) for f in frame_summaries)
    colour_counts: Dict[str, int] = {}
    width_votes: Dict[str, int] = {}
    compactness_votes: Dict[str, int] = {}
    overload_votes: Dict[str, int] = {}

    for frame in frame_summaries:
        for colour, count in (frame.get("teamColourCounts") or {}).items():
            colour_counts[colour] = colour_counts.get(colour, 0) + int(count)
        shape = frame.get("shape") or {}
        width_votes[shape.get("width", "unknown")] = width_votes.get(shape.get("width", "unknown"), 0) + 1
        compactness_votes[shape.get("compactness", "unknown")] = compactness_votes.get(shape.get("compactness", "unknown"), 0) + 1
        overload_votes[shape.get("overloadCue", "unknown")] = overload_votes.get(shape.get("overloadCue", "unknown"), 0) + 1

    def top(votes: Dict[str, int]) -> str:
        return max(votes, key=votes.get) if votes else "unknown"

    return {
        "enabled": True,
        "status": "complete",
        "framesAnalysed": len(frame_summaries),
        "playersDetected": total_players,
        "teamColourCounts": dict(sorted(colour_counts.items(), key=lambda item: item[1], reverse=True)),
        "shape": {
            "width": top(width_votes),
            "compactness": top(compactness_votes),
            "overloadCue": top(overload_votes)
        },
        "frameSummaries": frame_summaries
    }


def analyse_player_detection(video_path: str, start_second: int = 0, duration: int = 45, config: Optional[PlayerDetectionConfig] = None) -> Dict[str, Any]:
    config = config or PlayerDetectionConfig()
    if not yolo_available():
        return unavailable_result()

    try:
        model = YOLO(config.model_name)
        with tempfile.TemporaryDirectory() as tmpdir:
            frames = extract_cv_frames(video_path, start_second, duration, tmpdir, config)
            summaries = []
            for index, frame in enumerate(frames):
                summary = detect_players_in_frame(model, frame, config)
                summary["frameIndex"] = index
                summaries.append(summary)
            return summarise_frames(summaries)
    except Exception as exc:
        return unavailable_result(str(exc))
