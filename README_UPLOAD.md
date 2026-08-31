# Nolix / TrapX Agent Inspection Patch

Purpose: make the weekly Growth Agent investigate flagged actions before asking a human to investigate them.

## Files

1. `app/services/agent_inspection.py` — NEW FILE. Upload exactly at this path.
2. `snippets/schemas_addition.py.txt` — paste into `app/schemas.py`.
3. `snippets/main_addition.py.txt` — import + endpoint to paste into `app/main.py`.
4. `snippets/mcp_server_addition.py.txt` — paste into `app/mcp_server.py`.
5. `AGENT_REPORTING_RULE.md` — rule to add to the weekly agent/skill instructions.

## What the endpoint does

`GET /v1/brands/{brand}/ga4/referral-inspection`

Required query parameters:
- `start_date`
- `end_date`
- `previous_start_date`
- `previous_end_date`

It queries GA4 with:
- `sessionSource`
- `sessionMedium`
- `landingPagePlusQueryString`

It returns:
- agent_inspected
- current vs previous Referral totals
- top referral sources
- sessions/users/engaged sessions per source
- 0-100 inspection score
- classification
- reasons
- agent conclusion
- human_action_required

## Important interpretation

The score is a conservative `bot_or_low_quality_risk` score, not proof that a visitor is a bot. The agent should never claim bot traffic solely from a high score. A high score means the source deserves deeper review/exclusion consideration.

## Test after deploy

Use the existing API key header and call:

`/v1/brands/nolix/ga4/referral-inspection?start_date=2026-08-17&end_date=2026-08-23&previous_start_date=2026-08-10&previous_end_date=2026-08-16`

Expected behavior:
- HTTP 200
- `agent_inspected: true`
- Referral source list is populated if GA4 exposes source/medium for those sessions.
- Current sessions should reconcile approximately with the Referral total from `/ga4/channels`.

Then restart/redeploy the MCP service so the new `inspect_ga4_referrals` tool becomes available to the agent.
