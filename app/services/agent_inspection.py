from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.services.ga4 import GA4Client


def _value(raw: str, value_type=float):
    try:
        return value_type(raw)
    except (TypeError, ValueError):
        return value_type(0)


def _risk_score(
    sessions: int,
    active_users: int,
    engaged_sessions: int,
    engagement_rate: float,
) -> tuple[int, list[str]]:
    """Return a conservative traffic-quality/bot-risk score from 0-100."""
    score = 0
    reasons: list[str] = []

    if sessions >= 20 and active_users <= max(2, int(sessions * 0.25)):
        score += 35
        reasons.append("many sessions are concentrated among relatively few users")

    if sessions >= 10 and engagement_rate < 0.10:
        score += 30
        reasons.append("engagement rate is below 10%")
    elif sessions >= 10 and engagement_rate < 0.25:
        score += 15
        reasons.append("engagement rate is below 25%")

    if sessions >= 10 and engaged_sessions == 0:
        score += 25
        reasons.append("no engaged sessions were recorded")

    if sessions >= 20 and active_users >= int(sessions * 0.80):
        score -= 15
        reasons.append("most sessions came from distinct active users")

    if sessions >= 10 and engagement_rate >= 0.50:
        score -= 15
        reasons.append("at least half of sessions were engaged")

    return max(0, min(100, score)), reasons


def _classification(score: int) -> str:
    if score >= 70:
        return "high_bot_or_low_quality_risk"
    if score >= 40:
        return "medium_bot_or_low_quality_risk"
    return "low_bot_risk"


def inspect_referral_traffic(
    ga4: GA4Client,
    start_date: date,
    end_date: date,
    previous_start_date: date,
    previous_end_date: date,
    limit: int = 1000,
) -> dict:
    """Inspect Referral traffic using GA4 source/medium/landing-page evidence."""

    def collect(period_start: date, period_end: date) -> list[dict]:
        report = ga4.run_report(
            start_date=period_start,
            end_date=period_end,
            dimensions=[
                "sessionSource",
                "sessionMedium",
                "landingPagePlusQueryString",
            ],
            metrics=[
                "sessions",
                "activeUsers",
                "engagedSessions",
                "engagementRate",
            ],
            limit=limit,
        )

        rows: list[dict] = []
        for row in report.rows:
            dims = [v.value for v in row.dimension_values]
            metrics = [v.value for v in row.metric_values]
            medium = dims[1] if len(dims) > 1 else ""
            if medium.lower() != "referral":
                continue

            rows.append(
                {
                    "source": dims[0] if dims else "(not set)",
                    "medium": medium,
                    "landing_page": dims[2] if len(dims) > 2 else "(not set)",
                    "sessions": _value(metrics[0], int),
                    "active_users": _value(metrics[1], int),
                    "engaged_sessions": _value(metrics[2], int),
                    "engagement_rate": _value(metrics[3], float),
                }
            )
        return rows

    current_rows = collect(start_date, end_date)
    previous_rows = collect(previous_start_date, previous_end_date)

    def summarize(rows: list[dict]) -> dict:
        total_sessions = sum(r["sessions"] for r in rows)
        total_users = sum(r["active_users"] for r in rows)
        total_engaged = sum(r["engaged_sessions"] for r in rows)
        weighted_engagement = total_engaged / total_sessions if total_sessions else 0.0

        by_source: dict[str, dict] = defaultdict(
            lambda: {
                "sessions": 0,
                "active_users": 0,
                "engaged_sessions": 0,
                "landing_pages": set(),
            }
        )

        for row in rows:
            item = by_source[row["source"]]
            item["sessions"] += row["sessions"]
            item["active_users"] += row["active_users"]
            item["engaged_sessions"] += row["engaged_sessions"]
            item["landing_pages"].add(row["landing_page"])

        sources = []
        for source, item in by_source.items():
            sessions = item["sessions"]
            engaged = item["engaged_sessions"]
            rate = engaged / sessions if sessions else 0.0
            score, reasons = _risk_score(
                sessions,
                item["active_users"],
                engaged,
                rate,
            )
            sources.append(
                {
                    "source": source,
                    "sessions": sessions,
                    "active_users": item["active_users"],
                    "engaged_sessions": engaged,
                    "engagement_rate": round(rate, 4),
                    "landing_page_count": len(item["landing_pages"]),
                    "inspection_score": score,
                    "classification": _classification(score),
                    "reasons": reasons,
                }
            )

        sources.sort(key=lambda x: x["sessions"], reverse=True)
        overall_score, overall_reasons = _risk_score(
            total_sessions,
            total_users,
            total_engaged,
            weighted_engagement,
        )

        return {
            "sessions": total_sessions,
            "active_users": total_users,
            "engaged_sessions": total_engaged,
            "engagement_rate": round(weighted_engagement, 4),
            "inspection_score": overall_score,
            "classification": _classification(overall_score),
            "reasons": overall_reasons,
            "sources": sources,
        }

    current = summarize(current_rows)
    previous = summarize(previous_rows)
    session_change = current["sessions"] - previous["sessions"]
    pct_change = None
    if previous["sessions"]:
        pct_change = round(session_change / previous["sessions"] * 100, 1)

    human_required = current["inspection_score"] >= 40

    if current["inspection_score"] < 40:
        conclusion = (
            "Referral growth does not show strong bot-like behavior from the available "
            "GA4 engagement/user evidence. Review top sources only if they are unfamiliar "
            "or commercially irrelevant."
        )
    elif current["inspection_score"] < 70:
        conclusion = (
            "Referral traffic has mixed quality signals. The agent should inspect the "
            "highest-volume sources before a human changes GA4 settings."
        )
    else:
        conclusion = (
            "Referral traffic shows strong low-quality/bot-like signals. Human review is "
            "recommended before excluding domains or changing attribution."
        )

    return {
        "inspection": "ga4_referral_traffic",
        "agent_inspected": True,
        "current_period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            **current,
        },
        "previous_period": {
            "start_date": previous_start_date.isoformat(),
            "end_date": previous_end_date.isoformat(),
            **previous,
        },
        "session_change": session_change,
        "session_change_percent": pct_change,
        "agent_conclusion": conclusion,
        "human_action_required": human_required,
    }
