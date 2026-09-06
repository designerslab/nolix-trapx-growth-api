from app.services.llm_visibility_store import (
    persist_visibility_run,
    read_visibility_runs,
)


class Settings:
    llm_visibility_dynamodb_table = None
    aws_region = "us-east-1"

    def __init__(self, path):
        self.llm_visibility_data_path = str(path)


def test_jsonl_fallback_round_trip(tmp_path):
    path = tmp_path / "visibility.jsonl"
    settings = Settings(path)

    payload = {
        "brand": "nolix",
        "baseline_id": "test",
        "prompt_index": 0,
        "completed_at": "2026-09-03T00:00:00Z",
        "summary": {"mention_rate": 100.0},
    }

    assert persist_visibility_run(
        payload,
        settings,
    )

    runs = read_visibility_runs(
        "nolix",
        10,
        settings,
    )

    assert len(runs) == 1
    assert runs[0]["baseline_id"] == "test"


def test_no_backend_returns_false():
    class EmptySettings:
        llm_visibility_dynamodb_table = None
        llm_visibility_data_path = None
        aws_region = "us-east-1"

    assert (
        persist_visibility_run(
            {"brand": "nolix"},
            EmptySettings(),
        )
        is False
    )
