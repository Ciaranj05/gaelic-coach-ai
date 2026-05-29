import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kickout_reference import compare_candidate_to_reference_library, scan_match_for_kickouts_with_reference_library
from kickout_profile_scan import scan_match_for_kickouts_with_profile

router = APIRouter()


class KickoutReferenceTestRequest(BaseModel):
    videoUrl: str
    timestamp: int = 0
    bucketName: str | None = None


class KickoutReferenceScanRequest(BaseModel):
    videoUrl: str
    bucketName: str | None = None
    intervalSeconds: int = 120
    maxFrames: int = 30
    minSimilarity: int = 60


class KickoutProfileScanRequest(BaseModel):
    videoUrl: str
    bucketName: str | None = None
    intervalSeconds: int = 30
    maxFrames: int = 200
    includeReview: bool = True


@router.get('/debug/env-keys')
def debug_env_keys():
    prefixes = ('GCP', 'GCS', 'GOOGLE', 'OPENAI', 'RAILWAY')
    visible_keys = sorted([key for key in os.environ.keys() if key.startswith(prefixes)])
    return {'ok': True, 'visibleKeys': visible_keys, 'count': len(visible_keys), 'hasExpected': {'GCP_PROJECT_ID': 'GCP_PROJECT_ID' in os.environ, 'GCP_CLIENT_EMAIL': 'GCP_CLIENT_EMAIL' in os.environ, 'GCP_PRIVATE_KEY': 'GCP_PRIVATE_KEY' in os.environ, 'GCS_UPLOAD_BUCKET': 'GCS_UPLOAD_BUCKET' in os.environ, 'OPENAI_API_KEY': 'OPENAI_API_KEY' in os.environ}}


@router.get('/debug/env-check')
def debug_env_check():
    private_key = os.getenv('GCP_PRIVATE_KEY') or ''
    client_email = os.getenv('GCP_CLIENT_EMAIL') or ''
    project_id = os.getenv('GCP_PROJECT_ID') or ''
    bucket = os.getenv('GCS_UPLOAD_BUCKET') or ''

    return {'ok': True, 'checks': {'GCP_PROJECT_ID_present': bool(project_id), 'GCP_PROJECT_ID_length': len(project_id), 'GCP_CLIENT_EMAIL_present': bool(client_email), 'GCP_CLIENT_EMAIL_length': len(client_email), 'GCP_CLIENT_EMAIL_looks_valid': client_email.endswith('.iam.gserviceaccount.com'), 'GCP_PRIVATE_KEY_present': bool(private_key), 'GCP_PRIVATE_KEY_length': len(private_key), 'GCP_PRIVATE_KEY_has_begin_marker': 'BEGIN PRIVATE KEY' in private_key, 'GCP_PRIVATE_KEY_has_end_marker': 'END PRIVATE KEY' in private_key, 'GCP_PRIVATE_KEY_contains_escaped_newlines': '\\n' in private_key, 'GCP_PRIVATE_KEY_contains_real_newlines': '\n' in private_key, 'GCS_UPLOAD_BUCKET_present': bool(bucket), 'GCS_UPLOAD_BUCKET_length': len(bucket)}, 'safeValues': {'GCP_PROJECT_ID': project_id, 'GCP_CLIENT_EMAIL_domain': client_email.split('@')[-1] if '@' in client_email else '', 'GCS_UPLOAD_BUCKET': bucket or 'gaelic-coach-ai-uploads'}}


@router.post('/debug/kickout-reference-test')
def debug_kickout_reference_test(request: KickoutReferenceTestRequest):
    try:
        result = compare_candidate_to_reference_library(video_url=request.videoUrl, timestamp=request.timestamp, bucket_name=request.bucketName or 'gaelic-coach-ai-uploads')
        return {'ok': True, 'test': 'kickout-reference-library', **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post('/debug/kickout-reference-scan')
def debug_kickout_reference_scan(request: KickoutReferenceScanRequest):
    try:
        return scan_match_for_kickouts_with_reference_library(
            video_url=request.videoUrl,
            bucket_name=request.bucketName or 'gaelic-coach-ai-uploads',
            interval_seconds=request.intervalSeconds,
            max_frames=request.maxFrames,
            min_similarity=request.minSimilarity,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post('/debug/kickout-profile-scan')
def debug_kickout_profile_scan(request: KickoutProfileScanRequest):
    try:
        return scan_match_for_kickouts_with_profile(
            video_url=request.videoUrl,
            bucket_name=request.bucketName or 'gaelic-coach-ai-uploads',
            interval_seconds=request.intervalSeconds,
            max_frames=request.maxFrames,
            include_review=request.includeReview,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
