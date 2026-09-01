from app.product_catalog_api import (
    ProductCatalogPriceRange,
    ProductCatalogRow,
    _audit_product,
    _health_counts,
    _numeric_id,
    _report_status,
    _to_catalog_row,
)


def _product(
    *,
    status="active",
    handle="example",
    product_type="Sensor",
    seo_title="SEO title",
    seo_description="SEO description",
    total_inventory=10,
    variant_count=2,
    has_only_default_variant=False,
):
    return ProductCatalogRow(
        id="gid://shopify/Product/123",
        numeric_id="123",
        title="Example",
        handle=handle,
        status=status,
        vendor="IoTx",
        product_type=product_type,
        tags=[],
        online_store_url="https://example.com/products/example",
        seo_title=seo_title,
        seo_description=seo_description,
        total_inventory=total_inventory,
        tracks_inventory=True,
        variant_count=variant_count,
        has_only_default_variant=has_only_default_variant,
        price=ProductCatalogPriceRange(
            min_price="10.00",
            max_price="10.00",
            currency="USD",
        ),
        published_at="2026-08-01T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )


def test_numeric_id():
    assert _numeric_id("gid://shopify/Product/123") == "123"


def test_to_catalog_row():
    row = _to_catalog_row(
        {
            "id": "gid://shopify/Product/123",
            "title": "Example",
            "handle": "example",
            "status": "ACTIVE",
            "vendor": "IoTx",
            "productType": "Sensor",
            "tags": ["TrapX"],
            "onlineStoreUrl": "https://example.com/products/example",
            "seo": {
                "title": "Example SEO",
                "description": "Example description",
            },
            "totalInventory": 10,
            "tracksInventory": True,
            "variantsCount": {"count": 1},
            "hasOnlyDefaultVariant": True,
            "priceRangeV2": {
                "minVariantPrice": {
                    "amount": "99.00",
                    "currencyCode": "USD",
                },
                "maxVariantPrice": {
                    "amount": "99.00",
                    "currencyCode": "USD",
                },
            },
            "publishedAt": "2026-08-01T00:00:00Z",
            "updatedAt": "2026-08-02T00:00:00Z",
        }
    )

    assert row.numeric_id == "123"
    assert row.status == "active"
    assert row.price.min_price == "99.00"
    assert row.price.currency == "USD"
    assert row.variant_count == 1


def test_active_metadata_gaps_are_actionable():
    product = _product(
        product_type=None,
        seo_title=None,
        seo_description=None,
    )
    metadata = {
        issue.code: issue.actionability
        for issue in _audit_product(product)
    }

    assert metadata["missing_product_type"] == "actionable"
    assert metadata["missing_seo_title"] == "actionable"
    assert metadata["missing_seo_description"] == "actionable"


def test_default_variant_is_informational():
    product = _product(
        variant_count=1,
        has_only_default_variant=True,
    )
    issue = next(
        item
        for item in _audit_product(product)
        if item.code == "default_variant_only"
    )
    assert issue.actionability == "informational"


def test_symbol_handle_requires_review():
    product = _product(handle="example®")
    issue = next(
        item
        for item in _audit_product(product)
        if item.code == "symbol_in_handle"
    )
    assert issue.actionability == "review"


def test_draft_metadata_is_backlog():
    product = _product(
        status="draft",
        seo_title=None,
    )
    issue = next(
        item
        for item in _audit_product(product)
        if item.code == "missing_seo_title"
    )
    assert issue.actionability == "backlog"


def test_health_counts():
    products = [
        _product(
            product_type=None,
            seo_title=None,
            seo_description=None,
            total_inventory=0,
            handle="example®",
            variant_count=1,
            has_only_default_variant=True,
        )
    ]

    counts = _health_counts(products)

    assert counts.missing_product_type == 1
    assert counts.missing_seo_title == 1
    assert counts.missing_seo_description == 1
    assert counts.zero_or_negative_inventory == 1
    assert counts.url_handle_review_candidates == 1
    assert counts.default_variant_only == 1


def test_report_status():
    assert _report_status(12, 0) == "needs_attention"
    assert _report_status(1, 0) == "review"
    assert _report_status(0, 1) == "review"
    assert _report_status(0, 0) == "healthy"
