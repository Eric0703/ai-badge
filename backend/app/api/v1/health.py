from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint. Returns 200 when the service is running."""
    return {"status": "ok", "version": "0.1.0"}
