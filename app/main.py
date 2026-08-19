from fastapi import Depends, FastAPI, HTTPException, Path, Query, status

from app.config import get_settings
from app.schemas import HealthResponse, ShopifyProductsResponse
from app.security import require_api_key
from app.services.shopify import ShopifyClient, ShopifyNotConfiguredError, ShopifyUpstreamError

app = FastAPI(
    title="Nolix & TrapX Growth API",
    version="0.1.0",
    description="Read-only source data for the Nolix & TrapX Growth Agent.",
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        integrations={
            "shopify": "configured" if any(settings.shopify_credentials(b)[0] for b in ("nolix", "trapx")) else "pending",
            "gsc": "planned",
            "ga4": "planned",
        }
    )


@app.get(
    "/v1/brands/{brand}/shopify/products",
    response_model=ShopifyProductsResponse,
    dependencies=[Depends(require_api_key)],
    tags=["shopify"],
)
async def list_shopify_products(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=50, ge=1, le=250),
    page_cursor: str | None = Query(default=None),
) -> ShopifyProductsResponse:
    try:
        return await ShopifyClient(get_settings(), brand).list_products(limit, page_cursor)
    except ShopifyNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except ShopifyUpstreamError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Shopify product query failed.") from error
