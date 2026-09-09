# SEO Agent V1 / aws-v11

Adds:
- ranked SEO action queue
- automatic execution routing
- automatic draft preparation
- automatic submission to Human Approval Workflow
- no external write before approval

Install:
1. Copy app/seo_agent/
2. Copy tests/test_seo_agent.py
3. Apply main_changes.txt
4. Apply mcp_server_changes.txt
5. Apply agent_registry_changes.txt
6. Run: python -m pytest -q

After deploy:
GET /v1/agents/seo/nolix/action-queue?limit=10

To prepare an action:
POST /v1/agents/seo/nolix/prepare-action

Prepared actions enter:
requires_human_approval -> approval -> Publishing Gate -> controlled Shopify write
