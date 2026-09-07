from app.content_opportunity_api import (
    _looks_like_brand_typo,
    _strategic_intent,
)


def test_brand_typo_filter_nolix_variants():
    assert _looks_like_brand_typo("nolix", "noalix")
    assert _looks_like_brand_typo("nolix", "ilinix")


def test_brand_typo_filter_does_not_block_real_query():
    assert not _looks_like_brand_typo(
        "nolix",
        "flood damage",
    )


def test_strategic_intent_commercial():
    assert (
        _strategic_intent(
            "commercial facility leak detection sensors"
        )
        == "commercial"
    )
