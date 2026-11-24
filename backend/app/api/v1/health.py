"""Health API routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
def health_check() -> dict[str, str]:
    """Return a basic health response indicating the API is running."""
    return {
        "status": "ok",
        "service": settings.project_name,
        "message": "API is running",
    }
