from typing import Any

import httpx

from app.services.shopify import (
    ShopifyNotConfiguredError,
    ShopifyUpstreamError,
)

API_VERSION = "2026-07"


class ShopifyPublisher:
    """Narrow writer for unpublished Shopify blog articles only."""

    def __init__(self, settings: Any, brand: str):
        domain, token = settings.shopify_credentials(brand)
        if not domain or not token:
            raise ShopifyNotConfiguredError(
                f"Shopify is not configured for {brand}."
            )
        self.url = (
            f"https://{domain}/admin/api/"
            f"{API_VERSION}/graphql.json"
        )
        self.token = token

    async def _graphql(self, query, variables=None):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.url,
                    headers={
                        "Content-Type": "application/json",
                        "X-Shopify-Access-Token": self.token,
                    },
                    json={
                        "query": query,
                        "variables": variables or {},
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise ShopifyUpstreamError(
                "Unable to write Shopify content."
            ) from error

        payload = response.json()
        if payload.get("errors"):
            raise ShopifyUpstreamError(
                f"Shopify GraphQL errors: {payload['errors']}"
            )
        return payload["data"]

    async def list_blogs(self):
        data = await self._graphql(
            "query { blogs(first:20){ nodes { id title handle } } }"
        )
        return data.get("blogs", {}).get("nodes", [])

    async def create_unpublished_article(
        self,
        *,
        blog_id,
        title,
        body_html,
        handle=None,
        author_name=None,
    ):
        mutation = """
        mutation ArticleCreate($article: ArticleCreateInput!) {
          articleCreate(article: $article) {
            article { id title handle isPublished }
            userErrors { field message }
          }
        }
        """
        article_input = {
            "blogId": blog_id,
            "title": title,
            "body": body_html,
            "isPublished": False,
        }
        if handle:
            article_input["handle"] = handle
        if author_name:
            article_input["author"] = {"name": author_name}

        result = (
            await self._graphql(
                mutation,
                {"article": article_input},
            )
        ).get("articleCreate") or {}

        if result.get("userErrors"):
            raise ShopifyUpstreamError(
                f"Shopify articleCreate errors: {result['userErrors']}"
            )

        article = result.get("article")
        if not article or article.get("isPublished") is True:
            raise ShopifyUpstreamError(
                "Shopify article safety check failed."
            )
        return article

    async def update_unpublished_article(
        self,
        *,
        article_id: str,
        title: str,
        body_html: str,
        handle: str | None = None,
        author_name: str | None = None,
    ):
        mutation = """
        mutation UpdateArticle(
          $id: ID!,
          $article: ArticleUpdateInput!
        ) {
          articleUpdate(id: $id, article: $article) {
            article { id title handle isPublished }
            userErrors { field message }
          }
        }
        """
        article_input = {
            "title": title,
            "body": body_html,
            "isPublished": False,
        }
        if handle:
            article_input["handle"] = handle
        if author_name:
            article_input["author"] = {"name": author_name}

        result = (
            await self._graphql(
                mutation,
                {
                    "id": article_id,
                    "article": article_input,
                },
            )
        ).get("articleUpdate") or {}

        if result.get("userErrors"):
            raise ShopifyUpstreamError(
                f"Shopify articleUpdate errors: {result['userErrors']}"
            )

        article = result.get("article")
        if not article or article.get("isPublished") is True:
            raise ShopifyUpstreamError(
                "Shopify repair safety check failed."
            )
        return article
