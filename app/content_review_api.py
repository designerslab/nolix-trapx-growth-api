from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.content_review_store import (
    create_review_record,
    get_review_record,
    list_review_records,
    update_review_record,
)

router = APIRouter()


class SubmitDraftForReviewRequest(BaseModel):
    draft_payload: dict
    reviewer_hint: str | None = Field(default=None, max_length=300)


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approved", "needs_changes", "rejected"]
    reviewer: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)


class ContentReviewRecord(BaseModel):
    draft_id: str
    brand: str
    status: str
    reviewer_hint: str | None = None
    reviewer: str | None = None
    review_notes: str | None = None
    created_at: str
    updated_at: str
    reviewed_at: str | None = None
    publish_allowed: bool = False
    draft_payload: dict


class ContentReviewListResponse(BaseModel):
    brand: str
    reviews: list[ContentReviewRecord] = Field(default_factory=list)


@router.post(
    "/v1/brands/{brand}/content-reviews",
    response_model=ContentReviewRecord,
    dependencies=[Depends(require_api_key)],
    tags=["content-reviews"],
    operation_id="submit_content_draft_for_review",
)
async def submit_content_draft_for_review(
    request: SubmitDraftForReviewRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
) -> ContentReviewRecord:
    payload_brand = request.draft_payload.get("brand")

    if payload_brand and payload_brand != brand:
        raise HTTPException(
            status_code=422,
            detail="draft_payload brand does not match the URL brand",
        )

    if request.draft_payload.get("publish_allowed") is True:
        raise HTTPException(
            status_code=422,
            detail="Draft payload must not already allow publishing.",
        )

    try:
        record = create_review_record(
            brand=brand,
            draft_payload=request.draft_payload,
            reviewer_hint=request.reviewer_hint,
            settings=get_settings(),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to store content draft for review: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error

    return ContentReviewRecord.model_validate(record)


@router.get(
    "/v1/brands/{brand}/content-reviews",
    response_model=ContentReviewListResponse,
    dependencies=[Depends(require_api_key)],
    tags=["content-reviews"],
    operation_id="list_content_reviews",
)
async def list_content_reviews(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=20, ge=1, le=100),
) -> ContentReviewListResponse:
    try:
        records = list_review_records(
            brand=brand,
            limit=limit,
            settings=get_settings(),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to list content reviews: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error

    return ContentReviewListResponse(
        brand=brand,
        reviews=[
            ContentReviewRecord.model_validate(item)
            for item in records
        ],
    )


@router.get(
    "/v1/brands/{brand}/content-reviews/{draft_id}",
    response_model=ContentReviewRecord,
    dependencies=[Depends(require_api_key)],
    tags=["content-reviews"],
    operation_id="get_content_review",
)
async def get_content_review(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    draft_id: str = Path(min_length=8, max_length=64),
) -> ContentReviewRecord:
    try:
        record = get_review_record(
            brand=brand,
            draft_id=draft_id,
            settings=get_settings(),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to read content review: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Content review not found.",
        )

    return ContentReviewRecord.model_validate(record)


@router.post(
    "/v1/brands/{brand}/content-reviews/{draft_id}/decision",
    response_model=ContentReviewRecord,
    dependencies=[Depends(require_api_key)],
    tags=["content-reviews"],
    operation_id="review_content_draft",
)
async def review_content_draft(
    request: ReviewDecisionRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
    draft_id: str = Path(min_length=8, max_length=64),
) -> ContentReviewRecord:
    try:
        record = update_review_record(
            brand=brand,
            draft_id=draft_id,
            decision=request.decision,
            reviewer=request.reviewer,
            notes=request.notes,
            settings=get_settings(),
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail="Content review not found.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to update content review: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error

    return ContentReviewRecord.model_validate(record)
