from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, Optional

import yt_dlp


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return default


def ffprobe_duration(path: str) -> int:
    if not path or not os.path.exists(path):
        return 0

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return _safe_int((result.stdout or "").strip())
    except Exception:
        return 0


def base_ytdlp_options(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Prefer lower resolution files for speed/reliability on Railway.
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "socket_timeout": 60,
        "retries": 4,
        "fragment_retries": 4,
        "extractor_retries": 4,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    cookies_file = os.getenv("YTDLP_COOKIES_FILE")
    if cookies_file and os.path.exists(cookies_file):
        options["cookiefile"] = cookies_file

    cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER")
    if cookies_from_browser:
        # Example value: chrome or firefox. Usually not available on Railway, but supported for local runs.
        options["cookiesfrombrowser"] = (cookies_from_browser,)

    if extra:
        options.update(extra)

    return options


def extract_video_metadata(url: str) -> Dict[str, Any]:
    debug = {
        "metadataExtractor": "yt-dlp",
        "metadataOk": False,
        "metadataError": "",
        "durationSource": "unknown",
    }

    try:
        with yt_dlp.YoutubeDL(base_ytdlp_options({"skip_download": True})) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = _safe_int(info.get("duration"))
            debug["metadataOk"] = True
            debug["durationSource"] = "yt_dlp_info" if duration else "missing_from_yt_dlp_info"

            return {
                "title": info.get("title", "") or "",
                "description": info.get("description", "") or "",
                "uploader": info.get("uploader", "") or "",
                "duration": duration,
                "filesize": info.get("filesize") or info.get("filesize_approx") or 0,
                "webpage_url": info.get("webpage_url") or url,
                "extractor": info.get("extractor", ""),
                "debug": debug,
            }
    except Exception as exc:
        debug["metadataError"] = str(exc)[:600]
        return {
            "title": "",
            "description": "",
            "uploader": "",
            "duration": 0,
            "filesize": 0,
            "webpage_url": url,
            "extractor": "",
            "debug": debug,
        }


def download_match_video(url: str, tmpdir: str, profile: Dict[str, Any]) -> Optional[str]:
    os.makedirs(tmpdir, exist_ok=True)
    output_template = os.path.join(tmpdir, "match.%(ext)s")

    preferred_format = profile.get(
        "videoFormat",
        "bv*[height<=480]+ba/b[height<=480]/bv*[height<=360]+ba/b[height<=360]/best",
    )

    download_debug_path = os.path.join(tmpdir, "download_debug.json")
    debug: Dict[str, Any] = {
        "downloadOk": False,
        "downloadError": "",
        "downloadedPath": "",
        "ffprobeDuration": 0,
        "format": preferred_format,
    }

    options = base_ytdlp_options(
        {
            "format": preferred_format,
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "overwrites": True,
            "continuedl": True,
        }
    )

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            requested = info.get("requested_downloads") or []
            candidate_paths = []
            for item in requested:
                filepath = item.get("filepath")
                if filepath:
                    candidate_paths.append(filepath)

            for name in os.listdir(tmpdir):
                if name.startswith("match.") and not name.endswith(".part"):
                    candidate_paths.append(os.path.join(tmpdir, name))

            for path in candidate_paths:
                if path and os.path.exists(path) and os.path.getsize(path) > 0:
                    duration = ffprobe_duration(path)
                    debug.update({
                        "downloadOk": True,
                        "downloadedPath": path,
                        "ffprobeDuration": duration,
                        "filesizeBytes": os.path.getsize(path),
                    })
                    with open(download_debug_path, "w", encoding="utf-8") as handle:
                        json.dump(debug, handle)
                    return path

            debug["downloadError"] = "yt-dlp completed but no downloaded file was found"
    except Exception as exc:
        debug["downloadError"] = str(exc)[:1000]

    try:
        with open(download_debug_path, "w", encoding="utf-8") as handle:
            json.dump(debug, handle)
    except Exception:
        pass

    return None
