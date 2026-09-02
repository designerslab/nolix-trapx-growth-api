from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path as FilePath
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.security import require_api_key

router = APIRouter()

BRAND_SITES = {"nolix": "nolix.ai", "trapx": "trapx.io"}

BRAND_TERMS = {
    "nolix": ["nolix", "nolix.ai"],
    "trapx": ["trapx", "trap x", "trapx.io"],
}

DEFAULT_COMPETITORS = {
    "nolix": [
        "Rentokil", "Anticimex", "Woodstream", "Victor",
        "Rook", "GTO", "RodentRadar", "Bell",
    ],
    "trapx": [
        "Rentokil", "Anticimex", "Woodstream", "Victor",
        "Rook", "GTO", "RodentRadar", "Bell",
    ],
}

DEFAULT_PROMPTS = {
    "nolix": [
        "What are the best smart rodent detection systems for commercial facilities?",
        "What are the best smart toilet leak detection systems for commercial buildings?",
        "What are the best IoT infrastructure monitoring solutions for facilities teams?",
        "How can a data center monitor hidden infrastructure risks such as leaks and rodents?",
        "What are good non-invasive pipe and cable monitoring solutions?",
        "What smart monitoring systems are suitable for hospitals and critical facilities?",
        "Which companies offer connected sensors for facility risk monitoring?",
        "What is Nolix and what products does it offer?",
    ],
    "trapx": [
        "What are the best smart rodent detection systems for commercial facilities?",
        "What are the best connected rodent monitoring devices for warehouses?",
        "What are alternatives to traditional mouse traps for commercial monitoring?",
        "Which rodent detection systems support remote monitoring?",
        "What smart pest monitoring systems are suitable for food facilities?",
        "What is TrapX and what does it offer?",
    ],
}

RECOMMENDATION_PATTERNS = [
    r"\brecommend(?:ed|s|ing)?\b",
    r"\bbest\b",
    r"\btop\b",
    r"\bstrong choice\b",
    r"\bgood (?:choice|option|fit)\b",
    r"\bconsider\b",
    r"\bsuitable\b",
]

TRUST_GAP_PATTERNS = {
    "insufficient_independent_validation": [
        r"independent (?:field )?validation",
        r"independent evidence",
        r"vendor-provided",
        r"company data",
        r"limited public evidence",
        r"public(?:ly available)? evidence is limited",
        r"neutral comparative study",
    ],
    "unclear_pricing": [
        r"pricing (?:is )?(?:unclear|not public|not publicly available|varies)",
        r"unclear.{0,60}pricing",
        r"verify.{0,60}pricing",
    ],
    "unclear_certifications": [
        r"certification(?:s)?.{0,40}(?:unclear|unknown|not clear)",
        r"unclear.{0,60}certification",
        r"verify.{0,60}certification",
    ],
    "limited_installed_base_evidence": [
        r"installed base",
        r"deployment(?:s)?.{0,40}(?:unclear|unknown|limited)",
        r"independently verify deployments",
        r"newer than",
    ],
    "service_support_uncertainty": [
        r"service model",
        r"support.{0,40}unclear",
        r"verify.{0,60}support",
        r"response sla",
        r"local coverage",
    ],
    "performance_uncertainty": [
        r"false[- ]alert",
        r"false positive",
        r"performance.{0,40}unclear",
        r"verify.{0,60}performance",
    ],
}


class CitationSource(BaseModel):
    url: str
    title: str | None = None
    domain: str | None = None


class LLMObservation(BaseModel):
    provider: str = "openai"
    model: str
    prompt: str
    trial: int
    answer: str
    brand_mentioned: bool
    brand_recommended: bool
    own_domain_cited: bool
    web_search_used: bool
    search_query_count: int = 0
    citation_count: int = 0
    grounded: bool = False
    competitor_mentions: list[str] = Field(default_factory=list)
    trust_gaps: list[str] = Field(default_factory=list)
    citations: list[CitationSource] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    error: str | None = None


class LLMVisibilityStatus(BaseModel):
    brand: str
    provider: str = "openai"
    configured: bool
    model: str
    web_search: bool = True


class LLMVisibilityPromptSet(BaseModel):
    brand: str
    prompts: list[str]
    competitors: list[str]


class LLMVisibilitySummary(BaseModel):
    observations: int
    successful_observations: int
    grounded_observations: int
    grounded_observation_rate: float
    mention_rate: float
    recommendation_rate: float
    own_domain_citation_rate: float
    discovery_status: str
    recommendation_confidence: str
    first_party_citation_authority: str
    top_citation_domains: list[tuple[str, int]]
    competitor_mentions: list[tuple[str, int]]
    trust_gaps: list[tuple[str, int]]


class PromptAggregate(BaseModel):
    prompt: str
    trials: int
    successful_trials: int
    grounded_trials: int
    mention_rate: float
    recommendation_rate: float
    own_domain_citation_rate: float
    competitor_mentions: list[tuple[str, int]]
    trust_gaps: list[tuple[str, int]]


class LLMVisibilityRunResponse(BaseModel):
    brand: str
    started_at: str
    completed_at: str
    model: str
    prompts_run: int
    repeat_count: int
    summary: LLMVisibilitySummary
    prompt_aggregates: list[PromptAggregate]
    observations: list[LLMObservation]
    persisted: bool = False
    source: str = "openai_responses_web_search"


class LLMVisibilityHistoryResponse(BaseModel):
    brand: str
    runs: list[dict]


def _setting(name: str) -> str | None:
    settings = get_settings()
    value = getattr(settings, name, None)

    if value is None:
        return None

    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()

    text = str(value).strip()
    return text or None


def _model() -> str:
    return _setting("openai_llm_visibility_model") or "gpt-5.6-luna"


def _competitors(brand: str) -> list[str]:
    raw = _setting(f"{brand}_llm_competitors")

    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]

    return DEFAULT_COMPETITORS[brand]


def _contains_term(text: str, term: str) -> bool:
    normalized = text.lower()
    term_norm = term.lower().strip()

    if not term_norm:
        return False

    if re.fullmatch(r"[a-z0-9 ]+", term_norm):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(term_norm)}(?![a-z0-9])",
                normalized,
            )
        )

    return term_norm in normalized


def _brand_mentioned(brand: str, answer: str) -> bool:
    return any(_contains_term(answer, term) for term in BRAND_TERMS[brand])


def _brand_recommended(brand: str, answer: str) -> bool:
    if not _brand_mentioned(brand, answer):
        return False

    lower = answer.lower()

    for term in BRAND_TERMS[brand]:
        term_lower = term.lower()
        start = 0

        while True:
            index = lower.find(term_lower, start)

            if index == -1:
                break

            window = lower[max(0, index - 180):min(len(lower), index + 260)]

            if any(re.search(pattern, window) for pattern in RECOMMENDATION_PATTERNS):
                return True

            start = index + len(term_lower)

    return False


def _trust_gaps(brand: str, answer: str) -> list[str]:
    if not _brand_mentioned(brand, answer):
        return []

    lower = answer.lower()
    windows: list[str] = []

    for term in BRAND_TERMS[brand]:
        term_lower = term.lower()
        start = 0

        while True:
            index = lower.find(term_lower, start)

            if index == -1:
                break

            windows.append(
                lower[max(0, index - 350):min(len(lower), index + 700)]
            )
            start = index + len(term_lower)

    nearby = "\n".join(windows)

    return [
        gap
        for gap, patterns in TRUST_GAP_PATTERNS.items()
        if any(re.search(pattern, nearby) for pattern in patterns)
    ]


def _citation_domain(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None

    if host.startswith("www."):
        host = host[4:]

    return host or None


def _own_domain_cited(
    brand: str,
    citations: list[CitationSource],
) -> bool:
    own_domain = BRAND_SITES[brand]

    return any(
        source.domain == own_domain
        or (source.domain and source.domain.endswith(f".{own_domain}"))
        for source in citations
    )


def _competitor_mentions(brand: str, answer: str) -> list[str]:
    return [
        competitor
        for competitor in _competitors(brand)
        if _contains_term(answer, competitor)
    ]


def _extract_openai_response(
    data: dict,
) -> tuple[str, list[CitationSource], list[str], bool]:
    text_parts: list[str] = []
    citations: dict[str, CitationSource] = {}
    search_queries: list[str] = []
    web_search_used = False

    for item in data.get("output") or []:
        if item.get("type") == "web_search_call":
            web_search_used = True
            action = item.get("action") or {}

            for query in action.get("queries") or []:
                if query:
                    search_queries.append(str(query))

        if item.get("type") != "message":
            continue

        for part in item.get("content") or []:
            if part.get("type") != "output_text":
                continue

            text = part.get("text")
            if text:
                text_parts.append(str(text))

            for annotation in part.get("annotations") or []:
                if annotation.get("type") != "url_citation":
                    continue

                url = annotation.get("url")
                if not url:
                    continue

                citations[url] = CitationSource(
                    url=url,
                    title=annotation.get("title"),
                    domain=_citation_domain(url),
                )

    return (
        "\n".join(text_parts).strip(),
        list(citations.values()),
        list(dict.fromkeys(search_queries)),
        web_search_used,
    )


def _measurement_prompt(brand: str, prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Use current web information where useful. "
        "Answer as an independent buyer/research assistant. "
        "Do not favor any company because it appears in this instruction. "
        f"The measurement subject is {brand.title()}, but mention or recommend "
        "it only if the available evidence genuinely supports doing so."
    )


async def _run_openai(
    brand: str,
    prompt: str,
    trial: int,
) -> LLMObservation:
    api_key = _setting("openai_api_key")

    if not api_key:
        return LLMObservation(
            model=_model(),
            prompt=prompt,
            trial=trial,
            answer="",
            brand_mentioned=False,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=False,
            error="OPENAI_API_KEY is not configured.",
        )

    payload = {
        "model": _model(),
        "input": _measurement_prompt(brand, prompt),
        "tools": [
            {
                "type": "web_search",
                "search_context_size": "medium",
            }
        ],
        "max_output_tokens": 1600,
    }

    try:
        async with httpx.AsyncClient(
            timeout=120.0,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenAI API returned {response.status_code}: "
                f"{response.text[:1000]}"
            )

        answer, citations, queries, web_search_used = _extract_openai_response(
            response.json()
        )

        citation_count = len(citations)
        query_count = len(queries)
        grounded = web_search_used and (query_count > 0 or citation_count > 0)

        return LLMObservation(
            model=_model(),
            prompt=prompt,
            trial=trial,
            answer=answer,
            brand_mentioned=_brand_mentioned(brand, answer),
            brand_recommended=_brand_recommended(brand, answer),
            own_domain_cited=_own_domain_cited(brand, citations),
            web_search_used=web_search_used,
            search_query_count=query_count,
            citation_count=citation_count,
            grounded=grounded,
            competitor_mentions=_competitor_mentions(brand, answer),
            trust_gaps=_trust_gaps(brand, answer),
            citations=citations,
            search_queries=queries,
        )

    except Exception as error:
        return LLMObservation(
            model=_model(),
            prompt=prompt,
            trial=trial,
            answer="",
            brand_mentioned=False,
            brand_recommended=False,
            own_domain_cited=False,
            web_search_used=False,
            error=str(error),
        )


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0

    return round((count / total) * 100, 1)


def _level(rate: float) -> str:
    if rate >= 70:
        return "strong"
    if rate >= 30:
        return "moderate"
    return "weak"


def _summary_from(
    observations: list[LLMObservation],
) -> LLMVisibilitySummary:
    successful = [item for item in observations if not item.error]
    total = len(successful)

    mention_rate = _rate(sum(x.brand_mentioned for x in successful), total)
    recommendation_rate = _rate(
        sum(x.brand_recommended for x in successful),
        total,
    )
    citation_rate = _rate(
        sum(x.own_domain_cited for x in successful),
        total,
    )
    grounded_count = sum(x.grounded for x in successful)

    citation_domains = Counter(
        source.domain
        for item in successful
        for source in item.citations
        if source.domain
    )
    competitor_counts = Counter(
        competitor
        for item in successful
        for competitor in item.competitor_mentions
    )
    trust_gap_counts = Counter(
        gap
        for item in successful
        for gap in item.trust_gaps
    )

    return LLMVisibilitySummary(
        observations=len(observations),
        successful_observations=total,
        grounded_observations=grounded_count,
        grounded_observation_rate=_rate(grounded_count, total),
        mention_rate=mention_rate,
        recommendation_rate=recommendation_rate,
        own_domain_citation_rate=citation_rate,
        discovery_status=_level(mention_rate),
        recommendation_confidence=_level(recommendation_rate),
        first_party_citation_authority=_level(citation_rate),
        top_citation_domains=citation_domains.most_common(10),
        competitor_mentions=competitor_counts.most_common(10),
        trust_gaps=trust_gap_counts.most_common(10),
    )


def _prompt_aggregates(
    prompts: list[str],
    observations: list[LLMObservation],
) -> list[PromptAggregate]:
    output: list[PromptAggregate] = []

    for prompt in prompts:
        items = [item for item in observations if item.prompt == prompt]
        successful = [item for item in items if not item.error]
        total = len(successful)

        competitor_counts = Counter(
            competitor
            for item in successful
            for competitor in item.competitor_mentions
        )
        trust_gap_counts = Counter(
            gap
            for item in successful
            for gap in item.trust_gaps
        )

        output.append(
            PromptAggregate(
                prompt=prompt,
                trials=len(items),
                successful_trials=total,
                grounded_trials=sum(item.grounded for item in successful),
                mention_rate=_rate(
                    sum(item.brand_mentioned for item in successful),
                    total,
                ),
                recommendation_rate=_rate(
                    sum(item.brand_recommended for item in successful),
                    total,
                ),
                own_domain_citation_rate=_rate(
                    sum(item.own_domain_cited for item in successful),
                    total,
                ),
                competitor_mentions=competitor_counts.most_common(10),
                trust_gaps=trust_gap_counts.most_common(10),
            )
        )

    return output


def _history_path() -> FilePath | None:
    raw = _setting("llm_visibility_data_path")
    return FilePath(raw) if raw else None


def _persist_run(payload: dict) -> bool:
    path = _history_path()

    if path is None:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return True


def _read_history(brand: str, limit: int) -> list[dict]:
    path = _history_path()

    if path is None or not path.exists():
        return []

    runs: list[dict] = []

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if item.get("brand") == brand:
                runs.append(item)

    return runs[-limit:][::-1]


@router.get(
    "/v1/brands/{brand}/llm-visibility/status",
    response_model=LLMVisibilityStatus,
    dependencies=[Depends(require_api_key)],
    tags=["llm-visibility"],
)
async def get_llm_visibility_status(
    brand: str = Path(pattern="^(nolix|trapx)$"),
) -> LLMVisibilityStatus:
    return LLMVisibilityStatus(
        brand=brand,
        configured=bool(_setting("openai_api_key")),
        model=_model(),
    )


@router.get(
    "/v1/brands/{brand}/llm-visibility/prompts",
    response_model=LLMVisibilityPromptSet,
    dependencies=[Depends(require_api_key)],
    tags=["llm-visibility"],
)
async def get_llm_visibility_prompts(
    brand: str = Path(pattern="^(nolix|trapx)$"),
) -> LLMVisibilityPromptSet:
    return LLMVisibilityPromptSet(
        brand=brand,
        prompts=DEFAULT_PROMPTS[brand],
        competitors=_competitors(brand),
    )


@router.post(
    "/v1/brands/{brand}/llm-visibility/run",
    response_model=LLMVisibilityRunResponse,
    dependencies=[Depends(require_api_key)],
    tags=["llm-visibility"],
)
async def run_llm_visibility_measurement(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    prompt_limit: int = Query(default=1, ge=1, le=10),
    repeat_count: int = Query(default=3, ge=1, le=5),
) -> LLMVisibilityRunResponse:
    if not _setting("openai_api_key"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    prompts = DEFAULT_PROMPTS[brand][:prompt_limit]
    started_at = datetime.now(timezone.utc).isoformat()

    observations: list[LLMObservation] = []

    for prompt in prompts:
        for trial in range(1, repeat_count + 1):
            observations.append(
                await _run_openai(
                    brand=brand,
                    prompt=prompt,
                    trial=trial,
                )
            )

    result = LLMVisibilityRunResponse(
        brand=brand,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        model=_model(),
        prompts_run=len(prompts),
        repeat_count=repeat_count,
        summary=_summary_from(observations),
        prompt_aggregates=_prompt_aggregates(prompts, observations),
        observations=observations,
    )

    result.persisted = _persist_run(result.model_dump())

    return result


@router.get(
    "/v1/brands/{brand}/llm-visibility/history",
    response_model=LLMVisibilityHistoryResponse,
    dependencies=[Depends(require_api_key)],
    tags=["llm-visibility"],
)
async def get_llm_visibility_history(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=10, ge=1, le=100),
) -> LLMVisibilityHistoryResponse:
    return LLMVisibilityHistoryResponse(
        brand=brand,
        runs=_read_history(brand, limit),
    )
