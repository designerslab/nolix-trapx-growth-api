from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.shopify import ShopifyClient, ShopifyNotConfiguredError, ShopifyUpstreamError

router = APIRouter()


class ProductCatalogPriceRange(BaseModel):
    min_price: str | None = None
    max_price: str | None = None
    currency: str | None = None


class ProductCatalogRow(BaseModel):
    id: str
    numeric_id: str
    title: str
    handle: str
    status: str
    vendor: str | None = None
    product_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    online_store_url: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    total_inventory: int | None = None
    tracks_inventory: bool | None = None
    variant_count: int | None = None
    has_only_default_variant: bool | None = None
    price: ProductCatalogPriceRange
    published_at: str | None = None
    updated_at: str | None = None


class ProductCatalogResponse(BaseModel):
    brand: str
    products: list[ProductCatalogRow] = Field(default_factory=list)
    next_page: str | None = None
    source: str = "shopify"


class ProductAuditIssue(BaseModel):
    product_id: str
    title: str
    severity: str
    code: str
    message: str


class ProductAuditSummary(BaseModel):
    products_checked: int
    active_products: int
    draft_products: int
    issues_total: int
    high_issues: int
    medium_issues: int
    low_issues: int


class ProductAuditResponse(BaseModel):
    brand: str
    summary: ProductAuditSummary
    issues: list[ProductAuditIssue] = Field(default_factory=list)
    source: str = "shopify"


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _numeric_id(gid: str) -> str:
    return gid.rsplit("/", 1)[-1]


def _price_range(item: dict) -> ProductCatalogPriceRange:
    price_range = item.get("priceRangeV2") or {}
    min_price = price_range.get("minVariantPrice") or {}
    max_price = price_range.get("maxVariantPrice") or {}

    return ProductCatalogPriceRange(
        min_price=_clean_optional(min_price.get("amount")),
        max_price=_clean_optional(max_price.get("amount")),
        currency=_clean_optional(
            min_price.get("currencyCode") or max_price.get("currencyCode")
        ),
    )


def _to_catalog_row(item: dict) -> ProductCatalogRow:
    seo = item.get("seo") or {}
    variant_count = item.get("variantsCount") or {}

    return ProductCatalogRow(
        id=item["id"],
        numeric_id=_numeric_id(item["id"]),
        title=item["title"],
        handle=item["handle"],
        status=str(item["status"]).lower(),
        vendor=_clean_optional(item.get("vendor")),
        product_type=_clean_optional(item.get("productType")),
        tags=item.get("tags") or [],
        online_store_url=_clean_optional(item.get("onlineStoreUrl")),
        seo_title=_clean_optional(seo.get("title")),
        seo_description=_clean_optional(seo.get("description")),
        total_inventory=item.get("totalInventory"),
        tracks_inventory=item.get("tracksInventory"),
        variant_count=variant_count.get("count"),
        has_only_default_variant=item.get("hasOnlyDefaultVariant"),
        price=_price_range(item),
        published_at=_clean_optional(item.get("publishedAt")),
        updated_at=_clean_optional(item.get("updatedAt")),
    )


async def _read_enriched_products(
    brand: str,
    limit: int,
    page_cursor: str | None,
) -> ProductCatalogResponse:
    client = ShopifyClient(get_settings(), brand)

    query = """
    query EnrichedProducts($first: Int!, $after: String) {
      products(first: $first, after: $after) {
        nodes {
          id
          title
          handle
          status
          vendor
          productType
          tags
          onlineStoreUrl
          seo { title description }
          totalInventory
          tracksInventory
          variantsCount { count }
          hasOnlyDefaultVariant
          priceRangeV2 {
            minVariantPrice { amount currencyCode }
            maxVariantPrice { amount currencyCode }
          }
          publishedAt
          updatedAt
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """

    data = await client._graphql(
        query,
        {"first": limit, "after": page_cursor},
    )

    products = data.get("products") or {}
    nodes = products.get("nodes") or []
    page_info = products.get("pageInfo") or {}

    return ProductCatalogResponse(
        brand=brand,
        products=[_to_catalog_row(item) for item in nodes],
        next_page=(
            page_info.get("endCursor")
            if page_info.get("hasNextPage")
            else None
        ),
    )


def _audit_product(product: ProductCatalogRow) -> list[ProductAuditIssue]:
    issues: list[ProductAuditIssue] = []

    def add(severity: str, code: str, message: str) -> None:
        issues.append(
            ProductAuditIssue(
                product_id=product.numeric_id,
                title=product.title,
                severity=severity,
                code=code,
                message=message,
            )
        )

    if not product.vendor:
        add("medium", "missing_vendor", "Vendor is empty.")
    if not product.product_type:
        add("medium", "missing_product_type", "Product type is empty.")
    if not product.seo_title:
        add("medium", "missing_seo_title", "Shopify SEO title is empty.")
    if not product.seo_description:
        add("medium", "missing_seo_description", "Shopify SEO description is empty.")
    if product.status == "active" and not product.online_store_url:
        add("high", "active_without_store_url", "Active product has no online store URL.")
    if product.status == "active" and product.published_at is None:
        add("high", "active_without_published_at", "Active product has no publishedAt value.")
    if product.total_inventory is not None and product.total_inventory <= 0:
        add("low", "no_inventory", "Total inventory is zero or negative.")
    if product.variant_count == 1 and product.has_only_default_variant:
        add("low", "default_variant_only", "Only the default variant exists; confirm this is intentional.")
    if any(symbol in product.handle for symbol in ("®", "™", "©")):
        add("low", "symbol_in_handle", "URL handle contains a trademark/copyright symbol; review before changing.")
    if product.price.min_price is None:
        add("medium", "missing_price", "No minimum variant price was returned.")

    return issues


@router.get(
    "/v1/brands/{brand}/shopify/products/enriched",
    response_model=ProductCatalogResponse,
    dependencies=[Depends(require_api_key)],
    tags=["shopify"],
    operation_id="get_shopify_products_enriched",
)
async def get_shopify_products_enriched(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=50, ge=1, le=250),
    page_cursor: str | None = Query(default=None),
) -> ProductCatalogResponse:
    try:
        return await _read_enriched_products(brand, limit, page_cursor)
    except ShopifyNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except ShopifyUpstreamError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.get(
    "/v1/brands/{brand}/shopify/products/audit",
    response_model=ProductAuditResponse,
    dependencies=[Depends(require_api_key)],
    tags=["shopify"],
    operation_id="audit_shopify_products",
)
async def audit_shopify_products(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=250, ge=1, le=250),
) -> ProductAuditResponse:
    try:
        catalog = await _read_enriched_products(brand, limit, None)
    except ShopifyNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except ShopifyUpstreamError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

    issues = [
        issue
        for product in catalog.products
        for issue in _audit_product(product)
    ]

    severity_order = {"high": 3, "medium": 2, "low": 1}
    issues.sort(
        key=lambda item: (
            severity_order.get(item.severity, 0),
            item.title.lower(),
            item.code,
        ),
        reverse=True,
    )

    return ProductAuditResponse(
        brand=brand,
        summary=ProductAuditSummary(
            products_checked=len(catalog.products),
            active_products=sum(p.status == "active" for p in catalog.products),
            draft_products=sum(p.status == "draft" for p in catalog.products),
            issues_total=len(issues),
            high_issues=sum(i.severity == "high" for i in issues),
            medium_issues=sum(i.severity == "medium" for i in issues),
            low_issues=sum(i.severity == "low" for i in issues),
        ),
        issues=issues,
    )
