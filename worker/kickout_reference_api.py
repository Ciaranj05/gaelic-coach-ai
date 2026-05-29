from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kickout_reference import compare_candidate_to_reference_library

router = APIRouter()


class KickoutReferenceTestRequest(BaseModel):
    videoUrl: str
    timestamp: int = 0
    bucketName: str | None = None


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
