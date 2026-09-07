from app.content_draft_api import (
    ContentDraftArtifact,
    DraftClaim,
    ProductTruthItem,
    _numeric_product_id,
    _unsupported_claim_warnings,
)


def test_numeric_product_id_accepts_gid():
    assert _numeric_product_id("gid://shopify/Product/12345") == "12345"

def test_negated_guarantee_does_not_warn():
    draft = ContentDraftArtifact(
        title="Test",
        meta_title="Test",
        meta_description="Test",
        slug_suggestion="test",
        outline=["Intro"],
        body_markdown=(
            "Evaluate providers without making "
            "unsupported guarantees."
        ),
        claims=[],
    )

    warnings = _unsupported_claim_warnings(
        draft,
        [],
    )

    assert not any(
        "guarantee" in warning.lower()
        for warning in warnings
    )
def test_product_claim_without_evidence_warns():
    draft = ContentDraftArtifact(
        title="Test",
        meta_title="Test",
        meta_description="Test",
        slug_suggestion="test",
        outline=["Intro"],
        body_markdown="Draft.",
        claims=[
            DraftClaim(
                claim="The product detects leaks.",
                claim_type="product_fact",
                evidence_product_ids=[],
            )
        ],
    )

    assert _unsupported_claim_warnings(draft, [])


def test_known_product_truth_id_is_accepted():
    product = ProductTruthItem(
        product_id="123",
        title="Example",
        handle="example",
        status="active",
    )

    draft = ContentDraftArtifact(
        title="Test",
        meta_title="Test",
        meta_description="Test",
        slug_suggestion="test",
        outline=["Intro"],
        body_markdown="Draft.",
        claims=[
            DraftClaim(
                claim="Example is an active catalog product.",
                claim_type="product_fact",
                evidence_product_ids=["123"],
            )
        ],
    )

    assert not _unsupported_claim_warnings(draft, [product])


def test_risky_guarantee_language_warns():
    draft = ContentDraftArtifact(
        title="Test",
        meta_title="Test",
        meta_description="Test",
        slug_suggestion="test",
        outline=["Intro"],
        body_markdown="This guarantees perfect detection.",
        claims=[],
    )

    warnings = _unsupported_claim_warnings(draft, [])
    assert any("guarantee" in warning.lower() for warning in warnings)
