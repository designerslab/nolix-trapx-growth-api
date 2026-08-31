from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.services.ga4 import GA4Client

# Domains that are known to be internal/admin surfaces rather than genuine
# external referrers. GA4 sometimes attributes internal navigation (e.g.
# storefront <-> admin panel hops) as "referral" traffic.
KNOWN_INTERNAL_DOMAINS = {
    "admin.shopify.com",
    "admin.myshopify.com",
    "checkout.shopify.com",
}


def _value(raw: str, value_type=float):
    try:
        return value_type(raw)
    except (TypeError, ValueError):
        return value_type(0)


def _behavior_risk_score(
    sessions: int,
    active_users: int,
    engaged_sessions: int,
    engagement_rate: float,
) -> tuple[int, list[str]]:
    """Return a conservative traffic-quality/bot-risk score from 0-100, based
    purely on GA4 user/engagement behavior for a source (or a period total).
    """
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


def _known_internal_domain(source: str) -> bool:
    return source.strip().lower() in KNOWN_INTERNAL_DOMAINS


def _source_anomaly_score(
    sessions: int,
    referral_total_sessions: int,
    previous_sessions: int,
    landing_page_count: int,
    source: str,
) -> tuple[int, float, list[str]]:
    """Return a source-anomaly score from 0-100 based on concentration,
    novelty, growth, and landing-page-diversity signals. This is
    behavior-blind: it never looks at engagement rate or active users, so a
    source cannot buy its way to a low score just by looking "engaged".
    """
    score = 0
    reasons: list[str] = []

    share = sessions / referral_total_sessions if referral_total_sessions else 0.0

    if sessions >= 20 and share >= 0.70:
        score += 45
        reasons.append(
            f"source accounts for ~{share:.0%} of all Referral sessions in the period"
        )
    elif sessions >= 10 and share >= 0.40:
        score += 25
        reasons.append(
            f"source accounts for ~{share:.0%} of all Referral sessions in the period"
        )

    is_new_source = previous_sessions == 0
    if sessions >= 20 and is_new_source:
        score += 25
        reasons.append("source did not appear at all in the previous period")

    if not is_new_source and sessions >= previous_sessions * 4:
        score += 20
        reasons.append("sessions increased at least 4x versus the previous period")

    if sessions >= 20 and landing_page_count == 1:
        score += 20
        reasons.append("high-volume traffic lands on only one landing page")

    if _known_internal_domain(source):
        score += 15
        reasons.append("source matches a known internal/admin domain")

    return max(0, min(100, score)), round(share, 4), reasons


def _classification(score: int) -> str:
    if score >= 70:
        return "high_bot_or_low_quality_risk"
    if score >= 40:
        return "medium_bot_or_low_quality_risk"
    return "low_bot_risk"


def _aggregate_by_source(rows: list[dict]) -> dict[str, dict]:
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
    return by_source


def inspect_referral_traffic(
    ga4: GA4Client,
    start_date: date,
    end_date: date,
    previous_start_date: date,
    previous_end_date: date,
    limit: int = 1000,
) -> dict:
    """Inspect Referral traffic using GA4 source/medium/landing-page evidence.

    v2: scoring is split into two independent layers per source:
      - behavior_risk_score: existing GA4 user/engagement-based signal.
      - source_anomaly_score: concentration/novelty/growth/landing-page
        signals that do NOT depend on engagement, so a source can't be
        waved through just because GA4 says it's "engaged".

    The combined inspection_score is 35% behavior + 65% source anomaly,
    reflecting that concentration/novelty patterns are a stronger bot/fraud
    signal than engagement metrics alone (which are easy to spoof or which
    simply reflect a small number of legitimate embedded-browser sessions).
    """

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

    current_by_source = _aggregate_by_source(current_rows)
    previous_by_source = _aggregate_by_source(previous_rows)

    def summarize(
        rows: list[dict],
        by_source: dict[str, dict],
        other_by_source: dict[str, dict],
    ) -> dict:
        total_sessions = sum(r["sessions"] for r in rows)
        total_users = sum(r["active_users"] for r in rows)
        total_engaged = sum(r["engaged_sessions"] for r in rows)
        weighted_engagement = total_engaged / total_sessions if total_sessions else 0.0

        sources = []
        for source, item in by_source.items():
            sessions = item["sessions"]
            engaged = item["engaged_sessions"]
            rate = engaged / sessions if sessions else 0.0
            landing_page_count = len(item["landing_pages"])
            previous_sessions = other_by_source.get(source, {}).get("sessions", 0)

            behavior_score, behavior_reasons = _behavior_risk_score(
                sessions,
                item["active_users"],
                engaged,
                rate,
            )
            anomaly_score, share, anomaly_reasons = _source_anomaly_score(
                sessions,
                total_sessions,
                previous_sessions,
                landing_page_count,
                source,
            )

            combined_score = round(0.35 * behavior_score + 0.65 * anomaly_score)
            combined_score = max(0, min(100, combined_score))

            sources.append(
                {
                    "source": source,
                    "sessions": sessions,
                    "share_of_referral_sessions": share,
                    "previous_sessions": previous_sessions,
                    "active_users": item["active_users"],
                    "engaged_sessions": engaged,
                    "engagement_rate": round(rate, 4),
                    "landing_page_count": landing_page_count,
                    "behavior_risk_score": behavior_score,
                    "source_anomaly_score": anomaly_score,
                    "inspection_score": combined_score,
                    "classification": _classification(combined_score),
                    # NOTE: a source is never classified as legitimate solely
                    # because its behavior_risk_score is low. High engagement
                    # does not offset a high source_anomaly_score.
                    "reasons": behavior_reasons + anomaly_reasons,
                    "agent_followup_required": anomaly_score >= 40,
                }
            )

        sources.sort(key=lambda x: x["sessions"], reverse=True)

        overall_behavior_score, overall_behavior_reasons = _behavior_risk_score(
            total_sessions,
            total_users,
            total_engaged,
            weighted_engagement,
        )
        # Period-level anomaly signal: the worst (highest) anomaly score seen
        # among individual sources, since one concentrated bad actor is what
        # matters, not an average smoothed out by many clean sources.
        overall_anomaly_score = max((s["source_anomaly_score"] for s in sources), default=0)
        overall_combined_score = round(
            0.35 * overall_behavior_score + 0.65 * overall_anomaly_score
        )
        overall_combined_score = max(0, min(100, overall_combined_score))

        return {
            "sessions": total_sessions,
            "active_users": total_users,
            "engaged_sessions": total_engaged,
            "engagement_rate": round(weighted_engagement, 4),
            "behavior_risk_score": overall_behavior_score,
            "source_anomaly_score": overall_anomaly_score,
            "inspection_score": overall_combined_score,
            "classification": _classification(overall_combined_score),
            "reasons": overall_behavior_reasons,
            "sources": sources,
        }

    current = summarize(current_rows, current_by_source, previous_by_source)
    # Previous period has no "period before it" in this call, so every source
    # in it is scored with previous_sessions=0 for its own anomaly context.
    previous = summarize(previous_rows, previous_by_source, {})

    session_change = current["sessions"] - previous["sessions"]
    pct_change = None
    if previous["sessions"]:
        pct_change = round(session_change / previous["sessions"] * 100, 1)

    agent_followup_required = any(
        s["agent_followup_required"] for s in current["sources"]
    )

    if current["inspection_score"] < 40:
        conclusion = (
            "Referral growth does not show strong bot-like or anomalous-source "
            "behavior from the available GA4 evidence. Review top sources only "
            "if they are unfamiliar or commercially irrelevant."
        )
    elif current["inspection_score"] < 70:
        conclusion = (
            "Referral traffic has mixed quality/anomaly signals. The agent "
            "should inspect the highest-scoring sources before a human "
            "changes GA4 settings."
        )
    else:
        conclusion = (
            "Referral traffic shows strong low-quality/bot-like or anomalous "
            "source signals. The agent should attempt source/domain "
            "verification before any human changes attribution or exclusion "
            "settings."
        )

    # human_action_required intentionally stays False here: per policy, a
    # human is only pulled in after the agent has attempted source/domain
    # verification (WHOIS, reverse DNS, known-network lookups, etc.), which
    # this function does not perform. agent_followup_required signals that
    # such verification should happen next.
    human_action_required = False

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
        "agent_followup_required": agent_followup_required,
        "human_action_required": human_action_required,
    }