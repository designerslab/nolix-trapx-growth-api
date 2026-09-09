from fastapi import APIRouter,Depends,HTTPException,Path
from pydantic import BaseModel,Field
from app.config import get_settings
from app.security import require_api_key
from app.services.content_review_store import get_review_record
from app.services.publishing_gate import evaluate_publish_gate
from app.services.publish_audit_store import get_publish_audit,save_publish_audit
from app.services.shopify_publisher import ShopifyPublisher
router=APIRouter()
class PublishDraftRequest(BaseModel):
    actor:str=Field(min_length=1,max_length=200)
    idempotency_key:str=Field(min_length=8,max_length=200)
    blog_id:str|None=None
    blog_handle:str|None=None
def _draft_fields(p):
    d=p.get("draft") or {}; title=d.get("title") or p.get("title");body=(
    d.get("body_html")
    or d.get("body_markdown")
    or d.get("body")
    or d.get("content")
    or p.get("body_html")
); handle=d.get("slug") or d.get("handle") or p.get("handle")
    if not isinstance(title,str) or not title.strip(): raise ValueError("Draft title is missing.")
    if not isinstance(body,str) or not body.strip(): raise ValueError("Draft body/content is missing.")
    return title.strip(),body,str(handle).strip() if handle else None
async def _blog(pub,blog_id,blog_handle):
    if blog_id:return blog_id.strip()
    blogs=await pub.list_blogs()
    if blog_handle:
        m=[b for b in blogs if str(b.get("handle") or "").lower()==blog_handle.strip().lower()]
        if len(m)==1:return str(m[0]["id"])
        raise ValueError("Shopify blog handle not uniquely found.")
    if len(blogs)==1:return str(blogs[0]["id"])
    raise ValueError("blog_id or blog_handle is required when multiple Shopify blogs exist.")
@router.post("/v1/brands/{brand}/content-reviews/{draft_id}/publish",dependencies=[Depends(require_api_key)],tags=["content-publishing"],operation_id="publish_content_draft")
async def publish_content_draft(request:PublishDraftRequest,brand:str=Path(pattern="^(nolix|trapx)$"),draft_id:str=Path(min_length=1)):
    s=get_settings(); old=get_publish_audit(brand=brand,idempotency_key=request.idempotency_key,settings=s)
    if old:
        if old.get("draft_id")!=draft_id: raise HTTPException(409,"Idempotency key already used for another draft.")
        return {**old,"idempotent_replay":True}
    gate=await evaluate_publish_gate(brand=brand,draft_id=draft_id,settings=s)
    if not gate.eligible: raise HTTPException(409,{"message":"Publishing gate blocked this draft.","blockers":gate.blockers,"warnings":gate.warnings})
    rec=get_review_record(brand=brand,draft_id=draft_id,settings=s)
    if not rec: raise HTTPException(404,"Draft not found.")
    try:
        title,body,handle=_draft_fields(rec.get("draft_payload") or {}); pub=ShopifyPublisher(s,brand); bid=await _blog(pub,request.blog_id,request.blog_handle)
        article=await pub.create_unpublished_article(blog_id=bid,title=title,body_html=body,handle=handle,author_name=request.actor)
        audit=save_publish_audit(brand=brand,idempotency_key=request.idempotency_key,draft_id=draft_id,actor=request.actor,content_hash=gate.current_content_hash or "",shopify_article=article,settings=s)
        return {**audit,"idempotent_replay":False}
    except ValueError as e: raise HTTPException(422,str(e)) from e
