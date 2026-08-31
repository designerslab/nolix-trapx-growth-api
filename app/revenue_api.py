from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

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


class RevenueSummaryResponse(BaseModel):
    brand: str
    start_date: date
    end_date: date
    currency: str | None = None
    orders: int
    cancelled_orders: int
    gross_sales: str
    refunds: str
    net_sales: str
    discounts: str
    average_order_value: str
    source: str = "shopify_orders"
    definition_notes: list[str] = Field(default_factory=list)


class RevenueDailyRow(BaseModel):
    date: date
    orders: int
    gross_sales: str
    refunds: str
    net_sales: str


class RevenueDailyResponse(BaseModel):
    brand: str
    start_date: date
    end_date: date
    currency: str | None = None
    rows: list[RevenueDailyRow] = Field(default_factory=list)
    source: str = "shopify_orders"


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _shop_money(order: dict, field: str) -> tuple[Decimal, str | None]:
    money = ((order.get(field) or {}).get("shopMoney") or {})
    return _money(money.get("amount")), money.get("currencyCode")


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _currency_or_error(orders: list[dict]) -> str | None:
    currencies = {
        currency
        for order in orders
        for _, currency in [_shop_money(order, "currentTotalPriceSet")]
        if currency
    }
    if len(currencies) > 1:
        raise ShopifyUpstreamError(
            "Shopify returned multiple shop currencies for the requested period."
        )
    return next(iter(currencies), None)


async def _read_orders(
    brand: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )

    client = ShopifyClient(get_settings(), brand)
    after: str | None = None
    orders: list[dict] = []
    exclusive_end = end_date + timedelta(days=1)

    search_query = (
        f"created_at:>={start_date.isoformat()} "
        f"created_at:<{exclusive_end.isoformat()}"
    )

    query = '''
    query RevenueOrders($first: Int!, $after: String, $query: String!) {
      orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
        nodes {
          id
          createdAt
          cancelledAt
          displayFinancialStatus
          totalPriceSet { shopMoney { amount currencyCode } }
          currentTotalPriceSet { shopMoney { amount currencyCode } }
          totalRefundedSet { shopMoney { amount currencyCode } }
          totalDiscountsSet { shopMoney { amount currencyCode } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    '''

    while True:
        data = await client._graphql(
            query,
            {
                "first": 100,
                "after": after,
                "query": search_query,
            },
        )

        connection = data.get("orders") or {}
        orders.extend(connection.get("nodes") or [])

        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break

        after = page_info.get("endCursor")
        if not after:
            break

    return orders


@router.get(
    "/v1/brands/{brand}/revenue/summary",
    response_model=RevenueSummaryResponse,
    dependencies=[Depends(require_api_key)],
    tags=["revenue"],
    operation_id="get_revenue_summary",
)
async def get_revenue_summary(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> RevenueSummaryResponse:
    try:
        orders = await _read_orders(brand, start_date, end_date)
        currency = _currency_or_error(orders)
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

    gross_sales = Decimal("0")
    refunds = Decimal("0")
    net_sales = Decimal("0")
    discounts = Decimal("0")
    cancelled_orders = 0

    for order in orders:
        gross_sales += _shop_money(order, "totalPriceSet")[0]
        refunds += _shop_money(order, "totalRefundedSet")[0]
        net_sales += _shop_money(order, "currentTotalPriceSet")[0]
        discounts += _shop_money(order, "totalDiscountsSet")[0]
        if order.get("cancelledAt"):
            cancelled_orders += 1

    order_count = len(orders)
    average_order_value = (
        net_sales / order_count if order_count else Decimal("0")
    )

    return RevenueSummaryResponse(
        brand=brand,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        orders=order_count,
        cancelled_orders=cancelled_orders,
        gross_sales=_fmt(gross_sales),
        refunds=_fmt(refunds),
        net_sales=_fmt(net_sales),
        discounts=_fmt(discounts),
        average_order_value=_fmt(average_order_value),
        definition_notes=[
            "gross_sales uses Shopify totalPriceSet",
            "refunds uses Shopify totalRefundedSet",
            "net_sales uses Shopify currentTotalPriceSet",
            "all money values use Shopify shopMoney currency",
            "customer PII is not requested or returned",
        ],
    )


@router.get(
    "/v1/brands/{brand}/revenue/daily",
    response_model=RevenueDailyResponse,
    dependencies=[Depends(require_api_key)],
    tags=["revenue"],
    operation_id="get_revenue_daily",
)
async def get_revenue_daily(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> RevenueDailyResponse:
    try:
        orders = await _read_orders(brand, start_date, end_date)
        currency = _currency_or_error(orders)
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

    buckets: dict[date, dict[str, Decimal | int]] = defaultdict(
        lambda: {
            "orders": 0,
            "gross_sales": Decimal("0"),
            "refunds": Decimal("0"),
            "net_sales": Decimal("0"),
        }
    )

    for order in orders:
        created_at = str(order.get("createdAt") or "")
        try:
            order_date = date.fromisoformat(created_at[:10])
        except ValueError:
            continue

        bucket = buckets[order_date]
        bucket["orders"] = int(bucket["orders"]) + 1
        bucket["gross_sales"] = (
            Decimal(bucket["gross_sales"])
            + _shop_money(order, "totalPriceSet")[0]
        )
        bucket["refunds"] = (
            Decimal(bucket["refunds"])
            + _shop_money(order, "totalRefundedSet")[0]
        )
        bucket["net_sales"] = (
            Decimal(bucket["net_sales"])
            + _shop_money(order, "currentTotalPriceSet")[0]
        )

    rows = [
        RevenueDailyRow(
            date=day,
            orders=int(values["orders"]),
            gross_sales=_fmt(Decimal(values["gross_sales"])),
            refunds=_fmt(Decimal(values["refunds"])),
            net_sales=_fmt(Decimal(values["net_sales"])),
        )
        for day, values in sorted(buckets.items())
    ]

    return RevenueDailyResponse(
        brand=brand,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        rows=rows,
    )
