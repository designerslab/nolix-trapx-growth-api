from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.shopify import (
    ShopifyClient,
    ShopifyNotConfiguredError,
    ShopifyUpstreamError,
)

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
    product_status: str
    severity: str
    actionability: str
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
    actionable_issues: int = 0
    review_issues: int = 0
    informational_issues: int = 0
    backlog_issues: int = 0


class ProductAuditResponse(BaseModel):
    brand: str
    summary: ProductAuditSummary
    issues: list[ProductAuditIssue] = Field(default_factory=list)
    source: str = "shopify"


class CatalogHealthCounts(BaseModel):
    missing_vendor: int = 0
    missing_product_type: int = 0
    missing_seo_title: int = 0
    missing_seo_description: int = 0
    missing_price: int = 0
    zero_or_negative_inventory: int = 0
    active_without_store_url: int = 0
    active_without_published_at: int = 0
    url_handle_review_candidates: int = 0
    default_variant_only: int = 0


class CatalogHealthResponse(BaseModel):
    brand: str
    products_checked: int
    active_products: int
    draft_products: int
    active_actionable_issues: int
    active_review_issues: int
    active_informational_issues: int
    draft_backlog_issues: int
    active: CatalogHealthCounts
    draft: CatalogHealthCounts
    report_status: str
    report_summary: str
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
            min_price.get("currencyCode")
            or max_price.get("currencyCode")
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


def _issue_actionability(
    product: ProductCatalogRow,
    code: str,
) -> str:
    if product.status != "active":
        return "backlog"
    if code == "default_variant_only":
        return "informational"
    if code == "symbol_in_handle":
        return "review"
    return "actionable"


def _audit_product(
    product: ProductCatalogRow,
) -> list[ProductAuditIssue]:
    issues: list[ProductAuditIssue] = []

    def add(severity: str, code: str, message: str) -> None:
        issues.append(
            ProductAuditIssue(
                product_id=product.numeric_id,
                title=product.title,
                product_status=product.status,
                severity=severity,
                actionability=_issue_actionability(product, code),
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
        add(
            "low",
            "no_inventory",
            "Total inventory is zero or negative. Confirm whether this is intentional.",
        )
    if product.variant_count == 1 and product.has_only_default_variant:
        add(
            "low",
            "default_variant_only",
            "Product has only the default variant. This is informational when one SKU is intentional.",
        )
    if any(symbol in product.handle for symbol in ("®", "™", "©")):
        add(
            "low",
            "symbol_in_handle",
            "URL handle contains a trademark or copyright symbol. Review redirects, links and SEO impact before changing.",
        )
    if product.price.min_price is None:
        add("medium", "missing_price", "No minimum variant price was returned.")

    return issues


def _health_counts(
    products: list[ProductCatalogRow],
) -> CatalogHealthCounts:
    counts = Counter()

    for product in products:
        if not product.vendor:
            counts["missing_vendor"] += 1
        if not product.product_type:
            counts["missing_product_type"] += 1
        if not product.seo_title:
            counts["missing_seo_title"] += 1
        if not product.seo_description:
            counts["missing_seo_description"] += 1
        if product.price.min_price is None:
            counts["missing_price"] += 1
        if product.total_inventory is not None and product.total_inventory <= 0:
            counts["zero_or_negative_inventory"] += 1
        if product.status == "active" and not product.online_store_url:
            counts["active_without_store_url"] += 1
        if product.status == "active" and product.published_at is None:
            counts["active_without_published_at"] += 1
        if any(symbol in product.handle for symbol in ("®", "™", "©")):
            counts["url_handle_review_candidates"] += 1
        if product.variant_count == 1 and product.has_only_default_variant:
            counts["default_variant_only"] += 1

    return CatalogHealthCounts(**counts)


def _report_status(
    active_actionable: int,
    active_review: int,
) -> str:
    if active_actionable >= 10:
        return "needs_attention"
    if active_actionable > 0 or active_review > 0:
        return "review"
    return "healthy"


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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ShopifyUpstreamError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ShopifyUpstreamError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    issues = [
        issue
        for product in catalog.products
        for issue in _audit_product(product)
    ]

    severity_order = {"high": 3, "medium": 2, "low": 1}
    actionability_order = {
        "actionable": 4,
        "review": 3,
        "backlog": 2,
        "informational": 1,
    }

    issues.sort(
        key=lambda item: (
            actionability_order.get(item.actionability, 0),
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
            actionable_issues=sum(i.actionability == "actionable" for i in issues),
            review_issues=sum(i.actionability == "review" for i in issues),
            informational_issues=sum(i.actionability == "informational" for i in issues),
            backlog_issues=sum(i.actionability == "backlog" for i in issues),
        ),
        issues=issues,
    )


@router.get(
    "/v1/brands/{brand}/shopify/products/catalog-health",
    response_model=CatalogHealthResponse,
    dependencies=[Depends(require_api_key)],
    tags=["shopify"],
    operation_id="get_shopify_catalog_health",
)
async def get_shopify_catalog_health(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=250, ge=1, le=250),
) -> CatalogHealthResponse:
    try:
        catalog = await _read_enriched_products(brand, limit, None)
    except ShopifyNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ShopifyUpstreamError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    active_products = [p for p in catalog.products if p.status == "active"]
    draft_products = [p for p in catalog.products if p.status == "draft"]

    active_issues = [
        issue
        for product in active_products
        for issue in _audit_product(product)
    ]
    draft_issues = [
        issue
        for product in draft_products
        for issue in _audit_product(product)
    ]

    active_actionable = sum(
        issue.actionability == "actionable"
        for issue in active_issues
    )
    active_review = sum(
        issue.actionability == "review"
        for issue in active_issues
    )
    active_info = sum(
        issue.actionability == "informational"
        for issue in active_issues
    )
    draft_backlog = sum(
        issue.actionability == "backlog"
        for issue in draft_issues
    )

    active_counts = _health_counts(active_products)
    draft_counts = _health_counts(draft_products)

    report_status = _report_status(active_actionable, active_review)
    report_summary = (
        f"{len(active_products)} active products; "
        f"{active_actionable} actionable active-product catalog issues; "
        f"{active_review} review items; "
        f"{active_info} informational items; "
        f"{draft_backlog} draft-product backlog items."
    )

    return CatalogHealthResponse(
        brand=brand,
        products_checked=len(catalog.products),
        active_products=len(active_products),
        draft_products=len(draft_products),
        active_actionable_issues=active_actionable,
        active_review_issues=active_review,
        active_informational_issues=active_info,
        draft_backlog_issues=draft_backlog,
        active=active_counts,
        draft=draft_counts,
        report_status=report_status,
        report_summary=report_summary,
    )
