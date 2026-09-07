from datetime import date

from app.content_opportunity_api import (
    _business_relevance,
    _page_path,
    _resolve_periods,
    _strategic_intent,
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


def test_business_relevance_core_nolix_topic():
    result = _business_relevance(
        "nolix",
        "commercial water leak detection",
        "/blogs/news/leak-monitoring",
    )

    assert result.level == "high"
    assert result.score > 0
    assert "leak monitoring" in result.matched_themes


def test_business_relevance_discount_broad_repair():
    result = _business_relevance(
        "nolix",
        "how to repair water damage",
        "/blogs/news/water-damage-repair",
    )

    assert result.level == "low"
    assert result.score < 0


def test_strategic_intent_commercial():
    assert (
        _strategic_intent(
            "commercial facility leak detection sensors"
        )
        == "commercial"
    )


def test_strategic_intent_consumer():
    assert (
        _strategic_intent(
            "water damage not covered by insurance"
        )
        == "consumer_informational"
    )


def test_strategic_intent_product_nav():
    assert (
        _strategic_intent("pipex")
        == "navigational"
    )
