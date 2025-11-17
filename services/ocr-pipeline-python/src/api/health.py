"""Minimal health check endpoint for Docker container monitoring."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """
    Basic health check endpoint for Docker healthcheck.
    
    Returns:
        Simple status response indicating the service is running.
    """
    return JSONResponse(content={"status": "ok"})
