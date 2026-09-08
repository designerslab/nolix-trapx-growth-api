from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.content_review_store import (
    content_payload_hash,
    get_review_record,
)
from app.services.shopify import (
    ShopifyClient,
    ShopifyNotConfiguredError,
    ShopifyUpstreamError,
)


@dataclass
class PublishGateCheck:
    eligible: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    current_content_hash: str | None = None
    approved_content_hash: str | None = None
    product_truth_rechecked: bool = False
    product_ids_checked: list[str] = field(default_factory=list)
    destination: str = "shopify_blog_article"
    dry_run: bool = True


def _claim_product_ids(
    draft_payload: dict,
) -> list[str]:
    draft = draft_payload.get("draft") or {}
    claims = draft.get("claims") or []

    ids: set[str] = set()

    for claim in claims:
        if claim.get("claim_type") != "product_fact":
            continue

        for value in claim.get("evidence_product_ids") or []:
            text = str(value).strip()
            if text:
                ids.add(text)

    return sorted(ids)


async def evaluate_publish_gate(
    *,
    brand: str,
    draft_id: str,
    settings: Any,
) -> PublishGateCheck:
    record = get_review_record(
        brand=brand,
        draft_id=draft_id,
        settings=settings,
    )

    if record is None:
        return PublishGateCheck(
            eligible=False,
            blockers=["review_record_not_found"],
        )

    blockers: list[str] = []
    warnings: list[str] = []

    if record.get("status") != "approved":
        blockers.append("draft_not_approved")

    draft_payload = record.get("draft_payload") or {}
    current_hash = content_payload_hash(draft_payload)
    approved_hash = record.get("approved_content_hash")

    if not approved_hash:
        blockers.append("missing_approval_content_hash")
    elif current_hash != approved_hash:
        blockers.append("draft_changed_after_approval")

    if draft_payload.get("publish_allowed") is True:
        blockers.append("unsafe_draft_publish_flag")

    unsupported = (
        draft_payload.get("unsupported_claim_warnings")
        or []
    )

    if unsupported:
        blockers.append(
            "unsupported_claim_warnings_present"
        )

    product_ids = _claim_product_ids(draft_payload)
    rechecked = False

    if product_ids:
        try:
            client = ShopifyClient(
                settings,
                brand,
            )

            for product_id in product_ids:
                await client.get_product(product_id)

            rechecked = True

        except ShopifyNotConfiguredError:
            blockers.append(
                "shopify_product_truth_not_configured"
            )

        except ShopifyUpstreamError:
            blockers.append(
                "shopify_product_truth_recheck_failed"
            )
    else:
        warnings.append(
            "no_product_specific_claims_to_recheck"
        )

    return PublishGateCheck(
        eligible=not blockers,
        blockers=blockers,
        warnings=warnings,
        current_content_hash=current_hash,
        approved_content_hash=approved_hash,
        product_truth_rechecked=rechecked,
        product_ids_checked=product_ids,
        destination="shopify_blog_article",
        dry_run=True,
    )
