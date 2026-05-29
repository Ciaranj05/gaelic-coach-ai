import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kickout_reference import compare_candidate_to_reference_library

router = APIRouter()


class KickoutReferenceTestRequest(BaseModel):
    videoUrl: str
    timestamp: int = 0
    bucketName: str | None = None


@router.get('/debug/env-check')
def debug_env_check():
    private_key = os.getenv('GCP_PRIVATE_KEY') or ''
    client_email = os.getenv('GCP_CLIENT_EMAIL') or ''
    project_id = os.getenv('GCP_PROJECT_ID') or ''
    bucket = os.getenv('GCS_UPLOAD_BUCKET') or ''

    return {
        'ok': True,
        'checks': {
            'GCP_PROJECT_ID_present': bool(project_id),
            'GCP_PROJECT_ID_length': len(project_id),
            'GCP_CLIENT_EMAIL_present': bool(client_email),
            'GCP_CLIENT_EMAIL_length': len(client_email),
            'GCP_CLIENT_EMAIL_looks_valid': client_email.endswith('.iam.gserviceaccount.com'),
            'GCP_PRIVATE_KEY_present': bool(private_key),
            'GCP_PRIVATE_KEY_length': len(private_key),
            'GCP_PRIVATE_KEY_has_begin_marker': 'BEGIN PRIVATE KEY' in private_key,
            'GCP_PRIVATE_KEY_has_end_marker': 'END PRIVATE KEY' in private_key,
            'GCP_PRIVATE_KEY_contains_escaped_newlines': '\\n' in private_key,
            'GCP_PRIVATE_KEY_contains_real_newlines': '\n' in private_key,
            'GCS_UPLOAD_BUCKET_present': bool(bucket),
            'GCS_UPLOAD_BUCKET_length': len(bucket),
        },
        'safeValues': {
            'GCP_PROJECT_ID': project_id,
            'GCP_CLIENT_EMAIL_domain': client_email.split('@')[-1] if '@' in client_email else '',
            'GCS_UPLOAD_BUCKET': bucket or 'gaelic-coach-ai-uploads',
        }
    }


@router.post('/debug/kickout-reference-test')
def debug_kickout_reference_test(request: KickoutReferenceTestRequest):
    try:
        result = compare_candidate_to_reference_library(
            video_url=request.videoUrl,
            timestamp=request.timestamp,
            bucket_name=request.bucketName or 'gaelic-coach-ai-uploads',
        )
        return {
            'ok': True,
            'test': 'kickout-reference-library',
            **result,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
