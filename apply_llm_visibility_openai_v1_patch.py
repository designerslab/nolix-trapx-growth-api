from pathlib import Path

CONFIG = Path("app/config.py")
MAIN = Path("app/main.py")
MCP = Path("app/mcp_server.py")

config_text = CONFIG.read_text(encoding="utf-8")
main_text = MAIN.read_text(encoding="utf-8")
mcp_text = MCP.read_text(encoding="utf-8")

config_fields = '''
    openai_api_key: SecretStr | None = None
    openai_llm_visibility_model: str = "gpt-5.6-luna"

    nolix_llm_competitors: str | None = None
    trapx_llm_competitors: str | None = None

    llm_visibility_data_path: str | None = None
'''

if "openai_api_key:" not in config_text:
    marker = "    growth_api_key: SecretStr | None = None\n"
    if marker not in config_text:
        raise SystemExit("Could not find growth_api_key in app/config.py")
    config_text = config_text.replace(marker, marker + config_fields, 1)

main_import = (
    "from app.llm_visibility_api import "
    "router as llm_visibility_router\n"
)

if main_import not in main_text:
    marker = "from app.config import get_settings\n"
    if marker not in main_text:
        raise SystemExit("Could not find config import in app/main.py")
    main_text = main_text.replace(marker, marker + main_import, 1)

include_line = "app.include_router(llm_visibility_router)\n"

if include_line not in main_text:
    inserted = False
    for marker in (
        "app.include_router(technical_audit_router)\n",
        "app.include_router(product_catalog_router)\n",
        "app.include_router(revenue_router)\n",
    ):
        if marker in main_text:
            main_text = main_text.replace(marker, marker + include_line, 1)
            inserted = True
            break
    if not inserted:
        raise SystemExit("Could not find router insertion point in app/main.py")

measurement_annotation = '''
MEASUREMENT = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=True,
)
'''

if "MEASUREMENT = ToolAnnotations(" not in mcp_text:
    marker = '''READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=False,
)
'''
    if marker not in mcp_text:
        raise SystemExit("Could not find READ_ONLY annotation in app/mcp_server.py")
    mcp_text = mcp_text.replace(marker, marker + measurement_annotation, 1)

mcp_block = '''

@mcp.tool(annotations=READ_ONLY)
async def get_llm_visibility_status(
    brand: str,
) -> dict:
    """Check OpenAI LLM visibility measurement configuration."""
    brand = brand.lower().strip()
    if brand not in {"nolix", "trapx"}:
        raise ValueError("brand must be either 'nolix' or 'trapx'")

    return await _get(
        f"/v1/brands/{brand}/llm-visibility/status"
    )


@mcp.tool(annotations=READ_ONLY)
async def get_llm_visibility_prompts(
    brand: str,
) -> dict:
    """Get the default LLM visibility prompt set."""
    brand = brand.lower().strip()
    if brand not in {"nolix", "trapx"}:
        raise ValueError("brand must be either 'nolix' or 'trapx'")

    return await _get(
        f"/v1/brands/{brand}/llm-visibility/prompts"
    )


@mcp.tool(annotations=MEASUREMENT)
async def run_llm_visibility_measurement(
    brand: str,
    prompt_limit: int = 1,
) -> dict:
    """Run OpenAI web-search visibility measurement.

    This performs paid OpenAI API calls and may incur web-search/token charges.
    """
    brand = brand.lower().strip()
    if brand not in {"nolix", "trapx"}:
        raise ValueError("brand must be either 'nolix' or 'trapx'")

    headers = {}
    if GROWTH_API_KEY:
        headers["X-API-Key"] = GROWTH_API_KEY

    async with httpx.AsyncClient(
        timeout=300.0,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            (
                f"{GROWTH_API_PUBLIC_URL}"
                f"/v1/brands/{brand}/llm-visibility/run"
            ),
            params={"prompt_limit": prompt_limit},
            headers=headers,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Growth API returned {response.status_code}: "
                f"{response.text[:1000]}"
            )

        return response.json()


@mcp.tool(annotations=READ_ONLY)
async def get_llm_visibility_history(
    brand: str,
    limit: int = 10,
) -> dict:
    """Get persisted OpenAI LLM visibility history."""
    brand = brand.lower().strip()
    if brand not in {"nolix", "trapx"}:
        raise ValueError("brand must be either 'nolix' or 'trapx'")

    return await _get(
        f"/v1/brands/{brand}/llm-visibility/history",
        {"limit": limit},
    )
'''

if "async def run_llm_visibility_measurement(" not in mcp_text:
    mcp_text = mcp_text.rstrip() + "\n" + mcp_block + "\n"

CONFIG.write_text(config_text, encoding="utf-8")
MAIN.write_text(main_text, encoding="utf-8")
MCP.write_text(mcp_text, encoding="utf-8")

print("Patched OpenAI LLM Visibility V1.")
