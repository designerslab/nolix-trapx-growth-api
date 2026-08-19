# Nolix & TrapX Growth API

Small, read-only FastAPI service that will provide trusted source data to the Growth Agent and, later, a GPT Action.

## Current scope

- `GET /health` — service and integration readiness
- `GET /v1/brands/{brand}/shopify/products` — read-only Shopify product inventory for `nolix` or `trapx`; supports `limit` and `page_cursor`
- GSC and GA4 are intentionally placeholders until the Shopify integration is verified.

No endpoint modifies Shopify, Google Search Console, or GA4 data. Tokens are read from `.env` on the server and are neither returned nor stored in source files.

## Local setup

1. Create a virtual environment: `python -m venv .venv`
2. Activate it in PowerShell: `.\.venv\Scripts\Activate.ps1`
3. Install the project: `python -m pip install -e ".[dev]"`
4. Copy `.env.example` to `.env`. Leave Shopify tokens blank to run the API shell safely.
5. Run: `uvicorn app.main:app --reload`
6. Open `http://localhost:8000/docs` for the generated OpenAPI contract.

Run tests with `pytest`.

## Shopify setup, next

Create one dedicated Growth Read-Only custom app per Shopify store with only the Admin API scopes required for reading product data (initially `read_products`). Put each store domain and token in the matching environment variable. Do not reuse the article-writing app token, which has broader write permission. Do not use a storefront token or commit a `.env` file.

After this endpoint is working against both stores, add GSC read access and GA4 reporting access as separate service modules and routes.

## Deployment / GPT Action

Deploy behind HTTPS, set `GROWTH_API_KEY`, and configure the GPT Action to send that secret in the `X-API-Key` header. The generated OpenAPI schema is available at `/openapi.json`.

### Render deployment

The included `render.yaml` provisions a FastAPI web service with a `/health` health check. Push this folder to a **private** Git repository, then in Render select **New → Blueprint** and select that repository. Enter the Shopify values and a long random `GROWTH_API_KEY` in Render's Environment section; do not upload or commit `.env`.

After deployment, set `GROWTH_API_PUBLIC_URL` to the assigned HTTPS service URL and redeploy. Verify `https://your-service.onrender.com/health` before connecting the GPT Action.
