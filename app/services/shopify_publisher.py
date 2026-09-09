from typing import Any
import httpx
from app.services.shopify import ShopifyNotConfiguredError, ShopifyUpstreamError
API_VERSION="2026-07"
class ShopifyPublisher:
    """Narrow writer: creates UNPUBLISHED Shopify blog articles only."""
    def __init__(self,settings:Any,brand:str):
        domain,token=settings.shopify_credentials(brand)
        if not domain or not token: raise ShopifyNotConfiguredError(f"Shopify is not configured for {brand}.")
        self.url=f"https://{domain}/admin/api/{API_VERSION}/graphql.json"; self.token=token
    async def _graphql(self,query,variables=None):
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r=await c.post(self.url,headers={"Content-Type":"application/json","X-Shopify-Access-Token":self.token},json={"query":query,"variables":variables or {}})
                r.raise_for_status()
        except httpx.HTTPError as e: raise ShopifyUpstreamError("Unable to write Shopify content.") from e
        p=r.json()
        if p.get("errors"): raise ShopifyUpstreamError(f"Shopify GraphQL errors: {p['errors']}")
        return p["data"]
    async def list_blogs(self):
        d=await self._graphql("query { blogs(first:20){ nodes { id title handle } } }")
        return d.get("blogs",{}).get("nodes",[])
    async def create_unpublished_article(self,*,blog_id,title,body_html,handle=None,author_name=None):
        q="""mutation ArticleCreate($article: ArticleCreateInput!){articleCreate(article:$article){article{id title handle isPublished} userErrors{field message}}}"""
        a={"blogId":blog_id,"title":title,"body":body_html,"isPublished":False}
        if handle:a["handle"]=handle
        if author_name:a["author"]={"name":author_name}
        x=(await self._graphql(q,{"article":a})).get("articleCreate") or {}
        if x.get("userErrors"): raise ShopifyUpstreamError(f"Shopify articleCreate errors: {x['userErrors']}")
        article=x.get("article")
        if not article or article.get("isPublished") is True: raise ShopifyUpstreamError("Shopify article safety check failed.")
        return article
