"""Version 1 API routers."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1 import auth, health, query, regulations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(regulations.router)
api_router.include_router(query.router)
api_router.include_router(auth.router)
