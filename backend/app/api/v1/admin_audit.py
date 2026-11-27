"""Administrator audit-event listing API (Part 4, Stage 5).

``GET /admin/audit-events`` lists recorded audit events for administrators.
``require_administrator`` is attached to the router, so any route added here
later inherits it.

- Read-only: the repository reads in SQLite's ``query_only`` mode, and a
  successful listing records no audit event of its own. (A student who is
  refused still produces the usual ``authorization.denied`` event.)
- Responses use the Task 3 schemas: event details are reduced to an explicit
  allowlist, so the failed sign-in counter and lock expiry recorded for sign-in
  events are never returned. Audit events never contain passwords, hashes,
  tokens, email addresses or client IPs in the first place.
- Errors are generic; details are logged, never returned.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.deps import AuthenticatedUser, get_auth_db_path, require_administrator
from backend.app.api.permissions import ADMINISTRATOR_ONLY_RESPONSES
from backend.app.api.v1.admin_users import _no_store
from backend.app.audit.repository import list_audit_events
from backend.app.schemas.admin import AuditEventListQuery, AuditEventListResponse, AuditEventResponse

logger = logging.getLogger(__name__)

AUDIT_LIST_ERROR_DETAIL = "The audit-event request failed due to an internal server error."

router = APIRouter(
    prefix="/admin/audit-events",
    tags=["administration"],
    dependencies=[Depends(require_administrator), Depends(_no_store)],
    responses={
        **ADMINISTRATOR_ONLY_RESPONSES,
        500: {"description": "Internal server error. Details are logged, never returned."},
    },
)


@router.get("", response_model=AuditEventListResponse, summary="List audit events")
def list_events(
    query: Annotated[AuditEventListQuery, Query()],
    _administrator: Annotated[AuthenticatedUser, Depends(require_administrator)],
    db_path: Annotated[Optional[str | Path], Depends(get_auth_db_path)],
) -> AuditEventListResponse:
    """List audit events, newest first (ties broken by id), with bounded pagination.

    Filters are exact, except ``occurred_after`` and ``occurred_before``, which
    are inclusive bounds and must include a timezone offset. ``target_id``
    requires ``target_type``. Only approved, non-sensitive detail keys are returned.
    """
    try:
        page = list_audit_events(**query.model_dump(), db_path=db_path)
    except Exception:
        # The query schema already rejects invalid filters, so any failure here
        # (including a repository ValueError) is a server fault.
        logger.exception("Listing audit events failed.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=AUDIT_LIST_ERROR_DETAIL) from None
    return AuditEventListResponse(
        events=[AuditEventResponse.from_event(event) for event in page.events],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
