from __future__ import annotations

import html
import re


_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`\n]+)`")


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=True)

    # Re-introduce a deliberately small Markdown subset after escaping.
    escaped = _LINK_RE.sub(
        lambda m: (
            f'<a href="{html.escape(m.group(2), quote=True)}">'
            f'{html.escape(m.group(1))}</a>'
        ),
        escaped,
    )
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    escaped = _CODE_RE.sub(r"<code>\1</code>", escaped)
    return escaped


def render_article_markdown(
    markdown: str,
    *,
    title: str | None = None,
) -> str:
    """Render generated article Markdown into conservative Shopify HTML.

    The Shopify article template already renders the article title, so the
    first Markdown H1 is removed when it duplicates the supplied title.
    """
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("Article Markdown is empty.")

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Remove a duplicate document H1 because Shopify renders the title.
    while lines and not lines[0].strip():
        lines.pop(0)

    if lines and lines[0].lstrip().startswith("# "):
        h1_text = lines[0].lstrip()[2:].strip()
        if title is None or h1_text.casefold() == title.strip().casefold():
            lines.pop(0)

    out: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            text = " ".join(item.strip() for item in paragraph if item.strip())
            if text:
                out.append(f"<p>{_inline(text)}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    for raw in lines:
        line = raw.strip()

        if not line:
            flush_paragraph()
            close_list()
            continue

        heading = re.match(r"^(#{2,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            source_level = len(heading.group(1))
            # Keep body headings at h2 or deeper.
            level = min(max(source_level, 2), 6)
            out.append(
                f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>"
            )
            continue

        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", line)

        if bullet or numbered:
            flush_paragraph()
            wanted = "ul" if bullet else "ol"
            if list_type != wanted:
                close_list()
                out.append(f"<{wanted}>")
                list_type = wanted
            item = (bullet or numbered).group(1).strip()
            out.append(f"<li>{_inline(item)}</li>")
            continue

        close_list()

        # Horizontal rule.
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", line):
            flush_paragraph()
            out.append("<hr>")
            continue

        paragraph.append(line)

    flush_paragraph()
    close_list()

    return "\n".join(out).strip()
