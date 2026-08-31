from app.product_catalog_api import (
    ProductCatalogPriceRange,
    ProductCatalogRow,
    _audit_product,
    _numeric_id,
    _to_catalog_row,
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
            "seo": {"title": "Example SEO", "description": "Example description"},
            "totalInventory": 10,
            "tracksInventory": True,
            "variantsCount": {"count": 1},
            "hasOnlyDefaultVariant": True,
            "priceRangeV2": {
                "minVariantPrice": {"amount": "99.00", "currencyCode": "USD"},
                "maxVariantPrice": {"amount": "99.00", "currencyCode": "USD"},
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


def test_audit_flags_missing_metadata_and_symbol_handle():
    product = ProductCatalogRow(
        id="gid://shopify/Product/123",
        numeric_id="123",
        title="Example",
        handle="example®",
        status="active",
        vendor="IoTx",
        product_type=None,
        tags=[],
        online_store_url="https://example.com/products/example",
        seo_title=None,
        seo_description=None,
        total_inventory=0,
        tracks_inventory=True,
        variant_count=1,
        has_only_default_variant=True,
        price=ProductCatalogPriceRange(min_price="10.00", max_price="10.00", currency="USD"),
        published_at="2026-08-01T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )

    codes = {issue.code for issue in _audit_product(product)}

    assert "missing_product_type" in codes
    assert "missing_seo_title" in codes
    assert "missing_seo_description" in codes
    assert "no_inventory" in codes
    assert "default_variant_only" in codes
    assert "symbol_in_handle" in codes
