from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm_visibility_api import _read_baselines
from app.security import require_api_key
from app.services.ga4 import GA4Client
from app.services.gsc import GSCClient
from app.services.shopify import ShopifyClient
from app.technical_audit_api import get_technical_audit

router = APIRouter()


class BusinessRelevance(BaseModel):
    level: str
    score: float
    matched_themes: list[str] = Field(default_factory=list)
    negative_themes: list[str] = Field(default_factory=list)
    reason: str


class BusinessTheme(BaseModel):
    name: str
    terms: list[str]
    weight: float


class ContentOpportunity(BaseModel):
    priority: int
    seo_score: float
    strategic_score: float
    confidence: str
    strategic_intent: str
    opportunity_type: str
    query: str
    page: str | None = None
    action: str
    why: str
    business_relevance: BusinessRelevance
    search_evidence: dict = Field(default_factory=dict)
    engagement_evidence: dict = Field(default_factory=dict)
    geo_evidence: dict = Field(default_factory=dict)
    technical_evidence: list[dict] = Field(default_factory=list)
    product_truth: dict = Field(default_factory=dict)


class ContentOpportunityResponse(BaseModel):
    brand: str
    generated_at: str
    current_start_date: date
    current_end_date: date
    previous_start_date: date
    previous_end_date: date
    latest_baseline_id: str | None = None
    source_status: dict[str, str] = Field(default_factory=dict)
    seo_opportunities: list[ContentOpportunity] = Field(default_factory=list)
    strategic_opportunities: list[ContentOpportunity] = Field(default_factory=list)


BRANDED_TERMS = {
    "nolix": {
        "nolix",
        "nolix ai",
        "nolix.ai",
        "nolix.top",
        "nomorlix",
        "noolix",
        "noelix",
        "nowlicx",
        "nimilix",
        "notilex",
        "noliks",
    },
    "trapx": {
        "trapx",
        "trap x",
        "trapx.io",
    },
}


LOW_VALUE_QUERY_TERMS = {
    "nolix",
    "nolix ai",
    "nolix.ai",
    "trapx",
    "trap x",
    "trafixpro",
    "track lonox ai",
    "login",
    "customer service",
    "phone number",
    "email address",
}


PRODUCT_NAV_TERMS = {
    "nolix",
    "trapx",
    "trap x",
    "pipex",
    "dripx",
    "trafixpro",
}


LOW_COMMERCIAL_INTENT = [
    "insurance",
    "covered by insurance",
    "repair",
    "repairing",
    "damage repair",
    "home office",
    "gadgets",
    "diy",
]


COMMERCIAL_CONTEXT_TERMS = {
    "commercial",
    "facility",
    "facilities",
    "building",
    "buildings",
    "warehouse",
    "data center",
    "hospital",
    "infrastructure",
    "industrial",
    "business",
    "enterprise",
    "remote monitoring",
    "monitoring",
    "detection",
    "sensor",
    "sensors",
    "iot",
}


CONSUMER_CONTEXT_TERMS = {
    "rented house",
    "tenant",
    "landlord",
    "insurance",
    "covered by insurance",
    "repair",
    "repairing",
    "diy",
    "home office",
    "who is responsible",
    "wood damage",
}


BUSINESS_THEMES = {
    "nolix": [
        BusinessTheme(
            name="rodent monitoring",
            terms=[
                "rodent",
                "mouse",
                "mice",
                "pest monitoring",
                "rodent detection",
            ],
            weight=20,
        ),
        BusinessTheme(
            name="leak monitoring",
            terms=[
                "leak detection",
                "water leak",
                "water monitoring",
                "moisture monitoring",
            ],
            weight=20,
        ),
        BusinessTheme(
            name="pipe and cable monitoring",
            terms=[
                "pipe monitoring",
                "cable monitoring",
                "pipe sensor",
                "cable sensor",
            ],
            weight=20,
        ),
        BusinessTheme(
            name="facility monitoring",
            terms=[
                "facility monitoring",
                "infrastructure monitoring",
                "building monitoring",
                "iot monitoring",
                "facility risk",
            ],
            weight=18,
        ),
        BusinessTheme(
            name="critical facilities",
            terms=[
                "data center",
                "hospital",
                "warehouse",
                "commercial facility",
                "critical facility",
            ],
            weight=15,
        ),
    ],
    "trapx": [
        BusinessTheme(
            name="rodent monitoring",
            terms=[
                "rodent",
                "mouse",
                "mice",
                "pest monitoring",
                "rodent detection",
            ],
            weight=20,
        ),
        BusinessTheme(
            name="commercial pest monitoring",
            terms=[
                "warehouse",
                "food facility",
                "commercial facility",
                "remote monitoring",
            ],
            weight=18,
        ),
    ],
}


STOPWORDS = {
    "what",
    "which",
    "with",
    "from",
    "that",
    "this",
    "best",
    "good",
    "smart",
    "system",
    "systems",
    "solution",
    "solutions",
    "commercial",
    "product",
    "products",
}


def _default_current_end() -> date:
    return date.today() - timedelta(days=1)


def _resolve_periods(
    current_start_date: date | None,
    current_end_date: date | None,
    previous_start_date: date | None,
    previous_end_date: date | None,
) -> tuple[date, date, date, date]:
    current_end = current_end_date or _default_current_end()
    current_start = current_start_date or (
        current_end - timedelta(days=27)
    )

    if current_end < current_start:
        raise ValueError(
            "current_end_date must be on or after current_start_date"
        )

    period_days = (current_end - current_start).days + 1

    previous_end = previous_end_date or (
        current_start - timedelta(days=1)
    )
    previous_start = previous_start_date or (
        previous_end - timedelta(days=period_days - 1)
    )

    if previous_end < previous_start:
        raise ValueError(
            "previous_end_date must be on or after previous_start_date"
        )

    return (
        current_start,
        current_end,
        previous_start,
        previous_end,
    )


def _page_path(value: str | None) -> str | None:
    if not value:
        return None

    parsed = urlparse(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value

    path = (
        path.split("?", 1)[0]
        .split("#", 1)[0]
        .strip()
    )

    if not path:
        return "/"

    if not path.startswith("/"):
        path = "/" + path

    return path.rstrip("/") or "/"


def _normalize_query(query: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        query.lower()
        .strip()
        .replace("-", " ")
        .replace(".", " "),
    )


def _looks_like_brand_typo(
    brand: str,
    query: str,
) -> bool:
    normalized = _normalize_query(query)

    # Only treat short single-token queries as possible brand typos.
    # This avoids suppressing legitimate long-tail queries.
    if " " in normalized:
        return False

    if not 4 <= len(normalized) <= 10:
        return False

    canonical = {
        "nolix": "nolix",
        "trapx": "trapx",
    }.get(brand)

    if not canonical:
        return False

    similarity = SequenceMatcher(
        None,
        normalized,
        canonical,
    ).ratio()

    return similarity >= 0.50


def _is_branded_query(
    brand: str,
    query: str,
) -> bool:
    normalized = (
        query.lower()
        .strip()
        .replace("-", " ")
    )

    return any(
        term in normalized
        for term in BRANDED_TERMS.get(
            brand,
            set(),
        )
    )


def _is_low_value_query(query: str) -> bool:
    normalized = _normalize_query(query)

    return normalized in {
        _normalize_query(term)
        for term in LOW_VALUE_QUERY_TERMS
    }

def _looks_like_brand_typo(
    brand: str,
    query: str,
) -> bool:
    normalized = _normalize_query(query)

    canonical = {
        "nolix": "nolix",
        "trapx": "trapx",
    }.get(brand)

    if not canonical:
        return False

    tokens = normalized.split()

    for token in tokens:
        if not 4 <= len(token) <= 10:
            continue

        similarity = SequenceMatcher(
            None,
            token,
            canonical,
        ).ratio()

        if similarity >= 0.50:
            return True

    return False
def _looks_navigational_or_garbled(query: str) -> bool:
    normalized = _normalize_query(query)

    suspicious_terms = {
        "nolix",
        "trapx",
        "trafixpro",
        "lonox",
    }

    tokens = set(
        normalized.split()
    )

    return bool(
        tokens & suspicious_terms
    )


def _strategic_intent(query: str) -> str:
    normalized = _normalize_query(query)

    if normalized in {
        _normalize_query(term)
        for term in PRODUCT_NAV_TERMS
    }:
        return "navigational"

    if any(
        term in normalized
        for term in CONSUMER_CONTEXT_TERMS
    ):
        return "consumer_informational"

    if any(
        term in normalized
        for term in COMMERCIAL_CONTEXT_TERMS
    ):
        return "commercial"

    return "general_informational"


def _is_content_page(page: str | None) -> bool:
    path = _page_path(page)

    if not path:
        return False

    return path not in {
        "/search",
        "/account",
        "/cart",
        "/checkout",
    }


def _row_key(
    query: str,
    page: str | None,
) -> tuple[str, str]:
    return (
        query.strip().lower(),
        _page_path(page) or "",
    )


def _metric_snapshot(row) -> dict:
    return {
        "clicks": round(float(row.clicks), 2),
        "impressions": round(float(row.impressions), 2),
        "ctr": round(float(row.ctr), 4),
        "position": round(float(row.position), 2),
    }


def _ga4_rows(report) -> dict[str, dict]:
    result: dict[str, dict] = {}

    for row in getattr(report, "rows", []) or []:
        if not row.dimension_values:
            continue

        landing_page = (
            _page_path(
                row.dimension_values[0].value
            )
            or "/"
        )

        values = [
            item.value
            for item in row.metric_values
        ]

        while len(values) < 5:
            values.append("0")

        result[landing_page] = {
            "sessions": int(float(values[0] or 0)),
            "active_users": int(float(values[1] or 0)),
            "engaged_sessions": int(float(values[2] or 0)),
            "engagement_rate": round(
                float(values[3] or 0),
                4,
            ),
            "screen_page_views": int(float(values[4] or 0)),
        }

    return result


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[a-z0-9]+",
            value.lower(),
        )
        if (
            len(token) >= 4
            and token not in STOPWORDS
        )
    }


def _query_signature(query: str) -> frozenset[str]:
    return frozenset(
        _tokens(query)
    )


def _matched_products(
    brand: str,
    query: str,
    products: list,
) -> list[dict]:
    query_tokens = _tokens(query)

    query_tokens -= _tokens(brand)
    query_tokens -= {
        "nolix",
        "trapx",
        "trap",
    }

    if not query_tokens:
        return []

    matches = []

    for product in products:
        title_tokens = _tokens(
            product.title
        )

        overlap = sorted(
            query_tokens & title_tokens
        )

        if not overlap:
            continue

        distinctive_terms = {
            "rodent",
            "mouse",
            "mice",
            "leak",
            "moisture",
            "pipe",
            "cable",
            "gateway",
        }

        has_distinctive_match = bool(
            set(overlap)
            & distinctive_terms
        )

        if (
            len(overlap) < 2
            and not has_distinctive_match
        ):
            continue

        matches.append(
            {
                "id": product.id,
                "title": product.title,
                "handle": product.handle,
                "status": product.status,
                "matched_terms": overlap,
            }
        )

    return matches[:5]


def _technical_by_path(
    audit,
) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}

    if audit is None:
        return result

    for page in audit.pages:
        path = _page_path(
            page.url
        )

        if not path:
            continue

        result[path] = [
            issue.model_dump()
            for issue in page.issues
            if issue.severity in {
                "critical",
                "high",
                "medium",
            }
        ]

    return result


def _geo_summary(
    baseline: dict | None,
) -> dict:
    if not baseline:
        return {}

    unbranded = (
        baseline.get("unbranded")
        or {}
    )

    overall = (
        baseline.get("overall")
        or {}
    )

    return {
        "baseline_id": baseline.get("baseline_id"),
        "status": baseline.get("status"),
        "unbranded_mention_rate": unbranded.get("mention_rate"),
        "unbranded_recommendation_rate": unbranded.get(
            "recommendation_rate"
        ),
        "unbranded_own_domain_citation_rate": unbranded.get(
            "own_domain_citation_rate"
        ),
        "first_party_citation_authority": overall.get(
            "first_party_citation_authority"
        ),
        "trust_gaps": overall.get("trust_gaps") or [],
    }


def _business_relevance(
    brand: str,
    query: str,
    page: str | None,
) -> BusinessRelevance:
    text = f"{query} {page or ''}".lower()
    intent = _strategic_intent(query)

    matches: list[str] = []
    negatives: list[str] = []
    score = 0.0

    for theme in BUSINESS_THEMES.get(
        brand,
        [],
    ):
        if any(
            term in text
            for term in theme.terms
        ):
            matches.append(
                theme.name
            )

            score = max(
                score,
                theme.weight,
            )

    for term in LOW_COMMERCIAL_INTENT:
        if term in text:
            negatives.append(term)

    if intent == "consumer_informational":
        score = min(score, 0)
        score -= 10

    elif intent == "general_informational":
        score = min(score, 5)

    score = max(
        -10.0,
        min(
            20.0,
            score,
        ),
    )

    if score >= 15:
        level = "high"
    elif score > 0:
        level = "medium"
    elif score < 0:
        level = "low"
    else:
        level = "neutral"

    if intent == "commercial" and matches:
        reason = (
            "Commercial intent matches configured themes: "
            + ", ".join(matches)
        )
    elif intent == "consumer_informational":
        reason = (
            "Consumer/informational intent; "
            "commercial relevance is discounted."
        )
    elif matches:
        reason = (
            "Topic overlaps configured themes, "
            "but commercial intent is not established."
        )
    else:
        reason = (
            "No configured commercial theme matched."
        )

    return BusinessRelevance(
        level=level,
        score=score,
        matched_themes=matches,
        negative_themes=negatives,
        reason=reason,
    )


def _base_seo_score(
    current: dict,
    previous: dict,
    engagement: dict,
    technical_issues: list[dict],
    geo: dict,
    product_matches: list[dict],
) -> float:
    impressions = float(
        current.get("impressions")
        or 0
    )
    position = float(
        current.get("position")
        or 0
    )
    ctr = float(
        current.get("ctr")
        or 0
    )

    score = min(
        impressions,
        30.0,
    )

    if 4 <= position <= 10:
        score += 30
    elif 10 < position <= 20:
        score += 25
    elif 20 < position <= 40:
        score += 15
    elif position > 40:
        score += 5
    elif 0 < position < 4:
        score += 10

    if (
        impressions >= 10
        and ctr < 0.03
    ):
        score += 10

    previous_impressions = float(
        previous.get("impressions")
        or 0
    )
    previous_position = float(
        previous.get("position")
        or 0
    )

    if impressions > previous_impressions:
        score += min(
            10.0,
            impressions - previous_impressions,
        )

    if (
        previous_position > 0
        and position > 0
        and position < previous_position
    ):
        score += min(
            10.0,
            previous_position - position,
        )

    sessions = int(
        engagement.get("sessions")
        or 0
    )
    engagement_rate = float(
        engagement.get("engagement_rate")
        or 0
    )

    if (
        sessions >= 5
        and engagement_rate < 0.35
    ):
        score += 10
    elif (
        sessions >= 5
        and engagement_rate >= 0.50
    ):
        score += 6

    severity_points = {
        "critical": 20,
        "high": 15,
        "medium": 8,
    }

    score += min(
        20,
        sum(
            severity_points.get(
                item.get("severity"),
                0,
            )
            for item in technical_issues
        ),
    )

    if geo:
        if float(
            geo.get("unbranded_mention_rate")
            or 0
        ) < 70:
            score += 5

        if float(
            geo.get("unbranded_recommendation_rate")
            or 0
        ) < 40:
            score += 5

        if float(
            geo.get("unbranded_own_domain_citation_rate")
            or 0
        ) < 20:
            score += 5

    if product_matches:
        score += 5

    return round(
        min(
            score,
            100.0,
        ),
        1,
    )


def _seo_score(
    base_score: float,
    business_relevance: BusinessRelevance,
) -> float:
    adjustment = 0.0

    if business_relevance.score > 0:
        adjustment = min(
            5.0,
            business_relevance.score * 0.25,
        )
    elif business_relevance.score < 0:
        adjustment = max(
            -10.0,
            business_relevance.score,
        )

    return round(
        min(
            100.0,
            max(
                0.0,
                base_score + adjustment,
            ),
        ),
        1,
    )


def _strategic_score(
    current: dict,
    engagement: dict,
    geo: dict,
    technical_issues: list[dict],
    product_matches: list[dict],
    business_relevance: BusinessRelevance,
    strategic_intent: str,
) -> float:
    score = 0.0

    if strategic_intent == "commercial":
        score += 30
    elif strategic_intent == "general_informational":
        score += 5
    elif strategic_intent == "consumer_informational":
        score -= 20

    if business_relevance.score > 0:
        score += min(
            25.0,
            business_relevance.score * 1.25,
        )
    elif business_relevance.score < 0:
        score += business_relevance.score

    if product_matches:
        score += 15

    if geo:
        if float(
            geo.get("unbranded_recommendation_rate")
            or 0
        ) < 40:
            score += 10

        if float(
            geo.get("unbranded_own_domain_citation_rate")
            or 0
        ) < 20:
            score += 10

    impressions = float(
        current.get("impressions")
        or 0
    )
    position = float(
        current.get("position")
        or 0
    )

    if impressions >= 20:
        score += 10
    elif impressions >= 5:
        score += 5
    elif impressions > 0:
        score += 2

    if 4 <= position <= 20:
        score += 10
    elif 20 < position <= 40:
        score += 5

    sessions = int(
        engagement.get("sessions")
        or 0
    )

    if sessions >= 10:
        score += 5

    if technical_issues:
        score += min(
            5.0,
            len(technical_issues) * 2.0,
        )

    return round(
        min(
            100.0,
            max(
                0.0,
                score,
            ),
        ),
        1,
    )


def _confidence(
    current: dict,
    engagement: dict,
    technical_issues: list[dict],
    product_matches: list[dict],
) -> str:
    evidence = 0

    if float(
        current.get("impressions")
        or 0
    ) >= 10:
        evidence += 2
    elif float(
        current.get("impressions")
        or 0
    ) >= 3:
        evidence += 1

    if int(
        engagement.get("sessions")
        or 0
    ) >= 5:
        evidence += 1

    if technical_issues:
        evidence += 1

    if product_matches:
        evidence += 1

    if evidence >= 4:
        return "high"
    if evidence >= 2:
        return "medium"
    return "low"


def _action_for(
    query: str,
    page: str | None,
    current: dict,
    engagement: dict,
    technical_issues: list[dict],
    geo: dict,
    product_matches: list[dict],
) -> tuple[str, str, str]:
    position = float(
        current.get("position")
        or 0
    )
    impressions = float(
        current.get("impressions")
        or 0
    )
    ctr = float(
        current.get("ctr")
        or 0
    )

    sessions = int(
        engagement.get("sessions")
        or 0
    )
    engagement_rate = float(
        engagement.get("engagement_rate")
        or 0
    )

    if technical_issues:
        action_type = (
            "fix_and_strengthen_existing"
        )
        action = (
            "Fix the medium/high technical issues on "
            f"{page or 'the ranking page'}, then strengthen it "
            f"around the intent '{query}'."
        )

    elif 4 <= position <= 20:
        action_type = "optimize_existing"
        action = (
            f"Expand {page or 'the ranking page'} for '{query}', "
            "improve intent coverage, internal links, and snippet copy."
        )

    elif (
        impressions >= 10
        and position > 20
    ):
        action_type = "build_or_expand_topic"
        action = (
            f"Create or substantially expand a focused resource for '{query}' "
            "and link it from the closest relevant product/use-case pages."
        )

    elif (
        impressions >= 10
        and ctr < 0.03
    ):
        action_type = "improve_snippet"
        action = (
            f"Rewrite title/meta and opening copy for '{query}' "
            "while preserving verified positioning."
        )

    else:
        action_type = "test_content_improvement"
        action = (
            f"Improve the existing content coverage for '{query}' "
            "and measure GSC response."
        )

    reasons = []

    if impressions:
        reasons.append(
            f"{int(impressions)} current-period GSC impressions"
        )

    if position:
        reasons.append(
            f"average position {position:.1f}"
        )

    if sessions >= 5:
        reasons.append(
            f"{sessions} GA4 sessions at "
            f"{engagement_rate:.1%} engagement"
        )

    if technical_issues:
        reasons.append(
            f"{len(technical_issues)} medium/high technical findings"
        )

    if (
        geo
        and float(
            geo.get("unbranded_own_domain_citation_rate")
            or 0
        ) < 20
    ):
        reasons.append(
            "weak unbranded first-party GEO citation authority"
        )

    if product_matches:
        reasons.append(
            "related active catalog evidence exists"
        )

    return (
        action_type,
        action,
        "; ".join(reasons)
        or "Limited multi-source evidence",
    )


def _dedupe_and_rank(
    candidates: list[ContentOpportunity],
    limit: int,
    score_field: str,
) -> list[ContentOpportunity]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            getattr(
                item,
                score_field,
            ),
            item.search_evidence.get(
                "current",
                {},
            ).get(
                "impressions",
                0,
            ),
        ),
        reverse=True,
    )

    selected = []
    seen_signatures = set()

    for candidate in ordered:
        signature = _query_signature(
            candidate.query
        )

        if (
            signature
            and signature in seen_signatures
        ):
            continue

        if signature:
            seen_signatures.add(
                signature
            )

        selected.append(
            candidate.model_copy(
                deep=True
            )
        )

        if len(selected) >= limit:
            break

    for index, item in enumerate(
        selected,
        start=1,
    ):
        item.priority = index

    return selected


@router.get(
    "/v1/brands/{brand}/content-opportunities",
    response_model=ContentOpportunityResponse,
    dependencies=[
        Depends(
            require_api_key
        )
    ],
    tags=[
        "content-opportunities"
    ],
    operation_id="get_content_opportunities",
)
async def get_content_opportunities(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    current_start_date: date | None = Query(
        default=None
    ),
    current_end_date: date | None = Query(
        default=None
    ),
    previous_start_date: date | None = Query(
        default=None
    ),
    previous_end_date: date | None = Query(
        default=None
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    min_impressions: float = Query(
        default=1,
        ge=0,
    ),
    max_pages: int = Query(
        default=25,
        ge=1,
        le=50,
    ),
) -> ContentOpportunityResponse:
    (
        current_start,
        current_end,
        previous_start,
        previous_end,
    ) = _resolve_periods(
        current_start_date,
        current_end_date,
        previous_start_date,
        previous_end_date,
    )

    settings = get_settings()
    source_status: dict[str, str] = {}

    async def load_gsc(
        start: date,
        end: date,
    ):
        try:
            response = await GSCClient(
                settings,
                brand,
            ).query_performance(
                start_date=start,
                end_date=end,
                dimensions=[
                    "query",
                    "page",
                ],
                row_limit=5000,
            )

            return response

        except Exception as error:
            source_status["gsc"] = (
                f"error:"
                f"{type(error).__name__}"
            )
            return None

    async def load_ga4():
        try:
            client = GA4Client(
                settings,
                brand,
            )

            report = await asyncio.to_thread(
                client.run_report,
                current_start,
                current_end,
                [
                    "landingPage"
                ],
                [
                    "sessions",
                    "activeUsers",
                    "engagedSessions",
                    "engagementRate",
                    "screenPageViews",
                ],
                1000,
            )

            source_status[
                "ga4"
            ] = "ok"

            return report

        except Exception as error:
            source_status["ga4"] = (
                f"error:"
                f"{type(error).__name__}"
            )
            return None

    async def load_products():
        try:
            response = await ShopifyClient(
                settings,
                brand,
            ).list_products(
                limit=250
            )

            source_status[
                "product_truth"
            ] = "ok"

            return response.products

        except Exception as error:
            source_status[
                "product_truth"
            ] = (
                f"error:"
                f"{type(error).__name__}"
            )
            return []

    async def load_technical():
        try:
            response = await get_technical_audit(
                brand=brand,
                max_pages=max_pages,
                max_internal_links=0,
            )

            source_status[
                "technical_audit"
            ] = "ok"

            return response

        except Exception as error:
            source_status[
                "technical_audit"
            ] = (
                f"error:"
                f"{type(error).__name__}"
            )
            return None

    async def load_geo():
        try:
            baselines = await asyncio.to_thread(
                _read_baselines,
                brand,
                10,
            )

            complete = [
                item
                for item in baselines
                if item.get(
                    "status"
                )
                == "complete"
            ]

            source_status[
                "geo"
            ] = (
                "ok"
                if complete
                else "no_complete_baseline"
            )

            return (
                complete[0]
                if complete
                else None
            )

        except Exception as error:
            source_status["geo"] = (
                f"error:"
                f"{type(error).__name__}"
            )
            return None

    (
        current_gsc,
        previous_gsc,
        ga4_report,
        products,
        audit,
        baseline,
    ) = await asyncio.gather(
        load_gsc(
            current_start,
            current_end,
        ),
        load_gsc(
            previous_start,
            previous_end,
        ),
        load_ga4(),
        load_products(),
        load_technical(),
        load_geo(),
    )

    if (
        current_gsc is not None
        and previous_gsc is not None
    ):
        source_status[
            "gsc"
        ] = "ok"

    current_rows = (
        current_gsc.rows
        if current_gsc is not None
        else []
    )

    previous_rows = (
        previous_gsc.rows
        if previous_gsc is not None
        else []
    )

    previous_map = {}

    for row in previous_rows:
        if len(
            row.keys
        ) < 2:
            continue

        previous_map[
            _row_key(
                row.keys[0],
                row.keys[1],
            )
        ] = _metric_snapshot(
            row
        )

    engagement_by_path = (
        _ga4_rows(
            ga4_report
        )
        if ga4_report is not None
        else {}
    )

    technical_by_path = (
        _technical_by_path(
            audit
        )
    )

    geo = _geo_summary(
        baseline
    )

    candidates: list[
        ContentOpportunity
    ] = []

    for row in current_rows:
        if len(
            row.keys
        ) < 2:
            continue

        query = (
            row.keys[0]
            .strip()
        )

        page = (
            row.keys[1]
            .strip()
            or None
        )

        if _is_branded_query(
            brand,
            query,
        ):
            continue

        if _is_low_value_query(
            query
        ):
            continue

        if _looks_navigational_or_garbled(
            query
        ):
            continue

        if _looks_like_brand_typo(
            brand,
            query,
        ):
            continue

        strategic_intent = (
            _strategic_intent(
                query
            )
        )

        if strategic_intent == "navigational":
            continue

        if not _is_content_page(
            page
        ):
            continue

        current = _metric_snapshot(
            row
        )

        if (
            current[
                "impressions"
            ]
            < min_impressions
        ):
            continue

        path = _page_path(
            page
        )

        previous = previous_map.get(
            _row_key(
                query,
                page,
            ),
            {},
        )

        engagement = (
            engagement_by_path.get(
                path or "",
                {},
            )
        )

        technical_issues = (
            technical_by_path.get(
                path or "",
                [],
            )
        )

        product_matches = (
            _matched_products(
                brand,
                query,
                products,
            )
        )

        business_relevance = (
            _business_relevance(
                brand,
                query,
                page,
            )
        )

        base_score = _base_seo_score(
            current,
            previous,
            engagement,
            technical_issues,
            geo,
            product_matches,
        )

        seo_score = _seo_score(
            base_score,
            business_relevance,
        )

        strategic_score = _strategic_score(
            current,
            engagement,
            geo,
            technical_issues,
            product_matches,
            business_relevance,
            strategic_intent,
        )

        (
            opportunity_type,
            action,
            why,
        ) = _action_for(
            query,
            page,
            current,
            engagement,
            technical_issues,
            geo,
            product_matches,
        )

        candidates.append(
            ContentOpportunity(
                priority=0,
                seo_score=seo_score,
                strategic_score=strategic_score,
                confidence=_confidence(
                    current,
                    engagement,
                    technical_issues,
                    product_matches,
                ),
                strategic_intent=(
                    strategic_intent
                ),
                opportunity_type=(
                    opportunity_type
                ),
                query=query,
                page=page,
                action=action,
                why=why,
                business_relevance=(
                    business_relevance
                ),
                search_evidence={
                    "current": current,
                    "previous": previous,
                },
                engagement_evidence=(
                    engagement
                ),
                geo_evidence=geo,
                technical_evidence=(
                    technical_issues
                ),
                product_truth={
                    "matched_catalog_products": (
                        product_matches
                    ),
                    "claim_policy": (
                        "Catalog matches verify product existence only; "
                        "performance, ROI, certifications, deployment scale, "
                        "and suitability require separate evidence."
                    ),
                },
            )
        )

    seo_opportunities = _dedupe_and_rank(
        candidates,
        limit,
        "seo_score",
    )

    strategic_candidates = [
        item
        for item in candidates
        if (
            item.strategic_intent == "commercial"
            or item.business_relevance.score >= 15
        )
    ]

    strategic_opportunities = _dedupe_and_rank(
        strategic_candidates,
        limit,
        "strategic_score",
    )

    return ContentOpportunityResponse(
        brand=brand,
        generated_at=(
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        current_start_date=(
            current_start
        ),
        current_end_date=(
            current_end
        ),
        previous_start_date=(
            previous_start
        ),
        previous_end_date=(
            previous_end
        ),
        latest_baseline_id=(
            baseline.get(
                "baseline_id"
            )
            if baseline
            else None
        ),
        source_status=(
            source_status
        ),
        seo_opportunities=(
            seo_opportunities
        ),
        strategic_opportunities=(
            strategic_opportunities
        ),
    )
