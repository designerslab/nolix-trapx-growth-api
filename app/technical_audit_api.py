from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse, urlunparse

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


class LinkCheck(BaseModel):
    url: str
    status_code: int | None = None
    final_url: str | None = None
    redirects: int = 0
    broken: bool = False


class GeoAssetAudit(BaseModel):
    url: str
    status_code: int | None = None
    content_type: str | None = None
    length: int = 0
    has_heading: bool = False
    mentions_brand: bool = False
    issues: list[TechnicalIssue] = Field(default_factory=list)


class PageAudit(BaseModel):
    url: str
    normalized_url: str
    status_code: int | None = None
    content_type: str | None = None
    redirects: int = 0
    redirect_chain: list[str] = Field(default_factory=list)

    title: str | None = None
    title_length: int = 0
    meta_description: str | None = None
    meta_description_length: int = 0
    canonical: str | None = None
    canonical_matches_url: bool | None = None

    h1_count: int = 0
    noindex: bool = False

    json_ld_blocks: int = 0
    schema_types: list[str] = Field(default_factory=list)

    images: int = 0
    images_missing_alt: int = 0

    internal_links: int = 0
    internal_link_urls: list[str] = Field(default_factory=list)

    issues: list[TechnicalIssue] = Field(default_factory=list)


class SiteTechnicalSummary(BaseModel):
    pages_checked: int
    pages_ok: int
    pages_with_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    broken_internal_links: int
    redirecting_internal_links: int
    duplicate_title_groups: int
    duplicate_meta_groups: int
    health_score: int


class SiteTechnicalAuditResponse(BaseModel):
    brand: str
    site_url: str

    robots_url: str
    robots_status: int | None = None
    robots_all_blocked: bool = False
    robots_sitemaps: list[str] = Field(default_factory=list)

    sitemap_url: str | None = None
    sitemap_status: int | None = None

    llms_txt: GeoAssetAudit
    agents_md: GeoAssetAudit

    https_ok: bool

    summary: SiteTechnicalSummary

    site_issues: list[TechnicalIssue] = Field(default_factory=list)
    pages: list[PageAudit] = Field(default_factory=list)

    broken_links: list[LinkCheck] = Field(default_factory=list)
    redirecting_links: list[LinkCheck] = Field(default_factory=list)

    duplicate_titles: dict[str, list[str]] = Field(default_factory=dict)
    duplicate_meta_descriptions: dict[str, list[str]] = Field(default_factory=dict)

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
        self.schema_types: set[str] = set()
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

        self.images = 0
        self.images_missing_alt = 0

        self.internal_link_urls: list[str] = []
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
                self._in_json_ld = True
                self._json_ld_parts = []

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
                    self.internal_link_urls.append(absolute)

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if tag == "title":
            self.in_document_title = False

        elif tag == "head":
            self.in_head = False
            self.in_document_title = False

        elif tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            raw = "".join(self._json_ld_parts).strip()
            self._json_ld_parts = []

            if raw:
                self._collect_schema_types(raw)

    def handle_data(self, data: str):
        if self.in_document_title:
            self.title_parts.append(data)

        if self._in_json_ld:
            self._json_ld_parts.append(data)

    def _collect_schema_types(self, raw: str) -> None:
        try:
            parsed = json.loads(raw)
        except Exception:
            return

        def visit(value):
            if isinstance(value, dict):
                schema_type = value.get("@type")

                if isinstance(schema_type, str):
                    self.schema_types.add(schema_type)

                elif isinstance(schema_type, list):
                    for item in schema_type:
                        if isinstance(item, str):
                            self.schema_types.add(item)

                for child in value.values():
                    visit(child)

            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(parsed)

    @property
    def title(self) -> str | None:
        value = re.sub(
            r"\s+",
            " ",
            " ".join(self.title_parts),
        ).strip()

        return value or None


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)

    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()

    path = unquote(parsed.path or "/")

    if path != "/":
        path = path.rstrip("/")

    return urlunparse(
        (
            scheme,
            host,
            path,
            "",
            "",
            "",
        )
    )


def _path_extension(url: str) -> str:
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

    return _path_extension(url) not in NON_HTML_EXTENSIONS


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

    penalty = sum(
        weights.get(issue.severity, 0)
        for issue in issues
    )

    denominator = max(pages_checked, 1)

    return max(
        0,
        min(
            100,
            round(
                100
                - (
                    penalty
                    / denominator
                )
            ),
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

    if page.redirects > 1:
        add(
            "medium",
            "redirect_chain",
            (
                f"Page required {page.redirects} redirects "
                "before reaching the final URL."
            ),
        )

    elif page.redirects == 1:
        add(
            "low",
            "page_redirect",
            "Page URL redirects once before loading.",
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

    elif page.canonical_matches_url is False:
        add(
            "medium",
            "canonical_mismatch",
            (
                "Canonical points to a different normalized URL: "
                f"{page.canonical}"
            ),
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

    if page.images and page.images_missing_alt:
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


def _parse_robots(
    robots_text: str | None,
) -> tuple[bool, list[str]]:
    if not robots_text:
        return False, []

    sitemaps: list[str] = []

    current_agents: list[str] = []
    all_blocked = False

    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()

        if not line or ":" not in line:
            continue

        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            current_agents = [value.lower()]

        elif field == "disallow":
            if "*" in current_agents and value == "/":
                all_blocked = True

        elif field == "sitemap":
            if value.startswith("http"):
                sitemaps.append(value)

    return all_blocked, list(dict.fromkeys(sitemaps))


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[
    int | None,
    str | None,
    str,
    str | None,
    list[str],
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

        chain = [
            str(item.url)
            for item in response.history
        ]

        return (
            response.status_code,
            response.text,
            str(response.url),
            content_type,
            chain,
        )

    except httpx.HTTPError:
        return (
            None,
            None,
            url,
            None,
            [],
        )


async def _discover_sitemap(
    client: httpx.AsyncClient,
    site_url: str,
    robots_sitemaps: list[str],
) -> tuple[
    str | None,
    int | None,
    str | None,
]:
    candidates = list(robots_sitemaps)

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
            _,
        ) = await _fetch(
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
            _,
        ) = await _fetch(
            client,
            candidates[0],
        )

        return (
            final_url,
            code,
            text,
        )

    return None, None, None


async def _audit_geo_asset(
    client: httpx.AsyncClient,
    url: str,
    brand: str,
) -> GeoAssetAudit:
    (
        code,
        text,
        final_url,
        content_type,
        _,
    ) = await _fetch(
        client,
        url,
    )

    content = text or ""

    result = GeoAssetAudit(
        url=final_url,
        status_code=code,
        content_type=content_type,
        length=len(content),
        has_heading=bool(
            re.search(
                r"(?m)^\s*#\s+\S+",
                content,
            )
        ),
        mentions_brand=brand.lower() in content.lower(),
    )

    issues: list[TechnicalIssue] = []

    def add(
        severity: str,
        issue_code: str,
        message: str,
    ) -> None:
        issues.append(
            TechnicalIssue(
                severity=severity,
                code=issue_code,
                url=final_url,
                message=message,
            )
        )

    if code != 200:
        add(
            "low",
            "geo_asset_missing",
            f"GEO asset returned HTTP {code}.",
        )

    else:
        if len(content.strip()) < 100:
            add(
                "low",
                "geo_asset_thin",
                "GEO asset contains less than 100 characters.",
            )

        if not result.has_heading:
            add(
                "low",
                "geo_asset_missing_heading",
                "GEO asset has no Markdown H1 heading.",
            )

        if not result.mentions_brand:
            add(
                "low",
                "geo_asset_missing_brand",
                "GEO asset does not mention the brand name.",
            )

    result.issues = issues
    return result


async def _audit_page(
    client: httpx.AsyncClient,
    url: str,
) -> PageAudit | None:
    (
        status_code,
        text,
        final_url,
        content_type,
        redirect_chain,
    ) = await _fetch(
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

    normalized = _normalize_url(
        final_url
    )

    page = PageAudit(
        url=final_url,
        normalized_url=normalized,
        status_code=status_code,
        content_type=content_type,
        redirects=len(redirect_chain),
        redirect_chain=redirect_chain,
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

    if page.canonical:
        page.canonical_matches_url = (
            _normalize_url(
                page.canonical
            )
            == normalized
        )

    page.h1_count = parser.h1_count
    page.noindex = parser.noindex

    page.json_ld_blocks = (
        parser.json_ld_blocks
    )
    page.schema_types = sorted(
        parser.schema_types
    )

    page.images = parser.images
    page.images_missing_alt = (
        parser.images_missing_alt
    )

    unique_links = list(
        dict.fromkeys(
            _normalize_url(url)
            for url in parser.internal_link_urls
            if _is_page_candidate(
                url,
                urlparse(
                    final_url
                ).netloc,
            )
        )
    )

    page.internal_link_urls = (
        unique_links
    )
    page.internal_links = len(
        unique_links
    )

    page.issues = _page_issues(
        page
    )

    return page


def _duplicate_groups(
    pages: list[PageAudit],
    field: str,
) -> dict[str, list[str]]:
    groups: dict[
        str,
        list[str],
    ] = defaultdict(list)

    for page in pages:
        value = getattr(
            page,
            field,
        )

        if not value:
            continue

        normalized_value = re.sub(
            r"\s+",
            " ",
            str(value).strip().lower(),
        )

        groups[
            normalized_value
        ].append(
            page.url
        )

    return {
        key: urls
        for key, urls in groups.items()
        if len(urls) > 1
    }


async def _check_internal_link(
    client: httpx.AsyncClient,
    url: str,
) -> LinkCheck:
    (
        code,
        _,
        final_url,
        _,
        redirect_chain,
    ) = await _fetch(
        client,
        url,
    )

    return LinkCheck(
        url=url,
        status_code=code,
        final_url=final_url,
        redirects=len(
            redirect_chain
        ),
        broken=(
            code is None
            or code >= 400
        ),
    )


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
    max_internal_links: int = Query(
        default=100,
        ge=0,
        le=300,
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
    agents_url = (
        f"{site_url}/agents.md"
    )

    timeout = httpx.Timeout(
        20.0
    )

    headers = {
        "User-Agent": (
            "NolixGrowthAgent/2.0 "
            "(technical SEO/GEO audit; read-only)"
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
            _,
        ) = await _fetch(
            client,
            robots_url,
        )

        (
            robots_all_blocked,
            robots_sitemaps,
        ) = _parse_robots(
            robots_text
        )

        (
            sitemap_url,
            sitemap_status,
            sitemap_text,
        ) = await _discover_sitemap(
            client,
            site_url,
            robots_sitemaps,
        )

        llms_txt = await _audit_geo_asset(
            client,
            llms_url,
            brand,
        )

        agents_md = await _audit_geo_asset(
            client,
            agents_url,
            brand,
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

        if robots_all_blocked:
            site_issue(
                "critical",
                "robots_blocks_all",
                robots_url,
                (
                    "robots.txt contains "
                    "User-agent: * with Disallow: /."
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

        site_issues.extend(
            llms_txt.issues
        )
        site_issues.extend(
            agents_md.issues
        )

        page_urls: list[str] = []
        skipped_urls: list[str] = []

        if sitemap_text:
            sitemap_urls = (
                _extract_sitemap_urls(
                    sitemap_text,
                    max_pages * 5,
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
                for child in (
                    child_sitemaps[:20]
                ):
                    (
                        code,
                        child_text,
                        _,
                        _,
                        _,
                    ) = await _fetch(
                        client,
                        child,
                    )

                    if (
                        code != 200
                        or not child_text
                    ):
                        continue

                    child_urls = (
                        _extract_sitemap_urls(
                            child_text,
                            max_pages * 5,
                        )
                    )

                    for candidate in (
                        child_urls
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
                            >= max_pages * 2
                        ):
                            break

                    if (
                        len(page_urls)
                        >= max_pages * 2
                    ):
                        break

            else:
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

        page_urls.insert(
            0,
            site_url,
        )

        deduped: dict[
            str,
            str,
        ] = {}

        for url in page_urls:
            key = _normalize_url(
                url
            )

            if key not in deduped:
                deduped[key] = url

        page_urls = list(
            deduped.values()
        )[:max_pages]

        semaphore = (
            asyncio.Semaphore(8)
        )

        async def bounded_page(
            url: str,
        ) -> PageAudit | None:
            async with semaphore:
                return await _audit_page(
                    client,
                    url,
                )

        raw_pages = await asyncio.gather(
            *(
                bounded_page(url)
                for url in page_urls
            )
        )

        pages: list[
            PageAudit
        ] = []

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

        duplicate_titles = (
            _duplicate_groups(
                pages,
                "title",
            )
        )

        duplicate_meta = (
            _duplicate_groups(
                pages,
                "meta_description",
            )
        )

        for value, urls in (
            duplicate_titles.items()
        ):
            for page in pages:
                if page.url in urls:
                    page.issues.append(
                        TechnicalIssue(
                            severity="medium",
                            code="duplicate_title",
                            url=page.url,
                            message=(
                                "Title is duplicated across "
                                f"{len(urls)} audited pages."
                            ),
                        )
                    )

        for value, urls in (
            duplicate_meta.items()
        ):
            for page in pages:
                if page.url in urls:
                    page.issues.append(
                        TechnicalIssue(
                            severity="low",
                            code="duplicate_meta_description",
                            url=page.url,
                            message=(
                                "Meta description is duplicated across "
                                f"{len(urls)} audited pages."
                            ),
                        )
                    )

        internal_candidates: list[
            str
        ] = []

        for page in pages:
            internal_candidates.extend(
                page.internal_link_urls
            )

        internal_candidates = list(
            dict.fromkeys(
                internal_candidates
            )
        )[:max_internal_links]

        async def bounded_link(
            url: str,
        ) -> LinkCheck:
            async with semaphore:
                return await _check_internal_link(
                    client,
                    url,
                )

        link_results = await asyncio.gather(
            *(
                bounded_link(url)
                for url in internal_candidates
            )
        )

    broken_links = [
        result
        for result in link_results
        if result.broken
    ]

    redirecting_links = [
        result
        for result in link_results
        if (
            not result.broken
            and result.redirects > 0
        )
    ]

    for link in broken_links:
        site_issues.append(
            TechnicalIssue(
                severity="high",
                code="broken_internal_link",
                url=link.url,
                message=(
                    "Internal link returned "
                    f"{link.status_code}."
                ),
            )
        )

    for link in redirecting_links:
        site_issues.append(
            TechnicalIssue(
                severity="low",
                code="redirecting_internal_link",
                url=link.url,
                message=(
                    f"Internal link redirects "
                    f"{link.redirects} time(s)."
                ),
            )
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
        robots_all_blocked=(
            robots_all_blocked
        ),
        robots_sitemaps=(
            robots_sitemaps
        ),
        sitemap_url=sitemap_url,
        sitemap_status=sitemap_status,
        llms_txt=llms_txt,
        agents_md=agents_md,
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
                counts["critical"]
            ),
            high_issues=(
                counts["high"]
            ),
            medium_issues=(
                counts["medium"]
            ),
            low_issues=(
                counts["low"]
            ),
            broken_internal_links=(
                len(broken_links)
            ),
            redirecting_internal_links=(
                len(
                    redirecting_links
                )
            ),
            duplicate_title_groups=(
                len(
                    duplicate_titles
                )
            ),
            duplicate_meta_groups=(
                len(
                    duplicate_meta
                )
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
        broken_links=broken_links,
        redirecting_links=(
            redirecting_links
        ),
        duplicate_titles=(
            duplicate_titles
        ),
        duplicate_meta_descriptions=(
            duplicate_meta
        ),
        skipped_urls=list(
            dict.fromkeys(
                skipped_urls
            )
        ),
    )
