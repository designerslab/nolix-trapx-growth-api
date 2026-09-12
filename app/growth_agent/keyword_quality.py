from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

BRAND_TERMS = {
    "nolix": {"nolix", "nolix ai", "nolix.ai"},
    "trapx": {"trapx", "trap x", "trapx.io"},
}

LOW_VALUE_TERMS = {
    "login",
    "customer service",
    "phone number",
    "email address",
}

OFF_TOPIC_TERMS = {
    "project zomboid",
    "kfc mouse trap",
    "kfc meme",
    "zombies",
    "attic insulation",
    "cost to insulate attic",
}

TRAPX_RELEVANT_TERMS = {
    "mouse","mice","rat","rodent","trap","traps","exterminator",
    "pest","repellent","peppermint","detector","detection","monitor","monitoring",
}

NOLIX_RELEVANT_TERMS = {
    "water","leak","moisture","pipe","cable","sensor","monitor","monitoring",
    "smart","device","devices","office","apartment","home","rodent","trap",
}

def normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())

def canonical_page(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def is_brand_query(brand: str, query: str) -> bool:
    q = normalize_query(query)
    return any(term in q for term in BRAND_TERMS.get(brand, set()))

def is_low_value_query(query: str) -> bool:
    q = normalize_query(query)
    return any(term in q for term in LOW_VALUE_TERMS)

def is_off_topic_query(query: str) -> bool:
    q = normalize_query(query)
    return any(term in q for term in OFF_TOPIC_TERMS)

def is_relevant_query(brand: str, query: str) -> bool:
    q = normalize_query(query)
    if brand == "trapx":
        return any(term in q for term in TRAPX_RELEVANT_TERMS)
    if brand == "nolix":
        return any(term in q for term in NOLIX_RELEVANT_TERMS)
    return True

def dedupe_keyword_rows(rows: list[dict]) -> list[dict]:
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        query = normalize_query(str(row.get("query") or ""))
        page = canonical_page(row.get("page")) or ""
        key = (query, page)
        candidate = {**row, "page": canonical_page(row.get("page"))}
        current = best.get(key)
        if current is None:
            best[key] = candidate
            continue
        candidate_rank = (
            float(candidate.get("impressions") or 0),
            -float(candidate.get("position") or 9999),
        )
        current_rank = (
            float(current.get("impressions") or 0),
            -float(current.get("position") or 9999),
        )
        if candidate_rank > current_rank:
            best[key] = candidate
    return list(best.values())

def filter_keyword_rows(brand: str, rows: list[dict]) -> list[dict]:
    filtered = []
    for row in rows:
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        if is_brand_query(brand, query):
            continue
        if is_low_value_query(query):
            continue
        if is_off_topic_query(query):
            continue
        if not is_relevant_query(brand, query):
            continue
        filtered.append(row)
    return dedupe_keyword_rows(filtered)
