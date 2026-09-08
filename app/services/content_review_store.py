from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _setting(settings: Any, name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _table(settings: Any):
    table_name = _setting(settings, "llm_visibility_dynamodb_table")
    if not table_name:
        return None

    import boto3

    region = _setting(settings, "aws_region") or "us-east-1"
    return boto3.resource(
        "dynamodb",
        region_name=region,
    ).Table(table_name)


def create_review_record(
    *,
    brand: str,
    draft_payload: dict,
    reviewer_hint: str | None,
    settings: Any,
) -> dict:
    table = _table(settings)
    if table is None:
        raise RuntimeError("DynamoDB review storage is not configured.")

    draft_id = uuid4().hex
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "draft_id": draft_id,
        "brand": brand,
        "status": "requires_human_approval",
        "reviewer_hint": reviewer_hint,
        "reviewer": None,
        "review_notes": None,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
        "publish_allowed": False,
        "draft_payload": draft_payload,
    }

    table.put_item(
        Item={
            "pk": brand,
            "sk": f"draft#{draft_id}",
            "kind": "content_draft_review",
            "draft_id": draft_id,
            "status": record["status"],
            "created_at": now,
            "updated_at": now,
            "payload_json": json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        ConditionExpression=(
            "attribute_not_exists(pk) AND attribute_not_exists(sk)"
        ),
    )

    return record


def get_review_record(
    *,
    brand: str,
    draft_id: str,
    settings: Any,
) -> dict | None:
    table = _table(settings)
    if table is None:
        raise RuntimeError("DynamoDB review storage is not configured.")

    response = table.get_item(
        Key={"pk": brand, "sk": f"draft#{draft_id}"}
    )
    item = response.get("Item")
    if not item or not item.get("payload_json"):
        return None

    return json.loads(item["payload_json"])


def list_review_records(
    *,
    brand: str,
    limit: int,
    settings: Any,
) -> list[dict]:
    table = _table(settings)
    if table is None:
        raise RuntimeError("DynamoDB review storage is not configured.")

    from boto3.dynamodb.conditions import Key

    response = table.query(
        KeyConditionExpression=(
            Key("pk").eq(brand)
            & Key("sk").begins_with("draft#")
        ),
        Limit=min(max(int(limit), 1), 100),
    )

    records = []
    for item in response.get("Items", []):
        raw = item.get("payload_json")
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    records.sort(
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )
    return records[:limit]


def update_review_record(
    *,
    brand: str,
    draft_id: str,
    decision: str,
    reviewer: str,
    notes: str | None,
    settings: Any,
) -> dict:
    table = _table(settings)
    if table is None:
        raise RuntimeError("DynamoDB review storage is not configured.")

    existing = get_review_record(
        brand=brand,
        draft_id=draft_id,
        settings=settings,
    )
    if existing is None:
        raise KeyError(draft_id)

    if decision not in {"approved", "needs_changes", "rejected"}:
        raise ValueError(
            "decision must be approved, needs_changes, or rejected"
        )

    now = datetime.now(timezone.utc).isoformat()
    existing["status"] = decision
    existing["reviewer"] = reviewer
    existing["review_notes"] = notes
    existing["updated_at"] = now
    existing["reviewed_at"] = now
    existing["publish_allowed"] = False

    table.update_item(
        Key={"pk": brand, "sk": f"draft#{draft_id}"},
        UpdateExpression=(
            "SET #status = :status, updated_at = :updated_at, "
            "payload_json = :payload_json"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": decision,
            ":updated_at": now,
            ":payload_json": json.dumps(
                existing,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        ConditionExpression=(
            "attribute_exists(pk) AND attribute_exists(sk)"
        ),
    )

    return existing
