import base64
import os
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse, unquote

from google.cloud import storage
from google.oauth2 import service_account
from openai import OpenAI
import yt_dlp


DEFAULT_BUCKET = os.getenv('GCS_UPLOAD_BUCKET', 'gaelic-coach-ai-uploads')
POSITIVE_PREFIX = os.getenv('KICKOUT_POSITIVE_PREFIX', 'kickout/positive/')
NEGATIVE_PREFIX = os.getenv('KICKOUT_NEGATIVE_PREFIX', 'kickout/negative/')


def get_storage_client() -> storage.Client:
    project_id = os.getenv('GCP_PROJECT_ID')
    client_email = os.getenv('GCP_CLIENT_EMAIL')
    private_key = os.getenv('GCP_PRIVATE_KEY')

    missing = []
    if not project_id:
        missing.append('GCP_PROJECT_ID')
    if not client_email:
        missing.append('GCP_CLIENT_EMAIL')
    if not private_key:
        missing.append('GCP_PRIVATE_KEY')
    if missing:
        raise RuntimeError(f"Missing Railway env vars for GCS auth: {', '.join(missing)}")

    private_key = private_key.replace('\\n', '\n')
    if 'BEGIN PRIVATE KEY' not in private_key or 'END PRIVATE KEY' not in private_key:
        raise RuntimeError('GCP_PRIVATE_KEY is present but does not contain valid BEGIN/END PRIVATE KEY markers')

    credentials = service_account.Credentials.from_service_account_info({
        'type': 'service_account',
        'project_id': project_id,
        'private_key_id': os.getenv('GCP_PRIVATE_KEY_ID', ''),
        'private_key': private_key,
        'client_email': client_email,
        'client_id': os.getenv('GCP_CLIENT_ID', ''),
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url': f'https://www.googleapis.com/robot/v1/metadata/x509/{client_email.replace("@", "%40")}',
        'universe_domain': 'googleapis.com',
    })
    return storage.Client(project=project_id, credentials=credentials)


def _image_content_from_path(path: str) -> dict[str, Any]:
    with open(path, 'rb') as handle:
        encoded = base64.b64encode(handle.read()).decode('utf-8')
    return {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{encoded}', 'detail': 'low'}}


def parse_gcs_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.netloc == 'storage.googleapis.com':
        parts = parsed.path.lstrip('/').split('/', 1)
        if len(parts) == 2:
            return parts[0], unquote(parts[1])
    if parsed.netloc.endswith('.storage.googleapis.com'):
        bucket = parsed.netloc.replace('.storage.googleapis.com', '')
        return bucket, unquote(parsed.path.lstrip('/'))
    return None


def download_gcs_object(bucket_name: str, object_name: str, target_path: str) -> str:
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    if not blob.exists():
        raise RuntimeError(f'GCS object not found: gs://{bucket_name}/{object_name}')
    blob.download_to_filename(target_path)
    return target_path


def list_reference_images(bucket_name: str, prefix: str, limit: int = 10) -> list[str]:
    client = get_storage_client()
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
    os.makedirs(target_dir, exist_ok=True)
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    paths: list[str] = []
    for index, name in enumerate(names, start=1):
        ext = os.path.splitext(name)[1] or '.jpg'
        path = os.path.join(target_dir, f'ref_{index:02d}{ext}')
        bucket.blob(name).download_to_filename(path)
        paths.append(path)
    return paths


def download_video(video_url: str, target_path: str) -> str:
    gcs_ref = parse_gcs_url(video_url)
    if gcs_ref:
        bucket_name, object_name = gcs_ref
        return download_gcs_object(bucket_name, object_name, target_path)

    with yt_dlp.YoutubeDL({
        'format': 'best[height<=360]/best',
        'outtmpl': target_path,
        'quiet': True,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'nocheckcertificate': True,
    }) as ydl:
        ydl.download([video_url])
    return target_path


def extract_video_frame(video_url: str, timestamp: int, target_dir: str) -> str:
    video_path = os.path.join(target_dir, 'match.mp4')
    frame_path = os.path.join(target_dir, 'candidate.jpg')
    download_video(video_url, video_path)
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
