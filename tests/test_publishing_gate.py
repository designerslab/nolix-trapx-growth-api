from app.services.content_review_store import (
    content_payload_hash,
)


def test_content_hash_is_stable():
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}

    assert content_payload_hash(left) == content_payload_hash(right)


def test_content_hash_changes_when_content_changes():
    original = {
        "draft": {
            "title": "Version A"
        }
    }
    changed = {
        "draft": {
            "title": "Version B"
        }
    }

    assert (
        content_payload_hash(original)
        != content_payload_hash(changed)
    )
