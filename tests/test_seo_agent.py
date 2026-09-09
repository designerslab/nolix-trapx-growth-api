from app.content_opportunity_api import (
    BusinessRelevance,
    ContentOpportunity,
)
from app.seo_agent.service import (
    _action_id,
    _execution_for,
    build_action_queue,
)


def _item(query, seo, strategic, action_type="optimize_existing"):
    return ContentOpportunity(
        priority=1,
        seo_score=seo,
        strategic_score=strategic,
        confidence="medium",
        strategic_intent="commercial",
        opportunity_type=action_type,
        query=query,
        page="https://nolix.ai/example",
        action="Improve page",
        why="Evidence",
        business_relevance=BusinessRelevance(
            level="high",
            score=18,
            matched_themes=["leak monitoring"],
            negative_themes=[],
            reason="matched",
        ),
    )


def test_action_id_stable():
    item = _item("water leak monitoring", 70, 40)
    assert _action_id(item) == _action_id(item)


def test_execution_routes_content_actions():
    item = _item("water leak monitoring", 70, 40)
    assert _execution_for(item) == "prepare_content_draft_for_human_review"


def test_queue_combines_and_dedupes():
    a = _item("water leak monitoring", 80, 50)
    b = _item("water leak monitoring", 60, 40)
    c = _item("rodent monitoring", 50, 80)
    result = build_action_queue([a, b], [c], 10)
    assert len(result) == 2
