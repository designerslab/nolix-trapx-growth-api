from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key
from app.services.ga4 import GA4Client
from app.services.gsc import GSCClient
from app.services.growth_agent_store import list_events, save_event
from app.growth_agent.keyword_quality import filter_keyword_rows

router = APIRouter(
    prefix="/v1/agents/growth",
    tags=["growth-agent"],
    dependencies=[Depends(require_api_key)],
)


def _row_dict(row):
    return {
        "clicks": float(row.clicks),
        "impressions": float(row.impressions),
        "ctr": float(row.ctr),
        "position": float(row.position),
    }


def _change(current, previous):
    return {
        "clicks": current["clicks"] - previous["clicks"],
        "impressions": current["impressions"] - previous["impressions"],
        "ctr": current["ctr"] - previous["ctr"],
        "position": (
            previous["position"] - current["position"]
            if current["position"] and previous["position"]
            else 0
        ),
    }


def _landing_path(page):
    if not page:
        return None
    if page.startswith("/"):
        return page
    parsed = urlparse(page)
    return parsed.path or "/"


def _ga4_landing(ga4, start, end, page):
    report = ga4.run_report(
        start_date=start,
        end_date=end,
        dimensions=["landingPagePlusQueryString"],
        metrics=[
            "sessions",
            "activeUsers",
            "engagedSessions",
            "engagementRate",
            "screenPageViews",
        ],
        limit=1000,
    )
    wanted = _landing_path(page)
    total = {
        "sessions": 0,
        "active_users": 0,
        "engaged_sessions": 0,
        "engagement_rate": 0.0,
        "screen_page_views": 0,
    }
    matched = 0
    engagement_sum = 0.0
    for row in report.rows:
        landing = row.dimension_values[0].value
        path = landing.split("?", 1)[0]
        if wanted and path != wanted:
            continue
        vals = [v.value for v in row.metric_values]
        total["sessions"] += int(float(vals[0] or 0))
        total["active_users"] += int(float(vals[1] or 0))
        total["engaged_sessions"] += int(float(vals[2] or 0))
        engagement_sum += float(vals[3] or 0)
        total["screen_page_views"] += int(float(vals[4] or 0))
        matched += 1
    if matched:
        total["engagement_rate"] = engagement_sum / matched
    return total


async def _gsc_query_snapshot(gsc, start, end, query, page=None):
    dimensions = ["query", "page"] if page else ["query"]
    result = await gsc.query_performance(
        start_date=start,
        end_date=end,
        dimensions=dimensions,
        row_limit=25000,
    )
    for row in result.rows:
        if not row.keys or row.keys[0].casefold() != query.casefold():
            continue
        if page and len(row.keys) > 1 and row.keys[1] != page:
            continue
        return _row_dict(row)
    return {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}


class TrackActionRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=500)
    page: str | None = None
    action_type: str = Field(min_length=1, max_length=100)
    draft_id: str | None = None
    shopify_article_id: str | None = None
    public_url: str | None = None
    executed_at: date | None = None


@router.post("/{brand}/actions/track")
async def track_action(
    request: TrackActionRequest,
    brand: str = Path(pattern="^(nolix|trapx)$"),
):
    settings = get_settings()
    end = (request.executed_at or date.today()) - timedelta(days=1)
    start = end - timedelta(days=27)
    gsc = GSCClient(settings, brand)
    ga4 = GA4Client(settings, brand)
    gsc_before = await _gsc_query_snapshot(
        gsc, start, end, request.query, request.page
    )
    ga4_before = _ga4_landing(ga4, start, end, request.page)
    return save_event(
        brand=brand,
        kind="action",
        event_id=request.action_id,
        settings=settings,
        payload={
            **request.model_dump(mode="json"),
            "baseline_start_date": start.isoformat(),
            "baseline_end_date": end.isoformat(),
            "baseline": {"gsc": gsc_before, "ga4": ga4_before},
            "status": "tracking",
            "human_approval_required_for_followup_write": True,
        },
    )


@router.get("/{brand}/actions")
async def action_history(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=100, ge=1, le=500),
):
    return {
        "brand": brand,
        "actions": list_events(
            brand=brand,
            kind="action",
            limit=limit,
            settings=get_settings(),
        ),
    }


@router.post("/{brand}/actions/{action_id}/measure")
async def measure_action(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    action_id: str = Path(min_length=1),
    days: int = Query(default=28, ge=7, le=90),
):
    settings = get_settings()
    actions = list_events(
        brand=brand, kind="action", limit=500, settings=settings
    )
    action = next((x for x in actions if x.get("event_id") == action_id), None)
    if not action:
        raise HTTPException(404, "Tracked action not found.")

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    gsc = GSCClient(settings, brand)
    ga4 = GA4Client(settings, brand)
    current_gsc = await _gsc_query_snapshot(
        gsc, start, end, action["query"], action.get("page")
    )
    current_ga4 = _ga4_landing(ga4, start, end, action.get("page"))
    before = action["baseline"]
    gsc_delta = _change(current_gsc, before["gsc"])
    ga4_delta = {
        key: current_ga4[key] - before["ga4"].get(key, 0)
        for key in current_ga4
    }

    score = 0
    score += 1 if gsc_delta["clicks"] > 0 else -1 if gsc_delta["clicks"] < 0 else 0
    score += 1 if gsc_delta["impressions"] > 0 else -1 if gsc_delta["impressions"] < 0 else 0
    score += 1 if gsc_delta["position"] > 0 else -1 if gsc_delta["position"] < 0 else 0
    score += 1 if ga4_delta["engaged_sessions"] > 0 else -1 if ga4_delta["engaged_sessions"] < 0 else 0

    evidence = current_gsc["impressions"] + before["gsc"]["impressions"]
    if evidence < 5:
        outcome, decision = "insufficient_data", "keep_measuring"
    elif score >= 2:
        outcome, decision = "improved", "keep"
    elif score <= -2:
        outcome, decision = "declined", "investigate"
    else:
        outcome, decision = "neutral", "improve"

    measurement = save_event(
        brand=brand,
        kind="measurement",
        settings=settings,
        payload={
            "action_id": action_id,
            "query": action["query"],
            "page": action.get("page"),
            "measurement_start_date": start.isoformat(),
            "measurement_end_date": end.isoformat(),
            "baseline": before,
            "current": {"gsc": current_gsc, "ga4": current_ga4},
            "changes": {"gsc": gsc_delta, "ga4": ga4_delta},
            "outcome": outcome,
            "decision": decision,
            "followup_write_requires_human_approval": True,
        },
    )
    return measurement


@router.get("/{brand}/keywords/new")
async def new_keywords(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    current_days: int = Query(default=7, ge=3, le=31),
    min_impressions: float = Query(default=2, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
):
    settings = get_settings()
    today = date.today()
    current_end = today - timedelta(days=1)
    current_start = current_end - timedelta(days=current_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=current_days - 1)
    gsc = GSCClient(settings, brand)
    current = await gsc.query_performance(
        start_date=current_start,
        end_date=current_end,
        dimensions=["query", "page"],
        row_limit=25000,
    )
    previous = await gsc.query_performance(
        start_date=previous_start,
        end_date=previous_end,
        dimensions=["query"],
        row_limit=25000,
    )
    old = {r.keys[0].casefold() for r in previous.rows if r.keys}
    junk = ("login", "phone number", "email address", "customer service")
    rows = []
    for row in current.rows:
        if not row.keys or row.impressions < min_impressions:
            continue
        q = row.keys[0].strip()
        if q.casefold() in old or any(x in q.casefold() for x in junk):
            continue
        rows.append({
            "query": q,
            "page": row.keys[1] if len(row.keys) > 1 else None,
            **_row_dict(row),
            "classification": "new_query",
            "recommended_next_step": (
                "evaluate_for_action_queue"
                if row.position <= 30 else "monitor"
            ),
        })
    rows = filter_keyword_rows(
        brand,
        rows,
    )    
    rows.sort(
        key=lambda x: (
            x["recommended_next_step"] == "evaluate_for_action_queue",
            x["impressions"],
            -x["position"],
        ),
        reverse=True,
    )
    return {
        "brand": brand,
        "current_period": [current_start.isoformat(), current_end.isoformat()],
        "previous_period": [previous_start.isoformat(), previous_end.isoformat()],
        "keywords": rows[:limit],
    }


@router.get("/{brand}/weekly-report")
async def weekly_report(
    brand: str = Path(pattern="^(nolix|trapx)$"),
):
    settings = get_settings()
    today = date.today()
    current_end = today - timedelta(days=1)
    current_start = current_end - timedelta(days=6)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)

    gsc = GSCClient(settings, brand)
    ga4 = GA4Client(settings, brand)

    current_gsc = await gsc.query_performance(
        start_date=current_start, end_date=current_end,
        dimensions=["query"], row_limit=25000
    )
    previous_gsc = await gsc.query_performance(
        start_date=previous_start, end_date=previous_end,
        dimensions=["query"], row_limit=25000
    )

    def totals(response):
        clicks = sum(r.clicks for r in response.rows)
        impressions = sum(r.impressions for r in response.rows)
        weighted_position = (
            sum(r.position * r.impressions for r in response.rows) / impressions
            if impressions else 0
        )
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr": clicks / impressions if impressions else 0,
            "position": weighted_position,
        }

    cg, pg = totals(current_gsc), totals(previous_gsc)

    def overview(start, end):
        report = ga4.run_report(
            start_date=start, end_date=end, dimensions=[],
            metrics=[
                "activeUsers", "sessions", "engagedSessions",
                "engagementRate", "screenPageViews"
            ], limit=1
        )
        vals = (
            [v.value for v in report.rows[0].metric_values]
            if report.rows else ["0"] * 5
        )
        return {
            "active_users": int(float(vals[0] or 0)),
            "sessions": int(float(vals[1] or 0)),
            "engaged_sessions": int(float(vals[2] or 0)),
            "engagement_rate": float(vals[3] or 0),
            "screen_page_views": int(float(vals[4] or 0)),
        }

    cga, pga = overview(current_start, current_end), overview(previous_start, previous_end)
    new_kw = await new_keywords(
        brand=brand, current_days=7, min_impressions=2, limit=20
    )
    actions = list_events(
        brand=brand, kind="action", limit=20, settings=settings
    )
    measurements = list_events(
        brand=brand, kind="measurement", limit=20, settings=settings
    )

    return {
        "brand": brand,
        "period": {
            "current": [current_start.isoformat(), current_end.isoformat()],
            "previous": [previous_start.isoformat(), previous_end.isoformat()],
        },
        "gsc": {
            "current": cg, "previous": pg, "changes": _change(cg, pg)
        },
        "ga4": {
            "current": cga,
            "previous": pga,
            "changes": {k: cga[k] - pga[k] for k in cga},
        },
        "new_keywords": new_kw["keywords"],
        "tracked_actions": actions,
        "measurements": measurements,
        "report_notes": [
            "GSC and GA4 are measured separately.",
            "A newly created unpublished Shopify article is not treated as a public SEO change.",
            "Follow-up write actions require human approval.",
        ],
    }
