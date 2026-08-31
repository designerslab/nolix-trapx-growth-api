from pathlib import Path

MAIN = Path("app/main.py")
MCP = Path("app/mcp_server.py")

main_text = MAIN.read_text(encoding="utf-8")
mcp_text = MCP.read_text(encoding="utf-8")

main_import = "from app.product_catalog_api import router as product_catalog_router\n"
if main_import not in main_text:
    marker = "from app.config import get_settings\n"
    if marker not in main_text:
        raise SystemExit("Could not find app.config import in app/main.py")
    main_text = main_text.replace(marker, marker + main_import, 1)

include_line = "app.include_router(product_catalog_router)\n"
if include_line not in main_text:
    if "app.include_router(revenue_router)\n" in main_text:
        main_text = main_text.replace(
            "app.include_router(revenue_router)\n",
            "app.include_router(revenue_router)\napp.include_router(product_catalog_router)\n",
            1,
        )
    else:
        marker = "BRANDED_TERMS = {"
        if marker not in main_text:
            raise SystemExit("Could not find router insertion point in app/main.py")
        main_text = main_text.replace(marker, include_line + "\n" + marker, 1)

mcp_functions = """

@mcp.tool(annotations=READ_ONLY)
async def get_shopify_products_enriched(
    brand: str,
    limit: int = 50,
    page_cursor: str | None = None,
) -> dict:
    \\\"\\\"\\\"Get enriched read-only Shopify product catalog data.\\\"\\\"\\\"
    brand = brand.lower().strip()
    if brand not in {\\\"nolix\\\", \\\"trapx\\\"}:
        raise ValueError(\\\"brand must be either 'nolix' or 'trapx'\\\")

    params = {\\\"limit\\\": limit}
    if page_cursor:
        params[\\\"page_cursor\\\"] = page_cursor

    return await _get(
        f\\\"/v1/brands/{brand}/shopify/products/enriched\\\",
        params,
    )


@mcp.tool(annotations=READ_ONLY)
async def audit_shopify_products(
    brand: str,
    limit: int = 250,
) -> dict:
    \\\"\\\"\\\"Audit Shopify product catalog completeness without changing Shopify.\\\"\\\"\\\"
    brand = brand.lower().strip()
    if brand not in {\\\"nolix\\\", \\\"trapx\\\"}:
        raise ValueError(\\\"brand must be either 'nolix' or 'trapx'\\\")

    return await _get(
        f\\\"/v1/brands/{brand}/shopify/products/audit\\\",
        {\\\"limit\\\": limit},
    )
"""

mcp_functions = mcp_functions.replace('\\\\\\"', '"')

if "async def get_shopify_products_enriched(" not in mcp_text:
    mcp_text = mcp_text.rstrip() + mcp_functions + "\n"

MAIN.write_text(main_text, encoding="utf-8")
MCP.write_text(mcp_text, encoding="utf-8")

print("Patched app/main.py and app/mcp_server.py successfully.")
