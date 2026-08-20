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
    GSCActionRow,
    GSCActionsResponse,
    GSCCompareResponse,
    GSCComparisonRow,
    GSCMetricChange,
    GSCMetricSnapshot,
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
    version="0.3.0",
    description=(
        "Read-only source data for the "
        "Nolix & TrapX Growth Agent."
    ),
)


BRANDED_TERMS = {
    "nolix": [
        "nolix",
        "nolix ai",
        "nolix.ai",
        "nomorlix",
        "noolix",
        "noelix",
        "nowlicx",
        "nimilix",
        "notilex",
        "nomorlix",
        "noliks",
    ],
    "trapx": [
        "trapx",
        "trap x",
        "trapx.io",
    ],
}

LOW_VALUE_PATTERNS = [
    "email address",
    "phone number",
    "login",
    "customer service",
]
def default_start_date() -> date:
    return date.today() - timedelta(days=27)


def is_branded_query(
    brand: str,
    query: str,
) -> bool:
    """
    Return True when the search query appears
    navigational/branded rather than a generic SEO query.
    """

    normalized = (
        query.lower()
        .strip()
        .replace("-", " ")
    )

    terms = BRANDED_TERMS.get(
        brand,
        [],
    )

    return any(
        term in normalized
        for term in terms
    )

def is_low_value_query(
    query: str,
) -> bool:
    """
    Filter obviously irrelevant or navigational
    searches that should not become SEO priorities.
    """

    normalized = query.lower().strip()

    return any(
        pattern in normalized
        for pattern in LOW_VALUE_PATTERNS
    ) 
def calculate_seo_priority(
    current_impressions: float,
    previous_impressions: float,
    current_position: float,
    previous_position: float,
    clicks_change: float,
) -> float:
    """
    Simple 0-100 priority score.

    Higher scores favor:
    - more visibility
    - positions closer to page one
    - meaningful ranking improvements
    - impression growth
    """

    score = 0.0

    # Visibility / evidence
    score += min(
        max(
            current_impressions,
            previous_impressions,
        )
        * 2,
        30,
    )

    # Position opportunity
    if 1 <= current_position <= 3:
        score += 10

    elif 3 < current_position <= 10:
        score += 30

    elif 10 < current_position <= 20:
        score += 25

    elif 20 < current_position <= 40:
        score += 15

    elif 40 < current_position <= 70:
        score += 5

    # Ranking improvement
    if (
        current_position > 0
        and previous_position > 0
    ):
        ranking_change = (
            previous_position
            - current_position
        )

        score += min(
            max(ranking_change * 2, 0),
            20,
        )

    # Impression growth
    impression_change = (
        current_impressions
        - previous_impressions
    )

    if impression_change > 0:
        score += min(
            impression_change,
            15,
        )

    # Click growth
    if clicks_change > 0:
        score += min(
            clicks_change * 5,
            15,
        )

    return round(
        min(score, 100),
        1,
    )
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
        print(
            "GSC ERROR:",
            error,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
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
        default=3,
        ge=1,
    ),
) -> GSCOpportunitiesResponse:
    """
    Identify non-branded organic-search opportunities.

    Current classifications:

    near_top_3
        Average position 3-6.

    striking_distance
        Average position >6-10.

    page_2
        Average position >10-20.

    high_impressions_low_ctr
        Page-one query with substantial impressions
        and CTR below 2%.
    """

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
        if not row.keys:
            continue

        if row.impressions < min_impressions:
            continue

        query = row.keys[0].strip()

        if not query:
            continue

        if is_branded_query(
            brand,
            query,
        ):
            continue

        if is_low_value_query(query):
            continue

        page = (
            row.keys[1]
            if len(row.keys) > 1
            else None
        )

        opportunity: str | None = None

        if (
            row.impressions >= 10
            and row.position <= 10
            and row.ctr < 0.02
        ):
            opportunity = "high_impressions_low_ctr"

        elif (
            row.impressions >= 3
            and 3 <= row.position <= 6
        ):
            opportunity = "near_top_3"

        elif (
            row.impressions >= 3
            and 6 < row.position <= 10
        ):
            opportunity = "striking_distance"

        elif (
            row.impressions >= 3
            and 10 < row.position <= 20
        ):
            opportunity = "page_2"

        if opportunity is None:
            continue

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

    priority = {
        "high_impressions_low_ctr": 4,
        "near_top_3": 3,
        "striking_distance": 2,
        "page_2": 1,
    }

    opportunities.sort(
        key=lambda item: (
            priority.get(
                item.opportunity,
                0,
            ),
            item.impressions,
        ),
        reverse=True,
    )

    return GSCOpportunitiesResponse(
        brand=brand,
        site_url=performance.site_url,
        start_date=start_date,
        end_date=end_date,
        opportunities=opportunities,
    )
@app.get(
    "/v1/brands/{brand}/gsc/compare",
    response_model=GSCCompareResponse,
    dependencies=[Depends(require_api_key)],
    tags=["gsc"],
    operation_id="compare_gsc_queries",
)
async def compare_gsc_queries(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    current_start_date: date = Query(...),
    current_end_date: date = Query(...),
    previous_start_date: date = Query(...),
    previous_end_date: date = Query(...),
    limit: int = Query(
        default=1000,
        ge=1,
        le=25000,
    ),
    min_impressions: float = Query(
        default=1,
        ge=0,
    ),
) -> GSCCompareResponse:
    """
    Compare query performance between two periods.

    Positive position change means ranking improved.
    Example:
        previous position 12
        current position 7
        position change = +5
    """

    _validate_date_range(
        current_start_date,
        current_end_date,
    )

    _validate_date_range(
        previous_start_date,
        previous_end_date,
    )

    current = await _gsc_query(
        brand,
        current_start_date,
        current_end_date,
        ["query"],
        limit,
        0,
        None,
        None,
    )

    previous = await _gsc_query(
        brand,
        previous_start_date,
        previous_end_date,
        ["query"],
        limit,
        0,
        None,
        None,
    )

    current_by_query = {
        row.keys[0]: row
        for row in current.rows
        if row.keys
    }

    previous_by_query = {
        row.keys[0]: row
        for row in previous.rows
        if row.keys
    }

    all_queries = (
        set(current_by_query.keys())
        | set(previous_by_query.keys())
    )

    rows: list[GSCComparisonRow] = []

    for query in all_queries:
        if is_branded_query(
            brand,
            query,
        ):
            continue

        if is_low_value_query(query):
            continue

        current_row = current_by_query.get(query)
        previous_row = previous_by_query.get(query)

        current_clicks = (
            current_row.clicks
            if current_row
            else 0
        )

        current_impressions = (
            current_row.impressions
            if current_row
            else 0
        )

        current_ctr = (
            current_row.ctr
            if current_row
            else 0
        )

        current_position = (
            current_row.position
            if current_row
            else 0
        )

        previous_clicks = (
            previous_row.clicks
            if previous_row
            else 0
        )

        previous_impressions = (
            previous_row.impressions
            if previous_row
            else 0
        )

        previous_ctr = (
            previous_row.ctr
            if previous_row
            else 0
        )

        previous_position = (
            previous_row.position
            if previous_row
            else 0
        )

        if (
            current_impressions < min_impressions
            and previous_impressions < min_impressions
        ):
            continue

        clicks_change = (
            current_clicks
            - previous_clicks
        )

        impressions_change = (
            current_impressions
            - previous_impressions
        )

        ctr_change = (
            current_ctr
            - previous_ctr
        )

        if (
            current_position > 0
            and previous_position > 0
        ):
            position_change = (
                previous_position
                - current_position
            )

        else:
            position_change = 0

        trend = "stable"

        if (
            impressions_change > 0
            and (
                clicks_change > 0
                or position_change > 0
            )
        ):
            trend = "gaining"

        elif (
            impressions_change < 0
            and (
                clicks_change < 0
                or position_change < 0
            )
        ):
            trend = "declining"

        elif (
            previous_impressions == 0
            and current_impressions > 0
        ):
            trend = "new"

        elif (
            current_impressions == 0
            and previous_impressions > 0
        ):
            trend = "lost"

        rows.append(
            GSCComparisonRow(
                query=query,
                current=GSCMetricSnapshot(
                    clicks=current_clicks,
                    impressions=current_impressions,
                    ctr=current_ctr,
                    position=current_position,
                ),
                previous=GSCMetricSnapshot(
                    clicks=previous_clicks,
                    impressions=previous_impressions,
                    ctr=previous_ctr,
                    position=previous_position,
                ),
                changes=GSCMetricChange(
                    clicks=clicks_change,
                    impressions=impressions_change,
                    ctr=ctr_change,
                    position=position_change,
                ),
                trend=trend,
            )
        )

    trend_priority = {
        "gaining": 4,
        "new": 3,
        "declining": 2,
        "lost": 1,
        "stable": 0,
    }

    rows.sort(
        key=lambda item: (
            trend_priority.get(
                item.trend,
                0,
            ),
            abs(
                item.changes.impressions
            ),
        ),
        reverse=True,
    )

    return GSCCompareResponse(
        brand=brand,
        site_url=current.site_url,
        current_start_date=current_start_date,
        current_end_date=current_end_date,
        previous_start_date=previous_start_date,
        previous_end_date=previous_end_date,
        rows=rows,
    )
@app.get(
    "/v1/brands/{brand}/gsc/actions",
    response_model=GSCActionsResponse,
    dependencies=[Depends(require_api_key)],
    tags=["gsc"],
    operation_id="list_gsc_actions",
)
async def list_gsc_actions(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    current_start_date: date = Query(...),
    current_end_date: date = Query(...),
    previous_start_date: date = Query(...),
    previous_end_date: date = Query(...),
    limit: int = Query(
        default=1000,
        ge=1,
        le=25000,
    ),
    min_impressions: float = Query(
        default=1,
        ge=0,
    ),
) -> GSCActionsResponse:
    """
    Convert raw GSC period comparison data into
    actionable SEO recommendations.
    """

    _validate_date_range(
        current_start_date,
        current_end_date,
    )

    _validate_date_range(
        previous_start_date,
        previous_end_date,
    )

    current = await _gsc_query(
        brand,
        current_start_date,
        current_end_date,
        ["query"],
        limit,
        0,
        None,
        None,
    )

    previous = await _gsc_query(
        brand,
        previous_start_date,
        previous_end_date,
        ["query"],
        limit,
        0,
        None,
        None,
    )

    current_by_query = {
        row.keys[0]: row
        for row in current.rows
        if row.keys
    }

    previous_by_query = {
        row.keys[0]: row
        for row in previous.rows
        if row.keys
    }

    all_queries = (
        set(current_by_query.keys())
        | set(previous_by_query.keys())
    )

    actions: list[GSCActionRow] = []

    for query in all_queries:
        if is_branded_query(
            brand,
            query,
        ):
            continue

        if is_low_value_query(query):
            continue

        current_row = current_by_query.get(query)
        previous_row = previous_by_query.get(query)

        current_clicks = (
            current_row.clicks
            if current_row
            else 0
        )

        current_impressions = (
            current_row.impressions
            if current_row
            else 0
        )

        current_ctr = (
            current_row.ctr
            if current_row
            else 0
        )

        current_position = (
            current_row.position
            if current_row
            else 0
        )

        previous_clicks = (
            previous_row.clicks
            if previous_row
            else 0
        )

        previous_impressions = (
            previous_row.impressions
            if previous_row
            else 0
        )

        previous_ctr = (
            previous_row.ctr
            if previous_row
            else 0
        )

        previous_position = (
            previous_row.position
            if previous_row
            else 0
        )

        if (
            current_impressions < min_impressions
            and previous_impressions < min_impressions
        ):
            continue

        clicks_change = (
            current_clicks
            - previous_clicks
        )

        impressions_change = (
            current_impressions
            - previous_impressions
        )

        ctr_change = (
            current_ctr
            - previous_ctr
        )

        if (
            current_position > 0
            and previous_position > 0
        ):
            position_change = (
                previous_position
                - current_position
            )
        else:
            position_change = 0

        action: str | None = None
        recommendation: str | None = None

        # Best opportunity:
        # currently ranking close to page one/top positions.
        if (
            current_impressions >= 3
            and 4 <= current_position <= 20
        ):
            action = "quick_win"
            recommendation = (
                "Improve the existing ranking page around "
                "this query, strengthen title/H1 alignment, "
                "internal links, and search-intent coverage."
            )

        # New query already showing promising ranking.
        elif (
            previous_impressions == 0
            and current_impressions > 0
            and 1 <= current_position <= 30
        ):
            action = "new_opportunity"
            recommendation = (
                "Google has started surfacing Nolix for this "
                "query. Strengthen the relevant page before "
                "the ranking opportunity fades."
            )

        # Material upward trend, even if ranking is
        # still outside page one.
        elif (
            current_impressions
            > previous_impressions
            and position_change >= 3
            and current_position <= 70
        ):
            action = "rising"
            recommendation = (
                "Visibility and ranking are improving. "
                "Continue building topical relevance and "
                "internal links around this query."
            )

        # Ranking/visibility deteriorated.
        elif (
            current_impressions > 0
            and previous_impressions > 0
            and impressions_change < 0
            and position_change <= -3
        ):
            action = "declining"
            recommendation = (
                "Review the ranking page for content decay, "
                "intent mismatch, internal-link changes, "
                "and stronger competing pages."
            )

        # Query disappeared completely.
        elif (
            current_impressions == 0
            and previous_impressions >= 2
            and previous_position <= 30
        ):
            action = "lost_opportunity"
            recommendation = (
                "This query previously had meaningful "
                "visibility but disappeared. Check indexing, "
                "content changes, cannibalization, and SERP "
                "competition."
            )

        if action is None:
            continue

        priority_score = calculate_seo_priority(
            current_impressions=(
                current_impressions
            ),
            previous_impressions=(
                previous_impressions
            ),
            current_position=(
                current_position
            ),
            previous_position=(
                previous_position
            ),
            clicks_change=clicks_change,
        )

        actions.append(
            GSCActionRow(
                query=query,
                action=action,
                priority_score=priority_score,
                recommendation=recommendation,
                current=GSCMetricSnapshot(
                    clicks=current_clicks,
                    impressions=current_impressions,
                    ctr=current_ctr,
                    position=current_position,
                ),
                previous=GSCMetricSnapshot(
                    clicks=previous_clicks,
                    impressions=previous_impressions,
                    ctr=previous_ctr,
                    position=previous_position,
                ),
                changes=GSCMetricChange(
                    clicks=clicks_change,
                    impressions=impressions_change,
                    ctr=ctr_change,
                    position=position_change,
                ),
            )
        )

    action_priority = {
        "quick_win": 5,
        "lost_opportunity": 4,
        "new_opportunity": 3,
        "rising": 2,
        "declining": 1,
    }

    actions.sort(
        key=lambda item: (
            action_priority.get(
                item.action,
                0,
            ),
            item.priority_score,
        ),
        reverse=True,
    )

    return GSCActionsResponse(
        brand=brand,
        site_url=current.site_url,
        current_start_date=current_start_date,
        current_end_date=current_end_date,
        previous_start_date=previous_start_date,
        previous_end_date=previous_end_date,
        actions=actions,
    )