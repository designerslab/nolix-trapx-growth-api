from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from app.security import require_api_key

router = APIRouter()

BRAND_SITES = {
    "nolix": "https://nolix.ai",
    "trapx": "https://trapx.io",
}

NON_HTML_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".xml",
    ".txt",
    ".md",
    ".json",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".webm",
    ".zip",
}


class TechnicalIssue(BaseModel):
    severity: str
    code: str
    url: str
    message: str


class PageAudit(BaseModel):
    url: str
    status_code: int | None = None
    content_type: str | None = None
    title: str | None = None
    title_length: int = 0
    meta_description: str | None = None
    meta_description_length: int = 0
    canonical: str | None = None
    h1_count: int = 0
    noindex: bool = False
    json_ld_blocks: int = 0
    images: int = 0
    images_missing_alt: int = 0
    internal_links: int = 0
    issues: list[TechnicalIssue] = Field(default_factory=list)


class SiteTechnicalSummary(BaseModel):
    pages_checked: int
    pages_ok: int
    pages_with_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    health_score: int


class SiteTechnicalAuditResponse(BaseModel):
    brand: str
    site_url: str
    robots_url: str
    robots_status: int | None = None
    sitemap_url: str | None = None
    sitemap_status: int | None = None
    llms_txt_url: str
    llms_txt_status: int | None = None
    https_ok: bool
    summary: SiteTechnicalSummary
    site_issues: list[TechnicalIssue] = Field(default_factory=list)
    pages: list[PageAudit] = Field(default_factory=list)
    skipped_urls: list[str] = Field(default_factory=list)
    source: str = "live_site"


class _HTMLAuditParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.in_head = False
        self.in_document_title = False
        self.document_title_seen = False
        self.title_parts: list[str] = []
        self.h1_count = 0
        self.meta_description: str | None = None
        self.canonical: str | None = None
        self.noindex = False
        self.json_ld_blocks = 0
        self.images = 0
        self.images_missing_alt = 0
        self.internal_links = 0
        self._base_host = urlparse(base_url).netloc.lower()

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = {
            str(k).lower(): (v if v is not None else "")
            for k, v in attrs
        }
        tag = tag.lower()

        if tag == "head":
            self.in_head = True
            return

        if tag == "title":
            if self.in_head and not self.document_title_seen:
                self.in_document_title = True
                self.document_title_seen = True
            return

        if tag == "h1":
            self.h1_count += 1

        elif tag == "meta":
            name = attrs_dict.get("name", "").lower()
            content = attrs_dict.get("content", "").strip()

            if name == "description" and not self.meta_description:
                self.meta_description = content or None

            if name == "robots" and "noindex" in content.lower():
                self.noindex = True

        elif tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "").strip()
            if "canonical" in rel and href and not self.canonical:
                self.canonical = urljoin(self.base_url, href)

        elif tag == "script":
            if attrs_dict.get("type", "").lower() == "application/ld+json":
                self.json_ld_blocks += 1

        elif tag == "img":
            self.images += 1
            alt = attrs_dict.get("alt")
            if alt is None or not str(alt).strip():
                self.images_missing_alt += 1

        elif tag == "a":
            href = attrs_dict.get("href", "").strip()
            if href:
                absolute = urljoin(self.base_url, href)
                parsed = urlparse(absolute)
                if (
                    parsed.scheme in {"http", "https"}
                    and parsed.netloc.lower() == self._base_host
                ):
                    self.internal_links += 1

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if tag == "title":
            self.in_document_title = False

        elif tag == "head":
            self.in_head = False
            self.in_document_title = False

    def handle_data(self, data: str):
        if self.in_document_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str | None:
        value = re.sub(
            r"\s+",
            " ",
            " ".join(self.title_parts),
        ).strip()
        return value or None


def _severity_counts(
    issues: list[TechnicalIssue],
) -> dict[str, int]:
    return {
        severity: sum(
            issue.severity == severity
            for issue in issues
        )
        for severity in (
            "critical",
            "high",
            "medium",
            "low",
        )
    }


def _health_score(
    issues: list[TechnicalIssue],
    pages_checked: int,
) -> int:
    if pages_checked == 0:
        return 0

    weights = {
        "critical": 25,
        "high": 12,
        "medium": 5,
        "low": 2,
    }

    total_penalty = sum(
        weights.get(issue.severity, 0)
        for issue in issues
    )

    average_penalty = total_penalty / pages_checked

    return max(
        0,
        min(
            100,
            round(100 - average_penalty),
        ),
    )


def _page_issues(
    page: PageAudit,
) -> list[TechnicalIssue]:
    issues: list[TechnicalIssue] = []

    def add(
        severity: str,
        code: str,
        message: str,
    ) -> None:
        issues.append(
            TechnicalIssue(
                severity=severity,
                code=code,
                url=page.url,
                message=message,
            )
        )

    if page.status_code is None:
        add(
            "critical",
            "fetch_failed",
            "Page could not be fetched.",
        )
        return issues

    if page.status_code >= 500:
        add(
            "critical",
            "server_error",
            f"HTTP {page.status_code}.",
        )

    elif page.status_code >= 400:
        add(
            "high",
            "client_error",
            f"HTTP {page.status_code}.",
        )

    elif page.status_code >= 300:
        add(
            "medium",
            "redirect",
            f"HTTP {page.status_code}.",
        )

    if not page.title:
        add(
            "high",
            "missing_title",
            "Page title is missing.",
        )

    elif page.title_length < 20:
        add(
            "low",
            "short_title",
            "Page title is unusually short.",
        )

    elif page.title_length > 65:
        add(
            "medium",
            "long_title",
            "Page title exceeds 65 characters.",
        )

    if not page.meta_description:
        add(
            "medium",
            "missing_meta_description",
            "Meta description is missing.",
        )

    elif page.meta_description_length > 165:
        add(
            "low",
            "long_meta_description",
            "Meta description exceeds 165 characters.",
        )

    if not page.canonical:
        add(
            "medium",
            "missing_canonical",
            "Canonical link is missing.",
        )

    if page.h1_count == 0:
        add(
            "medium",
            "missing_h1",
            "No H1 heading found.",
        )

    elif page.h1_count > 1:
        add(
            "low",
            "multiple_h1",
            f"{page.h1_count} H1 headings found.",
        )

    if page.noindex:
        add(
            "medium",
            "noindex",
            "Page contains a noindex robots directive.",
        )

    if page.json_ld_blocks == 0:
        add(
            "low",
            "missing_json_ld",
            "No JSON-LD structured data block found.",
        )

    if (
        page.images
        and page.images_missing_alt
    ):
        ratio = (
            page.images_missing_alt
            / page.images
        )

        severity = (
            "medium"
            if ratio >= 0.25
            else "low"
        )

        add(
            severity,
            "images_missing_alt",
            (
                f"{page.images_missing_alt}/"
                f"{page.images} images have "
                "missing or empty alt text."
            ),
        )

    return issues


def _path_extension(
    url: str,
) -> str:
    path = urlparse(url).path.lower()
    leaf = path.rsplit("/", 1)[-1]

    if "." not in leaf:
        return ""

    return "." + leaf.rsplit(".", 1)[-1]


def _is_page_candidate(
    url: str,
    site_host: str,
) -> bool:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return False

    if parsed.netloc.lower() != site_host.lower():
        return False

    extension = _path_extension(url)

    if extension in NON_HTML_EXTENSIONS:
        return False

    return True


async def _fetch_text(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[
    int | None,
    str | None,
    str,
    str | None,
]:
    try:
        response = await client.get(url)

        content_type = (
            response.headers
            .get("content-type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
            or None
        )

        return (
            response.status_code,
            response.text,
            str(response.url),
            content_type,
        )

    except httpx.HTTPError:
        return (
            None,
            None,
            url,
            None,
        )


def _extract_sitemap_urls(
    xml_text: str,
    limit: int,
) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    urls: list[str] = []

    root_name = root.tag.lower()

    if root_name.endswith("sitemapindex"):
        wanted_parent = "sitemap"
    else:
        wanted_parent = "url"

    for parent in root:
        if not parent.tag.lower().endswith(
            wanted_parent
        ):
            continue

        for child in parent:
            if not child.tag.lower().endswith(
                "loc"
            ):
                continue

            if not child.text:
                continue

            value = child.text.strip()

            if value.startswith("http"):
                urls.append(value)

            break

        if len(urls) >= limit:
            break

    return urls


async def _discover_sitemap(
    client: httpx.AsyncClient,
    site_url: str,
    robots_text: str | None,
) -> tuple[
    str | None,
    int | None,
    str | None,
]:
    candidates: list[str] = []

    if robots_text:
        for line in robots_text.splitlines():
            if line.lower().startswith(
                "sitemap:"
            ):
                candidate = (
                    line.split(":", 1)[1]
                    .strip()
                )

                if candidate.startswith(
                    "http"
                ):
                    candidates.append(
                        candidate
                    )

    candidates.extend(
        [
            f"{site_url}/sitemap.xml",
            f"{site_url}/sitemap_index.xml",
        ]
    )

    seen = set()

    for candidate in candidates:
        if candidate in seen:
            continue

        seen.add(candidate)

        (
            code,
            text,
            final_url,
            _,
        ) = await _fetch_text(
            client,
            candidate,
        )

        if code == 200 and text:
            return (
                final_url,
                code,
                text,
            )

    if candidates:
        (
            code,
            text,
            final_url,
            _,
        ) = await _fetch_text(
            client,
            candidates[0],
        )

        return (
            final_url,
            code,
            text,
        )

    return None, None, None


async def _audit_page(
    client: httpx.AsyncClient,
    url: str,
) -> PageAudit | None:
    (
        status_code,
        text,
        final_url,
        content_type,
    ) = await _fetch_text(
        client,
        url,
    )

    if (
        content_type
        and content_type
        not in {
            "text/html",
            "application/xhtml+xml",
        }
    ):
        return None

    page = PageAudit(
        url=final_url,
        status_code=status_code,
        content_type=content_type,
    )

    if not text:
        page.issues = _page_issues(
            page
        )
        return page

    parser = _HTMLAuditParser(
        final_url
    )

    try:
        parser.feed(text)
    except Exception:
        pass

    page.title = parser.title
    page.title_length = len(
        page.title or ""
    )
    page.meta_description = (
        parser.meta_description
    )
    page.meta_description_length = len(
        page.meta_description or ""
    )
    page.canonical = parser.canonical
    page.h1_count = parser.h1_count
    page.noindex = parser.noindex
    page.json_ld_blocks = (
        parser.json_ld_blocks
    )
    page.images = parser.images
    page.images_missing_alt = (
        parser.images_missing_alt
    )
    page.internal_links = (
        parser.internal_links
    )
    page.issues = _page_issues(
        page
    )

    return page


@router.get(
    "/v1/brands/{brand}/technical-audit",
    response_model=SiteTechnicalAuditResponse,
    dependencies=[Depends(require_api_key)],
    tags=["technical-audit"],
    operation_id="get_technical_audit",
)
async def get_technical_audit(
    brand: str = Path(
        pattern="^(nolix|trapx)$"
    ),
    max_pages: int = Query(
        default=25,
        ge=1,
        le=100,
    ),
) -> SiteTechnicalAuditResponse:
    site_url = BRAND_SITES[
        brand
    ].rstrip("/")

    site_host = urlparse(
        site_url
    ).netloc.lower()

    robots_url = (
        f"{site_url}/robots.txt"
    )
    llms_url = (
        f"{site_url}/llms.txt"
    )

    timeout = httpx.Timeout(
        20.0
    )

    headers = {
        "User-Agent": (
            "NolixGrowthAgent/1.1 "
            "(technical SEO audit; "
            "read-only)"
        )
    }

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        (
            robots_status,
            robots_text,
            _,
            _,
        ) = await _fetch_text(
            client,
            robots_url,
        )

        (
            llms_status,
            _,
            _,
            _,
        ) = await _fetch_text(
            client,
            llms_url,
        )

        (
            sitemap_url,
            sitemap_status,
            sitemap_text,
        ) = await _discover_sitemap(
            client,
            site_url,
            robots_text,
        )

        site_issues: list[
            TechnicalIssue
        ] = []

        def site_issue(
            severity: str,
            code: str,
            url: str,
            message: str,
        ) -> None:
            site_issues.append(
                TechnicalIssue(
                    severity=severity,
                    code=code,
                    url=url,
                    message=message,
                )
            )

        if robots_status != 200:
            site_issue(
                "high",
                "robots_unavailable",
                robots_url,
                (
                    "robots.txt returned "
                    f"{robots_status}."
                ),
            )

        if (
            sitemap_status != 200
            or not sitemap_text
        ):
            site_issue(
                "high",
                "sitemap_unavailable",
                (
                    sitemap_url
                    or f"{site_url}/sitemap.xml"
                ),
                "No working sitemap was found.",
            )

        if llms_status != 200:
            site_issue(
                "low",
                "llms_txt_missing",
                llms_url,
                (
                    "llms.txt was not found. "
                    "This is optional but useful "
                    "for GEO experiments."
                ),
            )

        page_urls = [
            site_url
        ]
        skipped_urls: list[str] = []

        if sitemap_text:
            sitemap_urls = (
                _extract_sitemap_urls(
                    sitemap_text,
                    max_pages * 4,
                )
            )

            child_sitemaps = [
                url
                for url in sitemap_urls
                if _path_extension(
                    url
                ) == ".xml"
            ]

            if child_sitemaps:
                collected: list[
                    str
                ] = []

                for child in (
                    child_sitemaps[:20]
                ):
                    (
                        code,
                        child_text,
                        _,
                        _,
                    ) = await _fetch_text(
                        client,
                        child,
                    )

                    if (
                        code == 200
                        and child_text
                    ):
                        for candidate in (
                            _extract_sitemap_urls(
                                child_text,
                                max_pages * 4,
                            )
                        ):
                            if _is_page_candidate(
                                candidate,
                                site_host,
                            ):
                                collected.append(
                                    candidate
                                )
                            else:
                                skipped_urls.append(
                                    candidate
                                )

                            if (
                                len(collected)
                                >= max_pages
                            ):
                                break

                    if (
                        len(collected)
                        >= max_pages
                    ):
                        break

                if collected:
                    page_urls = (
                        collected[
                            :max_pages
                        ]
                    )

            else:
                page_urls = []

                for candidate in (
                    sitemap_urls
                ):
                    if _is_page_candidate(
                        candidate,
                        site_host,
                    ):
                        page_urls.append(
                            candidate
                        )
                    else:
                        skipped_urls.append(
                            candidate
                        )

                    if (
                        len(page_urls)
                        >= max_pages
                    ):
                        break

        if site_url not in page_urls:
            page_urls.insert(
                0,
                site_url,
            )
            page_urls = page_urls[
                :max_pages
            ]

        semaphore = (
            asyncio.Semaphore(8)
        )

        async def bounded(
            url: str,
        ) -> PageAudit | None:
            async with semaphore:
                return await _audit_page(
                    client,
                    url,
                )

        raw_pages = await asyncio.gather(
            *(
                bounded(url)
                for url in page_urls
            )
        )

        pages = []

        for url, result in zip(
            page_urls,
            raw_pages,
        ):
            if result is None:
                skipped_urls.append(
                    url
                )
            else:
                pages.append(
                    result
                )

    all_issues = (
        site_issues
        + [
            issue
            for page in pages
            for issue in page.issues
        ]
    )

    counts = _severity_counts(
        all_issues
    )

    pages_with_issues = sum(
        bool(page.issues)
        for page in pages
    )

    return SiteTechnicalAuditResponse(
        brand=brand,
        site_url=site_url,
        robots_url=robots_url,
        robots_status=robots_status,
        sitemap_url=sitemap_url,
        sitemap_status=sitemap_status,
        llms_txt_url=llms_url,
        llms_txt_status=llms_status,
        https_ok=site_url.startswith(
            "https://"
        ),
        summary=SiteTechnicalSummary(
            pages_checked=len(
                pages
            ),
            pages_ok=(
                len(pages)
                - pages_with_issues
            ),
            pages_with_issues=(
                pages_with_issues
            ),
            critical_issues=(
                counts[
                    "critical"
                ]
            ),
            high_issues=(
                counts["high"]
            ),
            medium_issues=(
                counts[
                    "medium"
                ]
            ),
            low_issues=(
                counts["low"]
            ),
            health_score=(
                _health_score(
                    all_issues,
                    len(pages),
                )
            ),
        ),
        site_issues=site_issues,
        pages=pages,
        skipped_urls=list(
            dict.fromkeys(
                skipped_urls
            )
        ),
    )
