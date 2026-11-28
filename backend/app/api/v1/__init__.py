"""Version 1 API routers."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1 import admin_audit, admin_users, auth, change_radar, health, impact_twin, query, regulations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(regulations.router)
api_router.include_router(query.router)
api_router.include_router(auth.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_audit.router)
api_router.include_router(change_radar.router)
api_router.include_router(impact_twin.router)
