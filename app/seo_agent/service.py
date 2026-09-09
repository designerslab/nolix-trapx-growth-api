from __future__ import annotations

import hashlib

from app.content_opportunity_api import ContentOpportunity


def _action_id(item: ContentOpportunity) -> str:
    raw = f"{item.query}|{item.page or ''}|{item.opportunity_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _execution_for(item: ContentOpportunity) -> str:
    if item.opportunity_type in {
        "optimize_existing",
        "build_or_expand_topic",
        "improve_snippet",
        "test_content_improvement",
        "fix_and_strengthen_existing",
    }:
        return "prepare_content_draft_for_human_review"
    return "recommend_only"


def build_action_queue(
    seo_items: list[ContentOpportunity],
    strategic_items: list[ContentOpportunity],
    limit: int,
):
    combined = []

    for item in seo_items:
        combined.append((
            float(item.seo_score) * 0.65
            + float(item.strategic_score) * 0.35,
            item,
        ))

    for item in strategic_items:
        combined.append((
            float(item.strategic_score) * 0.70
            + float(item.seo_score) * 0.30,
            item,
        ))

    combined.sort(key=lambda pair: pair[0], reverse=True)

    selected = []
    seen = set()

    for _, item in combined:
        key = (item.query.lower().strip(), item.page or "")
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= limit:
            break

    return selected
