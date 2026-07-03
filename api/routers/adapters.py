from fastapi import APIRouter, Depends
from api.security import verify_api_key

router = APIRouter(prefix="/api/v1/adapters", dependencies=[Depends(verify_api_key)])

@router.get("/status")
async def adapter_status():
    # In a real implementation, this would ping DBs, S3, etc.
    return {
        "api": "healthy", "database": "healthy", "email": "healthy",
        "file_system": "healthy", "excel": "healthy", "pdf_ocr": "healthy",
        "cloud": "healthy", "workflow": "healthy"
    }