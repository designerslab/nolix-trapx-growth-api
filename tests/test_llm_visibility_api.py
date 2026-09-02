from app.llm_visibility_api import (
    CitationSource,
    LLMObservation,
    _brand_mentioned,
    _brand_recommended,
    _citation_domain,
    _extract_openai_response,
    _own_domain_cited,
    _summarize,
)


def test_brand_mention():
    assert _brand_mentioned(
        "nolix",
        "Nolix offers connected monitoring products.",
    )


def test_brand_recommendation():
    assert _brand_recommended(
        "nolix",
        "For commercial facilities, Nolix can be a good option.",
    )


def test_citation_domain():
    assert _citation_domain(
        "https://www.nolix.ai/products/example"
    ) == "nolix.ai"


def test_extract_openai_response():
    data = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"queries": ["smart rodent monitoring"]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Nolix is one option.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://nolix.ai/",
                                "title": "Nolix",
                            }
                        ],
                    }
                ],
            },
        ]
    }

    answer, citations, queries = _extract_openai_response(data)
    assert answer == "Nolix is one option."
    assert citations[0].domain == "nolix.ai"
    assert queries == ["smart rodent monitoring"]


def test_own_domain_citation():
    assert _own_domain_cited(
        "nolix",
        [CitationSource(url="https://nolix.ai/", domain="nolix.ai")],
    )


def test_summary():
    observations = [
        LLMObservation(
            model="test",
            prompt="a",
            answer="Nolix is a good option.",
            brand_mentioned=True,
            brand_recommended=True,
            own_domain_cited=True,
            citations=[
                CitationSource(
                    url="https://nolix.ai/",
                    domain="nolix.ai",
                )
            ],
        ),
        LLMObservation(
            model="test",
            prompt="b",
            answer="Other options.",
            brand_mentioned=False,
            brand_recommended=False,
            own_domain_cited=False,
        ),
    ]

    summary = _summarize(observations)
    assert summary.mention_rate == 50.0
    assert summary.recommendation_rate == 50.0
    assert summary.own_domain_citation_rate == 50.0
