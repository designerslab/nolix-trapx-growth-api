from datetime import date

from app.content_opportunity_api import (
    _page_path,
    _priority_score,
    _resolve_periods,
)


def test_page_path_normalizes_absolute_url():
    assert (
        _page_path("https://nolix.ai/pages/example/?utm_source=test")
        == "/pages/example"
    )


def test_resolve_periods_uses_equal_previous_window():
    current_start, current_end, previous_start, previous_end = _resolve_periods(
        date(2026, 8, 1),
        date(2026, 8, 28),
        None,
        None,
    )

    assert current_start == date(2026, 8, 1)
    assert current_end == date(2026, 8, 28)
    assert previous_start == date(2026, 7, 4)
    assert previous_end == date(2026, 7, 31)


def test_priority_score_rewards_page_one_opportunity_and_geo_gap():
    score = _priority_score(
        current={
            "impressions": 20,
            "position": 8,
            "ctr": 0.02,
        },
        previous={
            "impressions": 10,
            "position": 12,
        },
        engagement={
            "sessions": 10,
            "engagement_rate": 0.30,
        },
        technical_issues=[],
        geo={
            "unbranded_mention_rate": 61.9,
            "unbranded_recommendation_rate": 33.3,
            "unbranded_own_domain_citation_rate": 14.3,
        },
        product_matches=[],
    )

    assert score >= 80
    assert score <= 100
