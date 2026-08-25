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
    @staticmethod
    def _product_gid(product_id: str) -> str:
        product_id = product_id.strip()

        if product_id.startswith(
            "gid://shopify/Product/"
        ):
            return product_id

        if not product_id.isdigit():
            raise ValueError(
                "product_id must be a numeric Shopify product ID"
            )

        return f"gid://shopify/Product/{product_id}"

    async def get_product_variants(
        self,
        product_id: str,
        limit: int = 100,
    ):
        from app.schemas import (
            ShopifySelectedOption,
            ShopifyVariantRow,
            ShopifyVariantsResponse,
        )

        gid = self._product_gid(product_id)

        query = """
        query ProductVariants(
        $id: ID!,
        $first: Int!
        ) {
        product(id: $id) {
            id
            variants(first: $first) {
            nodes {
                id
                title
                sku
                barcode
                price
                compareAtPrice
                inventoryQuantity
                selectedOptions {
                name
                value
                }
            }
            }
        }
        }
        """

        data = await self._graphql(
            query,
            {
                "id": gid,
                "first": limit,
            },
        )

        product = data.get("product")

        if not product:
            raise ShopifyUpstreamError(
                f"Shopify product not found: {product_id}"
            )

        variants = []

        for variant in (
            product.get("variants", {})
            .get("nodes", [])
        ):
            variants.append(
                ShopifyVariantRow(
                    id=variant["id"],
                    numeric_id=(
                        variant["id"]
                        .rsplit("/", 1)[-1]
                    ),
                    title=variant["title"],
                    sku=variant.get("sku"),
                    barcode=variant.get(
                        "barcode"
                    ),
                    price=variant.get("price"),
                    compare_at_price=variant.get(
                        "compareAtPrice"
                    ),
                    inventory_quantity=variant.get(
                        "inventoryQuantity"
                    ),
                    selected_options=[
                        ShopifySelectedOption(
                            name=option["name"],
                            value=option["value"],
                        )
                        for option in (
                            variant.get(
                                "selectedOptions"
                            )
                            or []
                        )
                    ],
                )
            )

        return ShopifyVariantsResponse(
            brand=self.brand,
            product_id=product["id"],
            variants=variants,
        )

    async def get_product(
        self,
        product_id: str,
    ):
        from app.schemas import (
            ShopifyProductDetail,
            ShopifyProductDetailResponse,
        )

        gid = self._product_gid(product_id)

        query = """
        query ProductDetail($id: ID!) {
        product(id: $id) {
            id
            title
            handle
            status
            vendor
            productType
            tags
            description
            descriptionHtml
            onlineStoreUrl
            seo {
            title
            description
            }
            publishedAt
            createdAt
            updatedAt
            totalInventory
        }
        }
        """

        data = await self._graphql(
            query,
            {"id": gid},
        )

        product = data.get("product")

        if not product:
            raise ShopifyUpstreamError(
                f"Shopify product not found: {product_id}"
            )

        numeric_id = product["id"].rsplit("/", 1)[-1]

        seo = product.get("seo") or {}

        return ShopifyProductDetailResponse(
            brand=self.brand,
            product=ShopifyProductDetail(
                id=product["id"],
                numeric_id=numeric_id,
                title=product["title"],
                handle=product["handle"],
                status=product["status"],
                vendor=product.get("vendor"),
                product_type=product.get(
                    "productType"
                ),
                tags=product.get("tags") or [],
                description=product.get(
                    "description"
                ),
                description_html=product.get(
                    "descriptionHtml"
                ),
                online_store_url=product.get(
                    "onlineStoreUrl"
                ),
                seo_title=seo.get("title"),
                seo_description=seo.get(
                    "description"
                ),
                published_at=product.get(
                    "publishedAt"
                ),
                created_at=product.get(
                    "createdAt"
                ),
                updated_at=product.get(
                    "updatedAt"
                ),
                total_inventory=product.get(
                    "totalInventory"
                ),
            ),
        )

    async def _graphql(
        self,
        query: str,
        variables: dict | None = None,
    ) -> dict:
        headers = {
            "X-Shopify-Access-Token": (
                self.access_token
            ),
            "Content-Type": "application/json",
        }

        url = (
            f"https://{self.store_domain}"
            f"/admin/api/2026-07/graphql.json"
        )

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "query": query,
                        "variables": variables or {},
                    },
                )

                response.raise_for_status()

        except httpx.HTTPStatusError as error:
            detail = error.response.text[:1000]

            raise ShopifyUpstreamError(
                f"Shopify returned "
                f"{error.response.status_code}: {detail}"
            ) from error

        except httpx.HTTPError as error:
            raise ShopifyUpstreamError(
                f"Unable to reach Shopify: {error}"
            ) from error

        payload = response.json()

        if payload.get("errors"):
            raise ShopifyUpstreamError(
                f"Shopify GraphQL errors: "
                f"{payload['errors']}"
            )

        return payload["data"]
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
