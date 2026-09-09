from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.config import get_settings
from app.security import require_api_key
from app.content_opportunity_api import get_content_opportunities
from app.content_draft_api import (
    ContentDraftRequest,
    generate_content_draft,
)
from app.services.content_review_store import create_review_record
from app.seo_agent.models import (
    SEOAction,
    SEOActionQueueResponse,
    PrepareSEOActionRequest,
    PrepareSEOActionResponse,
)
from app.seo_agent.service import (
    _action_id,
    _execution_for,
    build_action_queue,
)

router = APIRouter()


@router.get(
    "/v1/agents/seo/{brand}/action-queue",
    response_model=SEOActionQueueResponse,
    dependencies=[Depends(require_api_key)],
    tags=["seo-agent"],
    operation_id="get_seo_agent_action_queue",
)
async def get_seo_agent_action_queue(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    current_start_date: date | None = Query(default=None),
    current_end_date: date | None = Query(default=None),
    previous_start_date: date | None = Query(default=None),
    previous_end_date: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=25),
    min_impressions: float = Query(default=1, ge=0),
    max_pages: int = Query(default=25, ge=1, le=50),
) -> SEOActionQueueResponse:
    data = await get_content_opportunities(
        brand=brand,
        current_start_date=current_start_date,
        current_end_date=current_end_date,
        previous_start_date=previous_start_date,
        previous_end_date=previous_end_date,
        limit=max(limit, 10),
        min_impressions=min_impressions,
        max_pages=max_pages,
    )

    selected = build_action_queue(
        data.seo_opportunities,
        data.strategic_opportunities,
        limit,
    )

    actions = []

    for priority, item in enumerate(selected, start=1):
        actions.append(
            SEOAction(
                priority=priority,
                action_id=_action_id(item),
                query=item.query,
                page=item.page,
                action_type=item.opportunity_type,
                action=item.action,
                confidence=item.confidence,
                seo_score=item.seo_score,
                strategic_score=item.strategic_score,
                strategic_intent=item.strategic_intent,
                evidence={
                    "search": item.search_evidence,
                    "engagement": item.engagement_evidence,
                    "geo": item.geo_evidence,
                    "technical": item.technical_evidence,
                    "product_truth": item.product_truth,
                    "why": item.why,
                },
                execution=_execution_for(item),
                human_approval_required=True,
            )
        )

    return SEOActionQueueResponse(
        brand=brand,
        generated_at=data.generated_at,
        actions=actions,
        source_status=data.source_status,
    )


@router.post(
    "/v1/agents/seo/{brand}/prepare-action",
    response_model=PrepareSEOActionResponse,
    dependencies=[Depends(require_api_key)],
    tags=["seo-agent"],
    operation_id="prepare_seo_agent_action",
)
async def prepare_seo_agent_action(
    request: PrepareSEOActionRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
) -> PrepareSEOActionResponse:
    allowed = {
        "optimize_existing",
        "build_or_expand_topic",
        "improve_snippet",
        "test_content_improvement",
        "fix_and_strengthen_existing",
    }

    if request.action_type not in allowed:
        raise HTTPException(
            status_code=422,
            detail="This SEO action type is recommendation-only in V1.",
        )

    draft_request = ContentDraftRequest(
        target_query=request.query,
        target_page=request.page,
        strategic_intent=request.strategic_intent,
        opportunity_kind="seo",
        product_ids=request.product_ids,
        content_type="article",
        notes=(
            request.notes
            or (
                "Prepared automatically by SEO Agent V1. "
                "Human approval is required before any external write."
            )
        ),
    )

    draft = await generate_content_draft(
        request=draft_request,
        brand=brand,
    )

    record = create_review_record(
        brand=brand,
        draft_payload=draft.model_dump(mode="json"),
        reviewer_hint="SEO Agent V1 prepared this action for human review.",
        settings=get_settings(),
    )

    return PrepareSEOActionResponse(
        brand=brand,
        action=request.action_type,
        draft_id=record["draft_id"],
        review_status=record["status"],
        publish_allowed=False,
        draft_payload=draft.model_dump(mode="json"),
    )
