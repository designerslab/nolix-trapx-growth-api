from app.llm_visibility_api import (
    LLMObservation,
    _extract_openai_response,
    _prompt_aggregates,
    _summary_from,
)


def test_extract_grounding_metadata():
    data = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"queries": ["smart rodent detection"]},
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

    answer, citations, queries, used = _extract_openai_response(data)

    assert answer == "Nolix is one option."
    assert used is True
    assert queries == ["smart rodent detection"]
    assert len(citations) == 1


def test_summary_grounded_rate():
    observations = [
        LLMObservation(
            model="test",
            prompt="a",
            trial=1,
            answer="Nolix",
            brand_mentioned=True,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=True,
            search_query_count=1,
            citation_count=0,
            grounded=True,
        ),
        LLMObservation(
            model="test",
            prompt="a",
            trial=2,
            answer="Other",
            brand_mentioned=False,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=False,
            grounded=False,
        ),
    ]

    summary = _summary_from(observations)

    assert summary.mention_rate == 50.0
    assert summary.grounded_observation_rate == 50.0


def test_prompt_aggregate_three_trials():
    observations = [
        LLMObservation(
            model="test",
            prompt="a",
            trial=1,
            answer="Nolix",
            brand_mentioned=True,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=True,
            grounded=True,
        ),
        LLMObservation(
            model="test",
            prompt="a",
            trial=2,
            answer="Nolix",
            brand_mentioned=True,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=True,
            grounded=True,
        ),
        LLMObservation(
            model="test",
            prompt="a",
            trial=3,
            answer="Other",
            brand_mentioned=False,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=True,
            grounded=True,
        ),
    ]

    agg = _prompt_aggregates(["a"], observations)[0]

    assert agg.trials == 3
    assert agg.mention_rate == 66.7
    assert agg.grounded_trials == 3
