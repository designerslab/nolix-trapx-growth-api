from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.article_renderer import render_article_markdown
from app.services.content_review_store import get_review_record
from app.services.publishing_gate import evaluate_publish_gate
from app.services.publish_audit_store import (
    get_publish_audit,
    save_publish_audit,
)
from app.services.shopify_publisher import ShopifyPublisher

router = APIRouter()


class PublishDraftRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=200)
    blog_id: str | None = None
    blog_handle: str | None = None


class RepairArticleRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    article_id: str = Field(min_length=1)


def _draft_fields(payload):
    draft = payload.get("draft") or {}

    title = draft.get("title") or payload.get("title")
    body_html = draft.get("body_html")
    body_markdown = draft.get("body_markdown")
    body_fallback = (
        draft.get("body")
        or draft.get("content")
        or payload.get("body_html")
    )
    handle = (
        draft.get("slug")
        or draft.get("handle")
        or payload.get("handle")
    )

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Draft title is missing.")

    if body_html and isinstance(body_html, str):
        body = body_html
    elif body_markdown and isinstance(body_markdown, str):
        body = render_article_markdown(
            body_markdown,
            title=title.strip(),
        )
    elif body_fallback and isinstance(body_fallback, str):
        body = body_fallback
    else:
        raise ValueError("Draft body/content is missing.")

    return (
        title.strip(),
        body,
        str(handle).strip() if handle else None,
    )


async def _blog(pub, blog_id, blog_handle):
    if blog_id:
        return blog_id.strip()

    blogs = await pub.list_blogs()

    if blog_handle:
        matches = [
            blog
            for blog in blogs
            if str(blog.get("handle") or "").lower()
            == blog_handle.strip().lower()
        ]
        if len(matches) == 1:
            return str(matches[0]["id"])
        raise ValueError(
            "Shopify blog handle not uniquely found."
        )

    if len(blogs) == 1:
        return str(blogs[0]["id"])

    raise ValueError(
        "blog_id or blog_handle is required "
        "when multiple Shopify blogs exist."
    )


@router.post(
    "/v1/brands/{brand}/content-reviews/{draft_id}/publish",
    dependencies=[Depends(require_api_key)],
    tags=["content-publishing"],
    operation_id="publish_content_draft",
)
async def publish_content_draft(
    request: PublishDraftRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
    draft_id: str = Path(min_length=1),
):
    settings = get_settings()

    old = get_publish_audit(
        brand=brand,
        idempotency_key=request.idempotency_key,
        settings=settings,
    )
    if old:
        if old.get("draft_id") != draft_id:
            raise HTTPException(
                409,
                "Idempotency key already used for another draft.",
            )
        return {**old, "idempotent_replay": True}

    gate = await evaluate_publish_gate(
        brand=brand,
        draft_id=draft_id,
        settings=settings,
    )
    if not gate.eligible:
        raise HTTPException(
            409,
            {
                "message": "Publishing gate blocked this draft.",
                "blockers": gate.blockers,
                "warnings": gate.warnings,
            },
        )

    record = get_review_record(
        brand=brand,
        draft_id=draft_id,
        settings=settings,
    )
    if not record:
        raise HTTPException(404, "Draft not found.")

    try:
        title, body_html, handle = _draft_fields(
            record.get("draft_payload") or {}
        )
        publisher = ShopifyPublisher(settings, brand)
        blog_id = await _blog(
            publisher,
            request.blog_id,
            request.blog_handle,
        )
        article = await publisher.create_unpublished_article(
            blog_id=blog_id,
            title=title,
            body_html=body_html,
            handle=handle,
            author_name=request.actor,
        )
        audit = save_publish_audit(
            brand=brand,
            idempotency_key=request.idempotency_key,
            draft_id=draft_id,
            actor=request.actor,
            content_hash=gate.current_content_hash or "",
            shopify_article=article,
            settings=settings,
        )
        return {
            **audit,
            "idempotent_replay": False,
            "renderer": "semantic_html_v1",
        }
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post(
    "/v1/brands/{brand}/content-reviews/{draft_id}/repair-shopify-article",
    dependencies=[Depends(require_api_key)],
    tags=["content-publishing"],
    operation_id="repair_shopify_article_formatting",
)
async def repair_shopify_article_formatting(
    request: RepairArticleRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
    draft_id: str = Path(min_length=1),
):
    """Repair an existing test article using the approved stored draft.

    The article remains explicitly unpublished.
    """
    settings = get_settings()

    gate = await evaluate_publish_gate(
        brand=brand,
        draft_id=draft_id,
        settings=settings,
    )
    if not gate.eligible:
        raise HTTPException(
            409,
            {
                "message": "Publishing gate blocked article repair.",
                "blockers": gate.blockers,
                "warnings": gate.warnings,
            },
        )

    record = get_review_record(
        brand=brand,
        draft_id=draft_id,
        settings=settings,
    )
    if not record:
        raise HTTPException(404, "Draft not found.")

    try:
        title, body_html, handle = _draft_fields(
            record.get("draft_payload") or {}
        )
        article = await ShopifyPublisher(
            settings,
            brand,
        ).update_unpublished_article(
            article_id=request.article_id,
            title=title,
            body_html=body_html,
            handle=handle,
            author_name=request.actor,
        )
        return {
            "brand": brand,
            "draft_id": draft_id,
            "article": article,
            "renderer": "semantic_html_v1",
            "repair_executed": True,
            "publicly_published": False,
        }
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
