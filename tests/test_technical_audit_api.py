from app.technical_audit_api import (
    PageAudit,
    TechnicalIssue,
    _HTMLAuditParser,
    _extract_sitemap_urls,
    _health_score,
    _is_page_candidate,
    _page_issues,
)


def test_extract_urlset_does_not_take_image_locs():
    xml = """<?xml version="1.0"?>
    <urlset
      xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
      xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url>
        <loc>https://nolix.ai/blogs/news/example</loc>
        <image:image>
          <image:loc>https://cdn.shopify.com/example.jpg</image:loc>
        </image:image>
      </url>
    </urlset>
    """

    assert _extract_sitemap_urls(
        xml,
        10,
    ) == [
        "https://nolix.ai/blogs/news/example"
    ]


def test_extract_sitemap_index():
    xml = """<?xml version="1.0"?>
    <sitemapindex
      xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap>
        <loc>https://nolix.ai/sitemap_products.xml</loc>
      </sitemap>
    </sitemapindex>
    """

    assert _extract_sitemap_urls(
        xml,
        10,
    ) == [
        "https://nolix.ai/sitemap_products.xml"
    ]


def test_page_candidate_filters_assets_and_other_hosts():
    assert _is_page_candidate(
        "https://nolix.ai/products/example",
        "nolix.ai",
    )
    assert not _is_page_candidate(
        "https://cdn.shopify.com/example.jpg",
        "nolix.ai",
    )
    assert not _is_page_candidate(
        "https://nolix.ai/agents.md",
        "nolix.ai",
    )


def test_parser_ignores_svg_titles_after_head():
    html = """
    <html>
      <head>
        <title>NoliX Smart Protection</title>
      </head>
      <body>
        <svg><title>Visa</title></svg>
        <svg><title>Mastercard</title></svg>
      </body>
    </html>
    """

    parser = _HTMLAuditParser(
        "https://nolix.ai"
    )
    parser.feed(html)

    assert parser.title == (
        "NoliX Smart Protection"
    )


def test_page_issues_for_missing_metadata():
    page = PageAudit(
        url="https://nolix.ai/test",
        status_code=200,
        content_type="text/html",
        title=None,
        meta_description=None,
        canonical=None,
        h1_count=0,
        json_ld_blocks=0,
    )

    codes = {
        issue.code
        for issue in _page_issues(
            page
        )
    }

    assert "missing_title" in codes
    assert (
        "missing_meta_description"
        in codes
    )
    assert (
        "missing_canonical"
        in codes
    )
    assert "missing_h1" in codes
    assert (
        "missing_json_ld"
        in codes
    )


def test_health_score_is_normalized_per_page():
    issues = [
        TechnicalIssue(
            severity="high",
            code="x",
            url="https://example.com",
            message="x",
        ),
        TechnicalIssue(
            severity="medium",
            code="y",
            url="https://example.com",
            message="y",
        ),
    ]

    assert _health_score(
        issues,
        1,
    ) == 83

    assert _health_score(
        issues,
        10,
    ) == 98

    assert _health_score(
        [],
        1,
    ) == 100

    assert _health_score(
        [],
        0,
    ) == 0
