from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.publishing_gate import (
    evaluate_publish_gate,
)

router = APIRouter()


class PublishingGatePreviewResponse(BaseModel):
    brand: str
    draft_id: str
    eligible: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    current_content_hash: str | None = None
    approved_content_hash: str | None = None
    product_truth_rechecked: bool = False
    product_ids_checked: list[str] = Field(
        default_factory=list
    )
    destination: str
    dry_run: bool = True
    publish_executed: bool = False
    publish_allowed: bool = False


@router.post(
    "/v1/brands/{brand}/content-publishing-gates/{draft_id}/preview",
    response_model=PublishingGatePreviewResponse,
    dependencies=[Depends(require_api_key)],
    tags=["content-publishing-gate"],
    operation_id="preview_content_publish_gate",
)
async def preview_content_publish_gate(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    draft_id: str = Path(
        min_length=8,
        max_length=64,
    ),
) -> PublishingGatePreviewResponse:
    try:
        result = await evaluate_publish_gate(
            brand=brand,
            draft_id=draft_id,
            settings=get_settings(),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to evaluate publishing gate: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error

    return PublishingGatePreviewResponse(
        brand=brand,
        draft_id=draft_id,
        eligible=result.eligible,
        blockers=result.blockers,
        warnings=result.warnings,
        current_content_hash=(
            result.current_content_hash
        ),
        approved_content_hash=(
            result.approved_content_hash
        ),
        product_truth_rechecked=(
            result.product_truth_rechecked
        ),
        product_ids_checked=(
            result.product_ids_checked
        ),
        destination=result.destination,
        dry_run=True,
        publish_executed=False,
        publish_allowed=False,
    )
