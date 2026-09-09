from app.agent_platform.registry import get_agent, list_agents

def test_growth_agent_registered():
    assert get_agent("growth") is not None

def test_controlled_publish_capability():
    names = {x.name for x in get_agent("growth").capabilities}
    assert "controlled_publish" in names

def test_list_agents():
    assert any(x.key == "growth" for x in list_agents())
