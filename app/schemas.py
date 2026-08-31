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
class GSCMetricSnapshot(BaseModel):
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class GSCMetricChange(BaseModel):
    clicks: float = 0
    impressions: float = 0
    ctr: float = 0
    position: float = 0


class GSCComparisonRow(BaseModel):
    query: str
    current: GSCMetricSnapshot
    previous: GSCMetricSnapshot
    changes: GSCMetricChange
    trend: str


class GSCCompareResponse(BaseModel):
    brand: str
    site_url: str

    current_start_date: date
    current_end_date: date

    previous_start_date: date
    previous_end_date: date

    rows: list[GSCComparisonRow] = Field(
        default_factory=list
    )
class GSCActionRow(BaseModel):
    query: str
    action: str
    priority_score: float
    recommendation: str

    current: GSCMetricSnapshot
    previous: GSCMetricSnapshot
    changes: GSCMetricChange


class GSCActionsResponse(BaseModel):
    brand: str
    site_url: str

    current_start_date: date
    current_end_date: date

    previous_start_date: date
    previous_end_date: date

    actions: list[GSCActionRow] = Field(
        default_factory=list
    )
class GA4OverviewResponse(BaseModel):
    brand: str
    property_id: str
    start_date: date
    end_date: date

    active_users: int
    sessions: int
    engaged_sessions: int
    engagement_rate: float
    screen_page_views: int


class GA4LandingPageRow(BaseModel):
    landing_page: str
    sessions: int
    active_users: int
    engaged_sessions: int
    engagement_rate: float
    screen_page_views: int


class GA4LandingPagesResponse(BaseModel):
    brand: str
    property_id: str
    start_date: date
    end_date: date

    rows: list[GA4LandingPageRow] = Field(
        default_factory=list
    )


class GA4ChannelRow(BaseModel):
    channel: str
    sessions: int
    active_users: int
    engaged_sessions: int
    engagement_rate: float


class GA4ChannelsResponse(BaseModel):
    brand: str
    property_id: str
    start_date: date
    end_date: date

    rows: list[GA4ChannelRow] = Field(
        default_factory=list
    )   

class ShopifySelectedOption(BaseModel):
    name: str
    value: str


class ShopifyProductDetail(BaseModel):
    id: str
    numeric_id: str
    title: str
    handle: str
    status: str

    vendor: str | None = None
    product_type: str | None = None
    tags: list[str] = Field(default_factory=list)

    description: str | None = None
    description_html: str | None = None

    online_store_url: str | None = None

    seo_title: str | None = None
    seo_description: str | None = None

    published_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    total_inventory: int | None = None


class ShopifyProductDetailResponse(BaseModel):
    brand: str
    product: ShopifyProductDetail


class ShopifyVariantRow(BaseModel):
    id: str
    numeric_id: str

    title: str
    sku: str | None = None
    barcode: str | None = None

    price: str | None = None
    compare_at_price: str | None = None

    inventory_quantity: int | None = None

    selected_options: list[ShopifySelectedOption] = Field(
        default_factory=list
    )


class ShopifyVariantsResponse(BaseModel):
    brand: str
    product_id: str
    variants: list[ShopifyVariantRow] = Field(
        default_factory=list
    )     

    
class GA4ReferralSourceInspection(BaseModel):
    source: str
    sessions: int
    active_users: int
    engaged_sessions: int
    engagement_rate: float
    landing_page_count: int
    inspection_score: int
    classification: str
    reasons: list[str] = Field(default_factory=list)


class GA4ReferralInspectionPeriod(BaseModel):
    start_date: date
    end_date: date
    sessions: int
    active_users: int
    engaged_sessions: int
    engagement_rate: float
    inspection_score: int
    classification: str
    reasons: list[str] = Field(default_factory=list)
    sources: list[GA4ReferralSourceInspection] = Field(default_factory=list)


class GA4ReferralInspectionResponse(BaseModel):
    inspection: str
    agent_inspected: bool
    current_period: GA4ReferralInspectionPeriod
    previous_period: GA4ReferralInspectionPeriod
    session_change: int
    session_change_percent: float | None = None
    agent_conclusion: str
    human_action_required: bool
