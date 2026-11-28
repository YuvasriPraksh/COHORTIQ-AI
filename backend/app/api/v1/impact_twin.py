"""My Academic Impact Twin API: cohort-scoped impact of approved regulation changes.

The cohort always comes from the authenticated account; the endpoint accepts no
batch or programme input, so a client cannot request another cohort's changes.
Only Change Radar reviews that an administrator approved, whose new regulation
is approved, and whose recorded applicability includes the account's cohort are
assessed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import AuthenticatedUser, get_auth_db_path, get_current_user
from backend.app.schemas.impact_twin import ImpactTwinResponse
from backend.app.services import impact_twin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["academic impact twin"])


@router.get(
    "/impact-twin",
    response_model=ImpactTwinResponse,
    responses={
        401: {"description": "Not signed in."},
    },
)
def get_impact_twin(
    user: AuthenticatedUser = Depends(get_current_user),
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> ImpactTwinResponse:
    # Administrators have no cohort: like /updates, they receive an empty assessment.
    is_admin = user.role == "administrator"
    try:
        result = impact_twin.build_assessment(
            user_id=user.id,
            admission_batch=None if is_admin else user.admission_batch,
            programme=None if is_admin else user.programme,
            db_path=db_path,
        )
    except Exception:
        logger.exception("Could not build the Academic Impact Twin for an authenticated cohort.")
        raise HTTPException(status_code=500, detail="The Academic Impact Twin is temporarily unavailable.") from None
    return ImpactTwinResponse.model_validate(result)
