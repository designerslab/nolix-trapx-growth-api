from app.services.article_renderer import render_article_markdown
from app.content_publish_api import _draft_fields


def test_renderer_removes_duplicate_h1():
    html = render_article_markdown(
        "# My Title\n\nIntro text.",
        title="My Title",
    )
    assert "<h1>" not in html
    assert "<p>Intro text.</p>" in html


def test_renderer_headings_paragraphs_lists():
    html = render_article_markdown(
        "## Section\n\nParagraph.\n\n- One\n- Two\n\n### Detail\nText."
    )
    assert "<h2>Section</h2>" in html
    assert "<p>Paragraph.</p>" in html
    assert "<ul>" in html
    assert "<li>One</li>" in html
    assert "<li>Two</li>" in html
    assert "<h3>Detail</h3>" in html


def test_renderer_inline_formatting():
    html = render_article_markdown(
        "Use **strong** and [Nolix](https://nolix.ai/)."
    )
    assert "<strong>strong</strong>" in html
    assert '<a href="https://nolix.ai/">Nolix</a>' in html


def test_draft_fields_renders_markdown():
    title, body, handle = _draft_fields(
        {
            "draft": {
                "title": "My Title",
                "body_markdown": "# My Title\n\n## Section\n\nText.",
                "slug": "my-title",
            }
        }
    )
    assert title == "My Title"
    assert "<h2>Section</h2>" in body
    assert "# My Title" not in body
    assert handle == "my-title"
