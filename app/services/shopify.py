from collections.abc import Mapping
from datetime import datetime

import httpx

from app.config import Settings
from app.schemas import ShopifyProduct, ShopifyProductsResponse
from pydantic import SecretStr

API_VERSION = "2026-07"


class ShopifyNotConfiguredError(Exception):
    pass


class ShopifyUpstreamError(Exception):
    pass


class ShopifyClient:
    """Minimal read-only Shopify Admin GraphQL client. Never writes to Shopify."""

    def __init__(self, settings: Settings, brand: str) -> None:
        self.brand = brand
        domain, token = settings.shopify_credentials(brand)


        self.store_domain = domain
        self.access_token = token
        if not domain or not token:
            raise ShopifyNotConfiguredError(f"Shopify is not configured for {brand}.")
        self.base_url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": token,
        }

    async def list_products(self, limit: int = 50, page_cursor: str | None = None) -> ShopifyProductsResponse:
        # GraphQL requests use HTTP POST, but this query contains no mutation and is read-only.
        query = """
        query Products($first: Int!, $after: String) {
          products(first: $first, after: $after) {
            nodes { id title handle status updatedAt }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json={"query": query, "variables": {"first": limit, "after": page_cursor}},
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise ShopifyUpstreamError("Unable to read Shopify products.") from error
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:1000]

            print(
                "SHOPIFY UPSTREAM ERROR:",
                error.response.status_code,
                detail,
            )

            raise ShopifyUpstreamError(
                f"Shopify query failed with "
                f"{error.response.status_code}: {detail}"
            ) from error
        payload = response.json()
        if errors := payload.get("errors"):
            raise ShopifyUpstreamError(str(errors))
        products = payload.get("data", {}).get("products")
        if not products:
            raise ShopifyUpstreamError("Shopify returned no product data.")
        return ShopifyProductsResponse(
            brand=self.brand,
            products=[self._to_product(item) for item in products["nodes"]],
            next_page=products["pageInfo"]["endCursor"] if products["pageInfo"]["hasNextPage"] else None,
        )

    def _to_product(self, item: Mapping[str, object]) -> ShopifyProduct:
        updated_at = item.get("updatedAt")
        return ShopifyProduct(
            id=str(item["id"]),
            title=str(item["title"]),
            handle=str(item["handle"]),
            status=str(item["status"]).lower(),
            updated_at=datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")) if updated_at else None,
        )
