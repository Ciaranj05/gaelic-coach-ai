import base64
import os
import subprocess
import tempfile
from typing import Any

from google.cloud import storage
from openai import OpenAI
import yt_dlp


DEFAULT_BUCKET = os.getenv('GCS_UPLOAD_BUCKET', 'gaelic-coach-ai-uploads')
POSITIVE_PREFIX = os.getenv('KICKOUT_POSITIVE_PREFIX', 'kickout/positive/')
NEGATIVE_PREFIX = os.getenv('KICKOUT_NEGATIVE_PREFIX', 'kickout/negative/')


def _image_content_from_path(path: str) -> dict[str, Any]:
    with open(path, 'rb') as handle:
        encoded = base64.b64encode(handle.read()).decode('utf-8')
    return {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{encoded}', 'detail': 'low'}}


def list_reference_images(bucket_name: str, prefix: str, limit: int = 10) -> list[str]:
    client = storage.Client()
    blobs = client.list_blobs(bucket_name, prefix=prefix)
    image_names: list[str] = []
    for blob in blobs:
        lower = blob.name.lower()
        if lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            image_names.append(blob.name)
        if len(image_names) >= limit:
            break
    return image_names


def download_reference_images(bucket_name: str, names: list[str], target_dir: str) -> list[str]:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    paths: list[str] = []
    for index, name in enumerate(names, start=1):
        ext = os.path.splitext(name)[1] or '.jpg'
        path = os.path.join(target_dir, f'ref_{index:02d}{ext}')
        bucket.blob(name).download_to_filename(path)
        paths.append(path)
    return paths


def extract_video_frame(video_url: str, timestamp: int, target_dir: str) -> str:
    video_path = os.path.join(target_dir, 'match.mp4')
    frame_path = os.path.join(target_dir, 'candidate.jpg')
    with yt_dlp.YoutubeDL({
        'format': 'best[height<=360]/best',
        'outtmpl': video_path,
        'quiet': True,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'nocheckcertificate': True,
    }) as ydl:
        ydl.download([video_url])
    subprocess.run([
        'ffmpeg', '-y', '-ss', str(max(0, int(timestamp))), '-i', video_path,
        '-frames:v', '1', '-vf', 'scale=768:-1', frame_path,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not os.path.exists(frame_path):
        raise RuntimeError('Unable to extract candidate frame from video')
    return frame_path


def compare_candidate_to_reference_library(video_url: str, timestamp: int = 0, bucket_name: str = DEFAULT_BUCKET) -> dict[str, Any]:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is missing')

    positive_names = list_reference_images(bucket_name, POSITIVE_PREFIX, limit=10)
    negative_names = list_reference_images(bucket_name, NEGATIVE_PREFIX, limit=10)
    if not positive_names or not negative_names:
        raise RuntimeError('Kickout reference library is missing positive or negative images')

    with tempfile.TemporaryDirectory() as tmpdir:
        candidate_path = extract_video_frame(video_url, timestamp, tmpdir)
        positive_paths = download_reference_images(bucket_name, positive_names, os.path.join(tmpdir, 'positive'))
        negative_paths = download_reference_images(bucket_name, negative_names, os.path.join(tmpdir, 'negative'))

        content: list[dict[str, Any]] = [{
            'type': 'text',
            'text': '''You are testing a Gaelic football kickout reference library. Compare the candidate frame against labelled examples.
Positive examples are confirmed kickout setups. Negative examples are confirmed non-kickouts/open play.
Return JSON only with: kickoutSimilarity 0-100, nonKickoutSimilarity 0-100, label likely_kickout|possible_kickout|unlikely_kickout|not_kickout, confidence low|medium|high, positiveMatches array, negativeMatches array, reasoning string.
Be conservative. If candidate resembles open play, clusters, active tackling, or transition, mark not_kickout.'''
        }, {'type': 'text', 'text': 'CANDIDATE FRAME:'}, _image_content_from_path(candidate_path), {'type': 'text', 'text': 'POSITIVE KICKOUT EXAMPLES:'}]
        content.extend(_image_content_from_path(path) for path in positive_paths)
        content.append({'type': 'text', 'text': 'NEGATIVE NON-KICKOUT EXAMPLES:'})
        content.extend(_image_content_from_path(path) for path in negative_paths)

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            response_format={'type': 'json_object'},
            messages=[{'role': 'user', 'content': content}],
        )
        raw = response.choices[0].message.content or '{}'

    try:
        import json
        parsed = json.loads(raw)
    except Exception:
        parsed = {'raw': raw}

    parsed['referenceLibrary'] = {
        'bucket': bucket_name,
        'positivePrefix': POSITIVE_PREFIX,
        'negativePrefix': NEGATIVE_PREFIX,
        'positiveCount': len(positive_names),
        'negativeCount': len(negative_names),
    }
    parsed['timestamp'] = timestamp
    return parsed
