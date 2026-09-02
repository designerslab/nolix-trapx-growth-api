from app.llm_visibility_api import (
    LLMObservation,
    _competitor_mentions,
    _summarize,
    _trust_gaps,
)


def test_default_competitors_detected():
    answer = (
        "Rentokil and Anticimex are mature choices; "
        "Nolix is a newer option."
    )

    mentions = _competitor_mentions(
        "nolix",
        answer,
    )

    assert "Rentokil" in mentions
    assert "Anticimex" in mentions


def test_trust_gap_detection():
    answer = (
        "Nolix is interesting, but public evidence is limited. "
        "Its installed base and service model are unclear, and "
        "independent field validation should be verified."
    )

    gaps = _trust_gaps(
        "nolix",
        answer,
    )

    assert (
        "insufficient_independent_validation"
        in gaps
    )
    assert (
        "limited_installed_base_evidence"
        in gaps
    )
    assert (
        "service_support_uncertainty"
        in gaps
    )


def test_summary_labels_and_competitors():
    observations = [
        LLMObservation(
            model="test",
            prompt="a",
            answer="Nolix is known but not recommended.",
            brand_mentioned=True,
            brand_recommended=False,
            own_domain_cited=False,
            competitor_mentions=[
                "Rentokil"
            ],
            trust_gaps=[
                "insufficient_independent_validation"
            ],
        )
    ]

    summary = _summarize(
        observations
    )

    assert (
        summary.discovery_status
        == "strong"
    )
    assert (
        summary.recommendation_confidence
        == "weak"
    )
    assert (
        summary.first_party_citation_authority
        == "weak"
    )
    assert (
        summary.competitor_mentions[0][0]
        == "Rentokil"
    )
