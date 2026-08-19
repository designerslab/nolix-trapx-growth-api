from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    integrations: dict[str, str]


class ShopifyProduct(BaseModel):
    id: str
    title: str
    handle: str
    status: str
    updated_at: datetime | None = None
    url: str | None = None


class ShopifyProductsResponse(BaseModel):
    brand: str
    products: list[ShopifyProduct] = Field(default_factory=list)
    next_page: str | None = None
