from app.content_publish_api import _draft_fields
from app.services.content_review_store import content_payload_hash
def test_draft_fields():
    assert _draft_fields({"draft":{"title":"Test","body":"<p>Hello</p>","slug":"test"}})==("Test","<p>Hello</p>","test")
def test_hash_changes():
    assert content_payload_hash({"draft":{"body":"a"}})!=content_payload_hash({"draft":{"body":"b"}})
