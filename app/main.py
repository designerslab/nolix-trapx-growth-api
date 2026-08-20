from datetime import date, timedelta

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Path,
    Query,
    status,
)

from app.config import get_settings

from app.schemas import (
    GSCOpportunitiesResponse,
    GSCOpportunity,
    GSCPerformanceResponse,
    HealthResponse,
    ShopifyProductsResponse,
)

from app.security import require_api_key

from app.services.gsc import (
    GSCClient,
    GSCNotConfiguredError,
    GSCUpstreamError,
)

from app.services.shopify import (
    ShopifyClient,
    ShopifyNotConfiguredError,
    ShopifyUpstreamError,
)


app = FastAPI(
    title="Nolix & TrapX Growth API",
    version="0.2.0",
    description=(
        "Read-only source data for the "
        "Nolix & TrapX Growth Agent."
    ),
)


def default_start_date() -> date:
    return date.today() - timedelta(days=27)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    operation_id="health",
)
async def health() -> HealthResponse:
    settings = get_settings()

    gsc_configured = bool(
        settings.google_service_account_json
        and any(
            settings.gsc_site_url(brand)
            for brand in ("nolix", "trapx")
        )
    )

    shopify_configured = any(
        settings.shopify_credentials(brand)[0]
        for brand in ("nolix", "trapx")
    )

    return HealthResponse(
        integrations={
            "shopify": (
                "configured"
                if shopify_configured
                else "pending"
            ),
            "gsc": (
                "configured"
                if gsc_configured
                else "pending"
            ),
            "ga4": "planned",
        }
    )


@app.get(
    "/v1/brands/{brand}/shopify/products",
    response_model=ShopifyProductsResponse,
    dependencies=[Depends(require_api_key)],
    tags=["shopify"],
    operation_id="list_shopify_products",
)
async def list_shopify_products(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=250,
    ),
    page_cursor: str | None = Query(
        default=None
    ),
) -> ShopifyProductsResponse:

    try:
        return await ShopifyClient(
            get_settings(),
            brand,
        ).list_products(
            limit,
            page_cursor,
        )

    except ShopifyNotConfiguredError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(error),
        ) from error

    except ShopifyUpstreamError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Shopify product query failed.",
        ) from error


def _validate_date_range(
    start_date: date,
    end_date: date,
) -> None:

    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail=(
                "end_date must be on or "
                "after start_date"
            ),
        )


async def _gsc_query(
    brand: str,
    start_date: date,
    end_date: date,
    dimensions: list[str],
    limit: int,
    start_row: int,
    country: str | None,
    device: str | None,
) -> GSCPerformanceResponse:

    _validate_date_range(
        start_date,
        end_date,
    )

    try:
        return await GSCClient(
            get_settings(),
            brand,
        ).query_performance(
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            row_limit=limit,
            start_row=start_row,
            country=country,
            device=device,
        )

    except GSCNotConfiguredError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(error),
        ) from error

    except GSCUpstreamError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Google Search Console query failed."
            ),
        ) from error


@app.get(
    "/v1/brands/{brand}/gsc/queries",
    response_model=GSCPerformanceResponse,
    dependencies=[Depends(require_api_key)],
    tags=["gsc"],
    operation_id="list_gsc_queries",
)
async def list_gsc_queries(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    start_date: date = Query(
        default_factory=default_start_date
    ),
    end_date: date = Query(
        default_factory=date.today
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=25000,
    ),
    start_row: int = Query(
        default=0,
        ge=0,
    ),
    country: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
    ),
    device: str | None = Query(
        default=None,
        pattern="^(DESKTOP|MOBILE|TABLET)$",
    ),
) -> GSCPerformanceResponse:

    return await _gsc_query(
        brand,
        start_date,
        end_date,
        ["query"],
        limit,
        start_row,
        country,
        device,
    )


@app.get(
    "/v1/brands/{brand}/gsc/pages",
    response_model=GSCPerformanceResponse,
    dependencies=[Depends(require_api_key)],
    tags=["gsc"],
    operation_id="list_gsc_pages",
)
async def list_gsc_pages(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    start_date: date = Query(
        default_factory=default_start_date
    ),
    end_date: date = Query(
        default_factory=date.today
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=25000,
    ),
    start_row: int = Query(
        default=0,
        ge=0,
    ),
    country: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
    ),
    device: str | None = Query(
        default=None,
        pattern="^(DESKTOP|MOBILE|TABLET)$",
    ),
) -> GSCPerformanceResponse:

    return await _gsc_query(
        brand,
        start_date,
        end_date,
        ["page"],
        limit,
        start_row,
        country,
        device,
    )


@app.get(
    "/v1/brands/{brand}/gsc/query-pages",
    response_model=GSCPerformanceResponse,
    dependencies=[Depends(require_api_key)],
    tags=["gsc"],
    operation_id="list_gsc_query_pages",
)
async def list_gsc_query_pages(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    start_date: date = Query(
        default_factory=default_start_date
    ),
    end_date: date = Query(
        default_factory=date.today
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=25000,
    ),
    start_row: int = Query(
        default=0,
        ge=0,
    ),
    country: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
    ),
    device: str | None = Query(
        default=None,
        pattern="^(DESKTOP|MOBILE|TABLET)$",
    ),
) -> GSCPerformanceResponse:

    return await _gsc_query(
        brand,
        start_date,
        end_date,
        ["query", "page"],
        limit,
        start_row,
        country,
        device,
    )


@app.get(
    "/v1/brands/{brand}/gsc/opportunities",
    response_model=GSCOpportunitiesResponse,
    dependencies=[Depends(require_api_key)],
    tags=["gsc"],
    operation_id="list_gsc_opportunities",
)
async def list_gsc_opportunities(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    start_date: date = Query(
        default_factory=default_start_date
    ),
    end_date: date = Query(
        default_factory=date.today
    ),
    limit: int = Query(
        default=1000,
        ge=1,
        le=25000,
    ),
    min_impressions: float = Query(
        default=100,
        ge=0,
    ),
) -> GSCOpportunitiesResponse:

    performance = await _gsc_query(
        brand,
        start_date,
        end_date,
        ["query", "page"],
        limit,
        0,
        None,
        None,
    )

    opportunities: list[GSCOpportunity] = []

    for row in performance.rows:

        if (
            row.impressions < min_impressions
            or not row.keys
        ):
            continue

        query = row.keys[0]

        page = (
            row.keys[1]
            if len(row.keys) > 1
            else None
        )

        opportunity: str | None = None

        if 4 <= row.position <= 20:
            opportunity = "striking_distance"

        elif (
            row.ctr < 0.02
            and row.impressions >= min_impressions
        ):
            opportunity = (
                "high_impressions_low_ctr"
            )

        if opportunity:
            opportunities.append(
                GSCOpportunity(
                    query=query,
                    page=page,
                    clicks=row.clicks,
                    impressions=row.impressions,
                    ctr=row.ctr,
                    position=row.position,
                    opportunity=opportunity,
                )
            )

    opportunities.sort(
        key=lambda item: item.impressions,
        reverse=True,
    )

    return GSCOpportunitiesResponse(
        brand=brand,
        site_url=performance.site_url,
        start_date=start_date,
        end_date=end_date,
        opportunities=opportunities,
    )