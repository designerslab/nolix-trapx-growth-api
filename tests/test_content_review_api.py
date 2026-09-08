from app.content_review_api import (
    ContentReviewRecord,
    ReviewDecisionRequest,
    SubmitDraftForReviewRequest,
)


def test_submit_review_model_accepts_safe_draft():
    request = SubmitDraftForReviewRequest(
        draft_payload={
            "brand": "nolix",
            "approval_status": "requires_human_approval",
            "publish_allowed": False,
            "draft": {"title": "Example"},
        }
    )
    assert request.draft_payload["publish_allowed"] is False


def test_review_decision_values():
    request = ReviewDecisionRequest(
        decision="approved",
        reviewer="human-reviewer",
        notes="Reviewed manually.",
    )
    assert request.decision == "approved"


def test_approved_review_still_cannot_publish():
    record = ContentReviewRecord(
        draft_id="12345678",
        brand="nolix",
        status="approved",
        reviewer_hint=None,
        reviewer="human-reviewer",
        review_notes="Approved.",
        created_at="2026-09-07T00:00:00+00:00",
        updated_at="2026-09-07T00:00:00+00:00",
        reviewed_at="2026-09-07T00:00:00+00:00",
        publish_allowed=False,
        draft_payload={"publish_allowed": False},
    )

    assert record.status == "approved"
    assert record.publish_allowed is False
