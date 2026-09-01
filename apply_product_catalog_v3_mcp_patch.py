from pathlib import Path

MCP = Path("app/mcp_server.py")
text = MCP.read_text(encoding="utf-8")

block = """
@mcp.tool(annotations=READ_ONLY)
async def get_shopify_catalog_health(
    brand: str,
    limit: int = 250,
) -> dict:
    \"\"\"Get report-friendly Shopify product catalog health.\"\"\"
    brand = brand.lower().strip()

    if brand not in {"nolix", "trapx"}:
        raise ValueError(
            "brand must be either 'nolix' or 'trapx'"
        )

    return await _get(
        (
            f"/v1/brands/{brand}/shopify/products/"
            "catalog-health"
        ),
        {"limit": limit},
    )
"""

if "async def get_shopify_catalog_health(" not in text:
    MCP.write_text(
        text.rstrip() + "\n\n" + block + "\n",
        encoding="utf-8",
    )
    print("Added get_shopify_catalog_health MCP tool.")
else:
    print("MCP catalog-health tool already present; no change.")
