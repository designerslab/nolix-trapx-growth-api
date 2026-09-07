from __future__ import annotations

import json
import re
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.shopify import (
    ShopifyClient,
    ShopifyNotConfiguredError,
    ShopifyUpstreamError,
)

router = APIRouter()


class ContentDraftRequest(BaseModel):
    target_query: str = Field(min_length=2, max_length=300)
    target_page: str | None = None
    strategic_intent: str | None = None
    opportunity_kind: Literal["seo", "strategic", "manual"] = "manual"
    product_ids: list[str] = Field(default_factory=list, max_length=10)
    content_type: Literal["article", "landing_page"] = "article"
    notes: str | None = Field(default=None, max_length=4000)


class ProductTruthItem(BaseModel):
    product_id: str
    title: str
    handle: str
    status: str
    vendor: str | None = None
    product_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    online_store_url: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    total_inventory: int | None = None


class DraftClaim(BaseModel):
    claim: str
    claim_type: Literal["product_fact", "general_guidance", "editorial"]
    evidence_product_ids: list[str] = Field(default_factory=list)


class ContentDraftArtifact(BaseModel):
    title: str
    meta_title: str
    meta_description: str
    slug_suggestion: str
    outline: list[str] = Field(default_factory=list)
    body_markdown: str
    claims: list[DraftClaim] = Field(default_factory=list)


class ContentDraftResponse(BaseModel):
    brand: str
    target_query: str
    target_page: str | None = None
    strategic_intent: str | None = None
    opportunity_kind: str
    content_type: str
    model: str
    draft: ContentDraftArtifact
    product_truth: list[ProductTruthItem] = Field(default_factory=list)
    unsupported_claim_warnings: list[str] = Field(default_factory=list)
    approval_status: str = "requires_human_approval"
    publish_allowed: bool = False
    source: str = "openai_product_truth_grounded_draft_v1"


def _setting(name: str) -> str | None:
    settings = get_settings()
    value = getattr(settings, name, None)
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    text = str(value).strip()
    return text or None


def _model() -> str:
    return (
        _setting("openai_content_generation_model")
        or _setting("openai_llm_visibility_model")
        or "gpt-5.6-luna"
    )


def _numeric_product_id(product_id: str) -> str:
    value = str(product_id).strip()
    if value.startswith("gid://shopify/Product/"):
        return value.rsplit("/", 1)[-1]
    return value


async def _load_product_truth(
    brand: str,
    product_ids: list[str],
) -> list[ProductTruthItem]:
    if not product_ids:
        return []

    client = ShopifyClient(get_settings(), brand)
    truth: list[ProductTruthItem] = []
    seen = set()

    for raw_id in product_ids:
        product_id = _numeric_product_id(raw_id)
        if product_id in seen:
            continue
        seen.add(product_id)

        response = await client.get_product(product_id)
        item = response.product

        truth.append(
            ProductTruthItem(
                product_id=item.numeric_id,
                title=item.title,
                handle=item.handle,
                status=item.status,
                vendor=item.vendor,
                product_type=item.product_type,
                tags=item.tags,
                description=item.description,
                online_store_url=item.online_store_url,
                seo_title=item.seo_title,
                seo_description=item.seo_description,
                total_inventory=item.total_inventory,
            )
        )

    return truth


def _system_rules() -> str:
    return (
        "Create evidence-grounded marketing content drafts for human review. "
        "Never invent product capabilities, performance, ROI, certifications, "
        "deployment scale, customer results, installed base, compatibility, "
        "pricing, warranties, support coverage, or suitability. Product-specific "
        "factual claims may use only supplied PRODUCT_TRUTH. If PRODUCT_TRUTH is "
        "empty, do not make product-specific factual claims. Do not fabricate "
        "customers, case studies, testimonials, research, statistics, citations, "
        "or source URLs. The draft is never approved for publishing automatically. "
        "Use plain ASCII characters where practical to avoid encoding artifacts."
        "Return JSON only."
    )


def _generation_prompt(
    brand: str,
    request: ContentDraftRequest,
    product_truth: list[ProductTruthItem],
) -> str:
    truth_json = json.dumps(
        [item.model_dump() for item in product_truth],
        ensure_ascii=False,
        indent=2,
    )

    return f'''
BRAND: {brand}
CONTENT TYPE: {request.content_type}
TARGET QUERY: {request.target_query}
TARGET PAGE: {request.target_page or "none supplied"}
STRATEGIC INTENT: {request.strategic_intent or "not supplied"}
OPPORTUNITY KIND: {request.opportunity_kind}
EDITOR NOTES: {request.notes or "none"}

PRODUCT_TRUTH:
{truth_json}

Return exactly one JSON object:
{{
  "title": "string",
  "meta_title": "string",
  "meta_description": "string",
  "slug_suggestion": "string",
  "outline": ["string"],
  "body_markdown": "string",
  "claims": [
    {{
      "claim": "string",
      "claim_type": "product_fact|general_guidance|editorial",
      "evidence_product_ids": ["numeric Shopify product id"]
    }}
  ]
}}

Every product_fact must cite at least one supplied product_id.
If PRODUCT_TRUTH is empty, use only general_guidance or editorial claims.
Do not claim the opportunity itself proves commercial demand.
'''.strip()


def _extract_json_text(data: dict) -> str:
    parts: list[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") != "output_text":
                continue
            text = part.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


async def _generate_draft(
    brand: str,
    request: ContentDraftRequest,
    product_truth: list[ProductTruthItem],
) -> ContentDraftArtifact:
    api_key = _setting("openai_api_key")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured.",
        )

    payload = {
        "model": _model(),
        "input": [
            {"role": "system", "content": _system_rules()},
            {
                "role": "user",
                "content": _generation_prompt(
                    brand,
                    request,
                    product_truth,
                ),
            },
        ],
        "max_output_tokens": 5000,
    }

    try:
        async with httpx.AsyncClient(
            timeout=180.0,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenAI API returned {response.status_code}: "
                f"{response.text[:1000]}"
            )

        raw_text = _extract_json_text(response.json())
        if not raw_text:
            raise RuntimeError("OpenAI returned no draft text.")

        parsed = json.loads(_strip_code_fence(raw_text))
        return ContentDraftArtifact.model_validate(parsed)

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to generate content draft: "
                f"{type(error).__name__}: {error}"
            ),
        ) from error
def _contains_positive_risky_claim(
    text: str,
    pattern: str,
) -> bool:
    for sentence in re.split(
        r"(?<=[.!?])\s+",
        text,
    ):
        if not re.search(
            pattern,
            sentence,
            flags=re.IGNORECASE,
        ):
            continue

        normalized = sentence.lower()

        negating_phrases = {
            "do not",
            "does not",
            "should not",
            "cannot",
            "can't",
            "without",
            "no guarantee",
            "not guaranteed",
            "unsupported guarantee",
            "unsupported guarantees",
        }

        if any(
            phrase in normalized
            for phrase in negating_phrases
        ):
            continue

        return True

    return False

def _unsupported_claim_warnings(
    draft: ContentDraftArtifact,
    product_truth: list[ProductTruthItem],
) -> list[str]:
    warnings: list[str] = []
    valid_ids = {item.product_id for item in product_truth}

    for index, claim in enumerate(draft.claims, start=1):
        if claim.claim_type != "product_fact":
            continue

        if not claim.evidence_product_ids:
            warnings.append(
                f"Claim {index} is a product_fact without Product Truth evidence."
            )
            continue

        unknown_ids = [
            item
            for item in claim.evidence_product_ids
            if _numeric_product_id(item) not in valid_ids
        ]
        if unknown_ids:
            warnings.append(
                f"Claim {index} references unknown Product Truth IDs: "
                + ", ".join(unknown_ids)
            )

    if not product_truth and any(
        item.claim_type == "product_fact"
        for item in draft.claims
    ):
        warnings.append(
            "Product-specific claims were generated without supplied Product Truth."
        )

    risky_patterns = {
        "guarantee": r"\bguarantee(?:d|s)?\b",
        "roi": r"\bROI\b|return on investment",
        "certification": r"\bcertif(?:ied|ication|ications)\b",
        "customer proof": r"\bcustomer(?:s)? (?:report|reported|achieved|saw)\b",
        "deployment scale": r"\b(?:thousands|millions) of (?:devices|deployments|sites)\b",
    }

    for label, pattern in risky_patterns.items():
        if _contains_positive_risky_claim(
            draft.body_markdown,
            pattern,
        ):
            warnings.append(
                "Draft contains a potentially unsupported "
                f"{label} statement; human verification required."
            )

    return list(dict.fromkeys(warnings))


@router.post(
    "/v1/brands/{brand}/content-drafts",
    response_model=ContentDraftResponse,
    dependencies=[Depends(require_api_key)],
    tags=["content-drafts"],
    operation_id="generate_content_draft",
)
async def generate_content_draft(
    request: ContentDraftRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
) -> ContentDraftResponse:
    try:
        product_truth = await _load_product_truth(
            brand,
            request.product_ids,
        )
    except ShopifyNotConfiguredError as error:
        if request.product_ids:
            raise HTTPException(
                status_code=503,
                detail=str(error),
            ) from error
        product_truth = []
    except ShopifyUpstreamError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

    draft = await _generate_draft(
        brand,
        request,
        product_truth,
    )

    warnings = _unsupported_claim_warnings(
        draft,
        product_truth,
    )

    return ContentDraftResponse(
        brand=brand,
        target_query=request.target_query,
        target_page=request.target_page,
        strategic_intent=request.strategic_intent,
        opportunity_kind=request.opportunity_kind,
        content_type=request.content_type,
        model=_model(),
        draft=draft,
        product_truth=product_truth,
        unsupported_claim_warnings=warnings,
        approval_status="requires_human_approval",
        publish_allowed=False,
    )
