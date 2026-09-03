from pathlib import Path

API = Path("app/llm_visibility_api.py")
MCP = Path("app/mcp_server.py")

api = API.read_text(encoding="utf-8")
mcp = MCP.read_text(encoding="utf-8")

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} marker not found.")
    return text.replace(old, new, 1)

if "BRANDED_PROMPT_INDEX" not in api:
    marker = 'BRAND_SITES = {"nolix": "nolix.ai", "trapx": "trapx.io"}\n'
    api = replace_once(
        api,
        marker,
        marker + '\nBRANDED_PROMPT_INDEX = {"nolix": 7, "trapx": 5}\n',
        "BRAND_SITES",
    )

if "baseline_id: str | None = None" not in api:
    old = """class LLMVisibilityRunResponse(BaseModel):
    brand: str
    started_at: str
    completed_at: str
    model: str
    prompts_run: int
    repeat_count: int
    summary: LLMVisibilitySummary
"""
    new = """class LLMVisibilityRunResponse(BaseModel):
    brand: str
    baseline_id: str | None = None
    prompt_index: int | None = None
    expected_prompts: int
    started_at: str
    completed_at: str
    model: str
    prompts_run: int
    repeat_count: int
    summary: LLMVisibilitySummary
"""
    api = replace_once(api, old, new, "run response")

if "class LLMBaselineHistoryResponse" not in api:
    old = """class LLMVisibilityHistoryResponse(BaseModel):
    brand: str
    runs: list[dict]
"""
    new = old + """

class LLMBaselineHistoryResponse(BaseModel):
    brand: str
    baselines: list[dict]
"""
    api = replace_once(api, old, new, "baseline history model")

if "def _read_baselines(" not in api:
    marker = '@router.get(\n    "/v1/brands/{brand}/llm-visibility/status",'
    helper = r"""
def _baseline_summary_from_records(
    brand: str,
    baseline_id: str,
    records: list[dict],
) -> dict:
    expected_prompts = len(DEFAULT_PROMPTS[brand])

    prompt_indexes = sorted({
        int(item["prompt_index"])
        for item in records
        if item.get("prompt_index") is not None
    })

    observations: list[LLMObservation] = []
    for item in records:
        for observation in item.get("observations") or []:
            try:
                observations.append(
                    LLMObservation.model_validate(observation)
                )
            except Exception:
                continue

    overall = _summary_from(observations)

    branded_index = BRANDED_PROMPT_INDEX[brand]
    unbranded_observations: list[LLMObservation] = []

    for item in records:
        if item.get("prompt_index") == branded_index:
            continue

        for observation in item.get("observations") or []:
            try:
                unbranded_observations.append(
                    LLMObservation.model_validate(observation)
                )
            except Exception:
                continue

    unbranded = _summary_from(unbranded_observations)
    completed_prompts = len(prompt_indexes)

    started_values = [
        str(item.get("started_at"))
        for item in records
        if item.get("started_at")
    ]
    completed_values = [
        str(item.get("completed_at"))
        for item in records
        if item.get("completed_at")
    ]

    return {
        "baseline_id": baseline_id,
        "status": (
            "complete"
            if completed_prompts == expected_prompts
            else "partial"
        ),
        "expected_prompts": expected_prompts,
        "completed_prompts": completed_prompts,
        "prompt_indexes": prompt_indexes,
        "observations": len(observations),
        "started_at": min(started_values) if started_values else None,
        "completed_at": max(completed_values) if completed_values else None,
        "overall": overall.model_dump(),
        "unbranded": unbranded.model_dump(),
    }


def _read_baselines(
    brand: str,
    limit: int,
) -> list[dict]:
    path = _history_path()

    if path is None or not path.exists():
        return []

    grouped: dict[str, list[dict]] = {}

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if item.get("brand") != brand:
                continue

            baseline_id = item.get("baseline_id")

            if not baseline_id:
                continue

            grouped.setdefault(
                str(baseline_id),
                [],
            ).append(item)

    baselines = [
        _baseline_summary_from_records(
            brand,
            baseline_id,
            records,
        )
        for baseline_id, records in grouped.items()
    ]

    baselines.sort(
        key=lambda item: item.get("completed_at") or "",
        reverse=True,
    )

    selected = baselines[:limit]

    for index, current in enumerate(selected):
        previous = (
            selected[index + 1]
            if index + 1 < len(selected)
            else None
        )

        if previous is None:
            current["previous_baseline_id"] = None
            current["delta"] = None
            continue

        current["previous_baseline_id"] = previous["baseline_id"]

        co = current["overall"]
        po = previous["overall"]
        cu = current["unbranded"]
        pu = previous["unbranded"]

        current["delta"] = {
            "overall_mention_rate": round(
                co["mention_rate"] - po["mention_rate"],
                1,
            ),
            "overall_recommendation_rate": round(
                co["recommendation_rate"]
                - po["recommendation_rate"],
                1,
            ),
            "overall_own_domain_citation_rate": round(
                co["own_domain_citation_rate"]
                - po["own_domain_citation_rate"],
                1,
            ),
            "unbranded_mention_rate": round(
                cu["mention_rate"] - pu["mention_rate"],
                1,
            ),
            "unbranded_recommendation_rate": round(
                cu["recommendation_rate"]
                - pu["recommendation_rate"],
                1,
            ),
            "unbranded_own_domain_citation_rate": round(
                cu["own_domain_citation_rate"]
                - pu["own_domain_citation_rate"],
                1,
            ),
        }

    return selected


"""
    api = replace_once(api, marker, helper + marker, "router insertion")

if "baseline_id: str | None = Query(" not in api:
    old = """async def run_llm_visibility_measurement(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    prompt_limit: int = Query(default=1, ge=1, le=10),
    repeat_count: int = Query(default=3, ge=1, le=5),
    prompt_index: int | None = Query(default=None, ge=0),
) -> LLMVisibilityRunResponse:
"""
    new = """async def run_llm_visibility_measurement(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    prompt_limit: int = Query(default=1, ge=1, le=10),
    repeat_count: int = Query(default=3, ge=1, le=5),
    prompt_index: int | None = Query(default=None, ge=0),
    baseline_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
) -> LLMVisibilityRunResponse:
"""
    api = replace_once(api, old, new, "REST run signature")

if "expected_prompts=len(DEFAULT_PROMPTS[brand])" not in api:
    old = """    result = LLMVisibilityRunResponse(
        brand=brand,
        started_at=started_at,
"""
    new = """    result = LLMVisibilityRunResponse(
        brand=brand,
        baseline_id=baseline_id,
        prompt_index=prompt_index,
        expected_prompts=len(DEFAULT_PROMPTS[brand]),
        started_at=started_at,
"""
    api = replace_once(api, old, new, "result constructor")

if '"/v1/brands/{brand}/llm-visibility/baselines"' not in api:
    api += r"""


@router.get(
    "/v1/brands/{brand}/llm-visibility/baselines",
    response_model=LLMBaselineHistoryResponse,
    dependencies=[Depends(require_api_key)],
    tags=["llm-visibility"],
    operation_id="get_llm_visibility_baselines",
)
async def get_llm_visibility_baselines(
    brand: str = Path(pattern="^(nolix|trapx)$"),
    limit: int = Query(default=10, ge=1, le=100),
) -> LLMBaselineHistoryResponse:
    return LLMBaselineHistoryResponse(
        brand=brand,
        baselines=_read_baselines(
            brand,
            limit,
        ),
    )
"""

if "baseline_id: str | None = None" not in mcp:
    old = """async def run_llm_visibility_measurement(
    brand: str,
    prompt_limit: int = 1,
    repeat_count: int = 3,
    prompt_index: int | None = None,
) -> dict:
"""
    new = """async def run_llm_visibility_measurement(
    brand: str,
    prompt_limit: int = 1,
    repeat_count: int = 3,
    prompt_index: int | None = None,
    baseline_id: str | None = None,
) -> dict:
"""
    mcp = replace_once(mcp, old, new, "MCP run signature")

if 'params["baseline_id"] = baseline_id' not in mcp:
    old = """        if prompt_index is not None:
            params["prompt_index"] = prompt_index

        response = await client.post(
"""
    new = """        if prompt_index is not None:
            params["prompt_index"] = prompt_index

        if baseline_id:
            params["baseline_id"] = baseline_id

        response = await client.post(
"""
    mcp = replace_once(mcp, old, new, "MCP params")

if "async def get_llm_visibility_baselines(" not in mcp:
    mcp += r"""


@mcp.tool(annotations=READ_ONLY)
async def get_llm_visibility_baselines(
    brand: str,
    limit: int = 10,
) -> dict:
    # Get grouped persisted GEO baselines with week-over-week deltas.
    brand = brand.lower().strip()

    if brand not in {"nolix", "trapx"}:
        raise ValueError(
            "brand must be either 'nolix' or 'trapx'"
        )

    return await _get(
        f"/v1/brands/{brand}/llm-visibility/baselines",
        {"limit": limit},
    )
"""

API.write_text(api, encoding="utf-8")
MCP.write_text(mcp, encoding="utf-8")

print("Applied LLM Visibility V2.3.")
