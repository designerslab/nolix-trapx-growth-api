from app.llm_visibility_api import (
    LLMObservation,
    _baseline_summary_from_records,
)


def make_observation(
    mentioned=True,
    recommended=False,
    cited=False,
):
    return LLMObservation(
        model="test",
        prompt="test prompt",
        trial=1,
        answer="test",
        brand_mentioned=mentioned,
        brand_recommended=recommended,
        own_domain_cited=cited,
        web_search_used=True,
        search_query_count=1,
        citation_count=1 if cited else 0,
        grounded=True,
    ).model_dump()


def test_complete_baseline():
    records = []

    for index in range(8):
        records.append(
            {
                "brand": "nolix",
                "baseline_id": "2026-09-03-weekly",
                "prompt_index": index,
                "started_at": "2026-09-03T00:00:00+00:00",
                "completed_at": "2026-09-03T00:01:00+00:00",
                "observations": [
                    make_observation(
                        mentioned=True,
                        recommended=index < 4,
                        cited=index == 7,
                    )
                ],
            }
        )

    baseline = _baseline_summary_from_records(
        "nolix",
        "2026-09-03-weekly",
        records,
    )

    assert baseline["status"] == "complete"
    assert baseline["completed_prompts"] == 8
    assert baseline["overall"]["mention_rate"] == 100.0
    assert baseline["overall"]["own_domain_citation_rate"] == 12.5
    assert baseline["unbranded"]["own_domain_citation_rate"] == 0.0


def test_partial_baseline():
    records = [
        {
            "brand": "nolix",
            "baseline_id": "partial",
            "prompt_index": 0,
            "started_at": "2026-09-03T00:00:00+00:00",
            "completed_at": "2026-09-03T00:01:00+00:00",
            "observations": [
                make_observation()
            ],
        }
    ]

    baseline = _baseline_summary_from_records(
        "nolix",
        "partial",
        records,
    )

    assert baseline["status"] == "partial"
    assert baseline["completed_prompts"] == 1
