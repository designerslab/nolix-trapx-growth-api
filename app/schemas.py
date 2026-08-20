from datetime import date, datetime

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
    products: list[ShopifyProduct] = Field(
        default_factory=list
    )
    next_page: str | None = None


class GSCPerformanceRow(BaseModel):
    keys: list[str] = Field(default_factory=list)
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class GSCPerformanceResponse(BaseModel):
    brand: str
    site_url: str
    start_date: date
    end_date: date
    dimensions: list[str]

    rows: list[GSCPerformanceRow] = Field(
        default_factory=list
    )


class GSCOpportunity(BaseModel):
    query: str
    page: str | None = None

    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0

    opportunity: str


class GSCOpportunitiesResponse(BaseModel):
    brand: str
    site_url: str

    start_date: date
    end_date: date

    opportunities: list[GSCOpportunity] = Field(
        default_factory=list
    )