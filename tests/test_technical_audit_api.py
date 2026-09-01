from app.technical_audit_api import (
    PageAudit,
    TechnicalIssue,
    _HTMLAuditParser,
    _duplicate_groups,
    _extract_sitemap_urls,
    _health_score,
    _is_page_candidate,
    _normalize_url,
    _page_issues,
    _parse_robots,
)


def test_normalize_root_urls_dedupe():
    assert _normalize_url(
        "https://nolix.ai"
    ) == _normalize_url(
        "https://nolix.ai/"
    )


def test_extract_urlset_ignores_image_locs():
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


def test_page_candidate_filters_assets():
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


def test_parser_title_and_schema_types():
    html = """
    <html>
      <head>
        <title>NoliX Smart Protection</title>
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"Organization"}
        </script>
      </head>
      <body>
        <svg><title>Visa</title></svg>
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

    assert parser.schema_types == {
        "Organization"
    }


def test_robots_all_blocked():
    text = """
    User-agent: *
    Disallow: /
    Sitemap: https://nolix.ai/sitemap.xml
    """

    blocked, sitemaps = _parse_robots(
        text
    )

    assert blocked is True
    assert sitemaps == [
        "https://nolix.ai/sitemap.xml"
    ]


def test_canonical_mismatch_issue():
    page = PageAudit(
        url="https://nolix.ai/a",
        normalized_url="https://nolix.ai/a",
        status_code=200,
        content_type="text/html",
        title="A useful page title for testing",
        meta_description="A valid description.",
        canonical="https://nolix.ai/b",
        canonical_matches_url=False,
        h1_count=1,
        json_ld_blocks=1,
    )

    codes = {
        issue.code
        for issue in _page_issues(
            page
        )
    }

    assert "canonical_mismatch" in codes


def test_duplicate_groups():
    pages = [
        PageAudit(
            url="https://nolix.ai/a",
            normalized_url="https://nolix.ai/a",
            title="Same Title",
        ),
        PageAudit(
            url="https://nolix.ai/b",
            normalized_url="https://nolix.ai/b",
            title="Same Title",
        ),
        PageAudit(
            url="https://nolix.ai/c",
            normalized_url="https://nolix.ai/c",
            title="Different",
        ),
    ]

    groups = _duplicate_groups(
        pages,
        "title",
    )

    assert len(groups) == 1


def test_health_score_normalized_per_page():
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
