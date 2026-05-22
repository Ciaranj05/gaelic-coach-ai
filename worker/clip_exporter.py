from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


CLIP_DIR = "/tmp/gaelic_ai_clips"


def ensure_clip_dir() -> str:
    Path(CLIP_DIR).mkdir(parents=True, exist_ok=True)
    return CLIP_DIR



def build_clip_path(label: str) -> str:
    safe = ''.join(c.lower() if c.isalnum() else '_' for c in label)[:80]
    return os.path.join(ensure_clip_dir(), f"{safe}.mp4")



def export_clip(video_path: str, start_second: int, end_second: int, label: str) -> Optional[str]:
    if not video_path or not os.path.exists(video_path):
        return None

    output_path = build_clip_path(label)

    duration = max(6, int(end_second) - int(start_second))

    command = [
        'ffmpeg',
        '-y',
        '-ss',
        str(max(0, int(start_second))),
        '-i',
        video_path,
        '-t',
        str(duration),
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-c:a',
        'aac',
        output_path,
    ]

    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return output_path if os.path.exists(output_path) else None
    except Exception:
        return None
