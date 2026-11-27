"""Role-scoped Change Radar and student-visible approved updates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.deps import AuthenticatedUser, get_auth_db_path, get_current_user, require_administrator
from backend.app.api.permissions import ADMINISTRATOR_ONLY_RESPONSES, COHORT_SCOPED_RESPONSES, UNAUTHENTICATED_RESPONSE
from backend.app.audit.repository import AuditEventError
from backend.app.services import change_radar
from backend.app.schemas.change_radar import (
    ChangeReviewListResponse,
    ChangeReviewResponse,
    PublishedUpdatesResponse,
    ReviewCreateRequest,
    ReviewStatusRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["regulation change radar"])


@router.post(
    "/change-radar/reviews",
    response_model=ChangeReviewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_administrator)],
    responses={**ADMINISTRATOR_ONLY_RESPONSES, 404: {"description": "A selected regulation was not found."}},
)
def create_change_review(
    request: ReviewCreateRequest,
    administrator: AuthenticatedUser = Depends(require_administrator),
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> ChangeReviewResponse:
    try:
        review = change_radar.create_review(
            previous_regulation_id=request.previous_regulation_id,
            new_regulation_id=request.new_regulation_id,
            applicable_batches=request.applicable_batches,
            applicable_programmes=request.applicable_programmes,
            administrator_id=int(administrator.id),
            db_path=db_path,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="A selected regulation was not found.") from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except AuditEventError:
        raise HTTPException(status_code=503, detail="The review could not be recorded in the audit log.") from None
    except Exception:
        logger.exception("Could not compare regulation versions.")
        raise HTTPException(status_code=500, detail="The regulation comparison failed. Please try again.") from None
    return ChangeReviewResponse.model_validate(review)


@router.get(
    "/change-radar/reviews",
    response_model=ChangeReviewListResponse,
    dependencies=[Depends(require_administrator)],
    responses=ADMINISTRATOR_ONLY_RESPONSES,
)
def get_change_reviews(db_path: Optional[str | Path] = Depends(get_auth_db_path)) -> ChangeReviewListResponse:
    try:
        reviews = change_radar.list_reviews(db_path)
    except Exception:
        logger.exception("Could not list change reviews.")
        raise HTTPException(status_code=500, detail="Change reviews are temporarily unavailable.") from None
    return ChangeReviewListResponse(reviews=[ChangeReviewResponse.model_validate(review) for review in reviews])


@router.get(
    "/change-radar/reviews/{review_id}",
    response_model=ChangeReviewResponse,
    dependencies=[Depends(require_administrator)],
    responses={**ADMINISTRATOR_ONLY_RESPONSES, 404: {"description": "Change review not found."}},
)
def get_change_review(
    review_id: int,
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> ChangeReviewResponse:
    review = change_radar.get_review(review_id, db_path)
    if review is None:
        raise HTTPException(status_code=404, detail="Change review not found.")
    return ChangeReviewResponse.model_validate(review)


@router.patch(
    "/change-radar/reviews/{review_id}",
    response_model=ChangeReviewResponse,
    dependencies=[Depends(require_administrator)],
    responses={**ADMINISTRATOR_ONLY_RESPONSES, 404: {"description": "Change review not found."}},
)
def update_change_review(
    review_id: int,
    request: ReviewStatusRequest,
    administrator: AuthenticatedUser = Depends(require_administrator),
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> ChangeReviewResponse:
    try:
        review = change_radar.update_review_status(
            review_id,
            status=request.status,
            administrator_id=int(administrator.id),
            db_path=db_path,
        )
    except AuditEventError:
        raise HTTPException(status_code=503, detail="The review action could not be recorded in the audit log.") from None
    except Exception:
        logger.exception("Could not update change review %s.", review_id)
        raise HTTPException(status_code=500, detail="The review status could not be updated.") from None
    if review is None:
        raise HTTPException(status_code=404, detail="Change review not found.")
    return ChangeReviewResponse.model_validate(review)


@router.get(
    "/updates",
    response_model=PublishedUpdatesResponse,
    responses={**UNAUTHENTICATED_RESPONSE, **COHORT_SCOPED_RESPONSES},
)
def get_published_updates(
    user: AuthenticatedUser = Depends(get_current_user),
    db_path: Optional[str | Path] = Depends(get_auth_db_path),
) -> PublishedUpdatesResponse:
    if user.role == "administrator":
        return PublishedUpdatesResponse(updates=[])
    if not user.admission_batch or not user.programme:
        return PublishedUpdatesResponse(updates=[])
    try:
        updates = change_radar.list_published_updates(user.admission_batch, user.programme, db_path)
    except Exception:
        logger.exception("Could not list approved updates for an authenticated cohort.")
        raise HTTPException(status_code=500, detail="Approved updates are temporarily unavailable.") from None
    return PublishedUpdatesResponse(updates=[ChangeReviewResponse.model_validate(item) for item in updates])
