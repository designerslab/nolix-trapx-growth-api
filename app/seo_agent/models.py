from __future__ import annotations

from pydantic import BaseModel, Field


class SEOAction(BaseModel):
    priority: int
    action_id: str
    query: str
    page: str | None = None
    action_type: str
    action: str
    confidence: str
    seo_score: float
    strategic_score: float
    strategic_intent: str
    evidence: dict = Field(default_factory=dict)
    execution: str
    human_approval_required: bool = True


class SEOActionQueueResponse(BaseModel):
    brand: str
    generated_at: str
    actions: list[SEOAction] = Field(default_factory=list)
    source_status: dict[str, str] = Field(default_factory=dict)


class PrepareSEOActionRequest(BaseModel):
    query: str
    page: str | None = None
    action_type: str
    strategic_intent: str | None = None
    product_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class PrepareSEOActionResponse(BaseModel):
    brand: str
    action: str
    draft_id: str
    review_status: str
    publish_allowed: bool
    draft_payload: dict
