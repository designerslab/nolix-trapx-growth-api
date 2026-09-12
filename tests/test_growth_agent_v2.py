from app.growth_agent.router import _change, _landing_path


def test_position_change_positive_means_improved():
    current = {"clicks": 3, "impressions": 20, "ctr": .15, "position": 7}
    previous = {"clicks": 1, "impressions": 10, "ctr": .10, "position": 12}
    result = _change(current, previous)
    assert result["position"] == 5
    assert result["clicks"] == 2


def test_landing_path_accepts_absolute_url():
    assert _landing_path("https://nolix.ai/blogs/news/example") == "/blogs/news/example"


def test_landing_path_accepts_path():
    assert _landing_path("/pages/contact") == "/pages/contact"
