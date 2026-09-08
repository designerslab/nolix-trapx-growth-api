# Human Approval / Draft Review Workflow V1

This milestone adds persistent review state while keeping publishing disabled.

## State flow

`requires_human_approval -> approved | needs_changes | rejected`

Even when status is `approved`:

`publish_allowed = false`

Publishing is intentionally NOT implemented in this milestone.

## Storage

The workflow reuses the existing DynamoDB table configured by:

`LLM_VISIBILITY_DYNAMODB_TABLE`

No new AWS table is required.

Records use:
- partition key: brand
- sort key: `draft#{draft_id}`
- kind: `content_draft_review`

## Install

1. Add `app/services/content_review_store.py`
2. Add `app/content_review_api.py`
3. Add `tests/test_content_review_api.py`
4. Apply `main_changes.txt`
5. Apply `mcp_server_changes.txt`
6. Run:

```powershell
python -m pytest -q
```

## AWS REST test

First generate a draft as before so `$d` contains the Content Generator response.

Submit it for review:

```powershell
$reviewBody = @{
    draft_payload = $d
    reviewer_hint = "Human review required"
} | ConvertTo-Json -Depth 30

$review = Invoke-RestMethod `
  -Method POST `
  -Uri "https://no-c5cdefdf346043a2bca11a744be31437.ecs.ap-south-1.on.aws/v1/brands/nolix/content-reviews" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $reviewBody

$review.draft_id
$review.status
$review.publish_allowed
```

Expected:

```text
requires_human_approval
False
```

Then record a review decision:

```powershell
$decisionBody = @{
    decision = "approved"
    reviewer = "human-reviewer"
    notes = "Reviewed manually. Approved for future publishing workflow."
} | ConvertTo-Json

$approved = Invoke-RestMethod `
  -Method POST `
  -Uri "https://no-c5cdefdf346043a2bca11a744be31437.ecs.ap-south-1.on.aws/v1/brands/nolix/content-reviews/$($review.draft_id)/decision" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $decisionBody

$approved.status
$approved.reviewer
$approved.publish_allowed
```

Expected:

```text
approved
human-reviewer
False
```

That final `False` is intentional: approval and permission to publish remain separate.

## Growth Agent behavior

- Generate a draft.
- Submit it with `submit_content_draft_for_review`.
- Only call `review_content_draft` after an explicit human decision.
- Never infer approval from praise, draft quality, or silence.
- `publish_allowed` must remain false throughout V1.
