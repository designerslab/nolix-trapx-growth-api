import os
from datetime import date

import httpx
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=False,
)
mcp = MCPServer(
    "Nolix Growth API",
    instructions=(
        "Read-only growth data for Nolix and TrapX "
        "from Google Search Console, GA4, and Shopify."
    ),
)

GROWTH_API_PUBLIC_URL = os.getenv(
    "GROWTH_API_PUBLIC_URL",
    "https://nolix-trapx-growth-api.onrender.com",
).rstrip("/")

GROWTH_API_KEY = os.getenv("GROWTH_API_KEY")


async def _get(
    path: str,
    params: dict | None = None,
) -> dict:
    headers = {}

    if GROWTH_API_KEY:
        headers["X-API-Key"] = GROWTH_API_KEY

    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(
            f"{GROWTH_API_PUBLIC_URL}{path}",
            params=params,
            headers=headers,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Growth API returned "
                f"{response.status_code}: "
                f"{response.text[:1000]}"
            )

        return response.json()


@mcp.tool(annotations=READ_ONLY)
async def get_gsc_queries(
    brand: str,
    start_date: str,
    end_date: str,
    limit: int = 100,
    start_row: int = 0,
) -> dict:
    """Get Google Search Console query performance."""

    return await _get(
        f"/v1/brands/{brand}/gsc/queries",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "start_row": start_row,
        },
    )


@mcp.tool( annotations=READ_ONLY)
async def get_gsc_pages(
    brand: str,
    start_date: str,
    end_date: str,
    limit: int = 100,
    start_row: int = 0,
) -> dict:
    """Get Google Search Console page performance."""

    return await _get(
        f"/v1/brands/{brand}/gsc/pages",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "start_row": start_row,
        },
    )


@mcp.tool( annotations=READ_ONLY)
async def get_gsc_query_pages(
    brand: str,
    start_date: str,
    end_date: str,
    limit: int = 100,
    start_row: int = 0,
) -> dict:
    """Get Google Search Console query-to-page performance."""

    return await _get(
        f"/v1/brands/{brand}/gsc/query-pages",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "start_row": start_row,
        },
    )


@mcp.tool(annotations=READ_ONLY)
async def get_gsc_opportunities(
    brand: str,
    start_date: str,
    end_date: str,
    limit: int = 1000,
    min_impressions: float = 3,
) -> dict:
    """Get filtered SEO opportunities from GSC."""

    return await _get(
        f"/v1/brands/{brand}/gsc/opportunities",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "min_impressions": min_impressions,
        },
    )


@mcp.tool(annotations=READ_ONLY)
async def compare_gsc_queries(
    brand: str,
    current_start_date: str,
    current_end_date: str,
    previous_start_date: str,
    previous_end_date: str,
    limit: int = 1000,
    min_impressions: float = 1,
) -> dict:
    """Compare GSC query performance between two periods."""

    return await _get(
        f"/v1/brands/{brand}/gsc/compare",
        {
            "current_start_date": current_start_date,
            "current_end_date": current_end_date,
            "previous_start_date": previous_start_date,
            "previous_end_date": previous_end_date,
            "limit": limit,
            "min_impressions": min_impressions,
        },
    )


@mcp.tool(annotations=READ_ONLY)
async def get_gsc_actions(
    brand: str,
    current_start_date: str,
    current_end_date: str,
    previous_start_date: str,
    previous_end_date: str,
    limit: int = 1000,
    min_impressions: float = 1,
) -> dict:
    """Get prioritized SEO actions derived from GSC comparison data."""

    return await _get(
        f"/v1/brands/{brand}/gsc/actions",
        {
            "current_start_date": current_start_date,
            "current_end_date": current_end_date,
            "previous_start_date": previous_start_date,
            "previous_end_date": previous_end_date,
            "limit": limit,
            "min_impressions": min_impressions,
        },
    )


@mcp.tool(annotations=READ_ONLY)
async def get_ga4_overview(
    brand: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Get GA4 traffic and engagement summary."""

    return await _get(
        f"/v1/brands/{brand}/ga4/overview",
        {
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@mcp.tool(annotations=READ_ONLY)
async def get_ga4_landing_pages(
    brand: str,
    start_date: str,
    end_date: str,
    limit: int = 100,
) -> dict:
    """Get GA4 landing-page engagement metrics."""

    return await _get(
        f"/v1/brands/{brand}/ga4/landing-pages",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    )


@mcp.tool(  annotations=READ_ONLY)
async def get_ga4_channels( 
    brand: str,
    start_date: str,
    end_date: str,
    limit: int = 50,
) -> dict:
    """Get GA4 acquisition channel performance."""

    return await _get(
        f"/v1/brands/{brand}/ga4/channels",
        {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        },
    )

@mcp.tool(annotations=READ_ONLY)
async def get_shopify_product(
    brand: str,
    product_id: str,
) -> dict:
    """
    Get detailed read-only Shopify product data.

    product_id should be the numeric Shopify product ID.
    """

    brand = brand.lower().strip()

    if brand not in {"nolix", "trapx"}:
        raise ValueError(
            "brand must be either 'nolix' or 'trapx'"
        )

    return await _get(
        (
            f"/v1/brands/{brand}"
            f"/shopify/products/{product_id}"
        )
    )
@mcp.tool(annotations=READ_ONLY)
async def get_shopify_product_variants(
    brand: str,
    product_id: str,
    limit: int = 100,
) -> dict:
    """
    Get variants, SKU, price and inventory
    for a Shopify product.

    product_id should be the numeric Shopify product ID.
    """

    brand = brand.lower().strip()

    if brand not in {"nolix", "trapx"}:
        raise ValueError(
            "brand must be either 'nolix' or 'trapx'"
        )

    return await _get(
        (
            f"/v1/brands/{brand}"
            f"/shopify/products/"
            f"{product_id}/variants"
        ),
        {
            "limit": limit,
        },
    )
@mcp.tool(annotations=READ_ONLY)
async def get_shopify_products(
    brand: str,
    limit: int = 50,
    page_cursor: str | None = None,
) -> dict:
    """Get read-only Shopify product catalog data."""

    brand = brand.lower().strip()

    if brand not in {"nolix", "trapx"}:
        raise ValueError(
            "brand must be either 'nolix' or 'trapx'"
        )

    params = {
        "limit": limit,
    }

    if page_cursor:
        params["page_cursor"] = page_cursor

    return await _get(
        f"/v1/brands/{brand}/shopify/products",
        params,
    )
@mcp.tool(annotations=READ_ONLY)
async def inspect_ga4_referrals(
    brand: str,
    start_date: str,
    end_date: str,
    previous_start_date: str,
    previous_end_date: str,
    limit: int = 1000,
) -> dict:
    """Inspect GA4 Referral traffic and score bot/traffic-quality risk."""

    return await _get(
        f"/v1/brands/{brand}/ga4/referral-inspection",
        {
            "start_date": start_date,
            "end_date": end_date,
            "previous_start_date": previous_start_date,
            "previous_end_date": previous_end_date,
            "limit": limit,
        },
    )

@mcp.tool(annotations=READ_ONLY)
async def get_revenue_summary(
    brand: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Get read-only Shopify revenue summary."""
    brand = brand.lower().strip()
    if brand not in {"nolix", "trapx"}:
        raise ValueError("brand must be either 'nolix' or 'trapx'")

    return await _get(
        f"/v1/brands/{brand}/revenue/summary",
        {
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@mcp.tool(annotations=READ_ONLY)
async def get_revenue_daily(
    brand: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Get read-only daily Shopify revenue."""
    brand = brand.lower().strip()
    if brand not in {"nolix", "trapx"}:
        raise ValueError("brand must be either 'nolix' or 'trapx'")

    return await _get(
        f"/v1/brands/{brand}/revenue/daily",
        {
            "start_date": start_date,
            "end_date": end_date,
        },
    )

