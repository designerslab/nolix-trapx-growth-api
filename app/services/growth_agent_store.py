import json
from datetime import datetime, timezone
from uuid import uuid4


def _table(settings):
    import boto3
    name = str(
        getattr(settings, "llm_visibility_dynamodb_table", "") or ""
    ).strip()
    if not name:
        raise RuntimeError("DynamoDB growth-agent storage is not configured.")
    region = str(getattr(settings, "aws_region", "") or "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(name)


def save_event(*, brand, kind, payload, settings, event_id=None):
    now = datetime.now(timezone.utc).isoformat()
    event_id = event_id or uuid4().hex
    sk = f"growth#{kind}#{now}#{event_id}"
    record = {
        "brand": brand,
        "kind": kind,
        "event_id": event_id,
        "created_at": now,
        **payload,
    }
    _table(settings).put_item(
        Item={
            "pk": brand,
            "sk": sk,
            "kind": f"growth_{kind}",
            "created_at": now,
            "payload_json": json.dumps(record, separators=(",", ":")),
        }
    )
    return record


def list_events(*, brand, settings, kind=None, limit=100):
    table = _table(settings)
    response = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": brand,
            ":prefix": f"growth#{kind}#" if kind else "growth#",
        },
        ScanIndexForward=False,
        Limit=limit,
    )
    out = []
    for item in response.get("Items", []):
        if item.get("payload_json"):
            out.append(json.loads(item["payload_json"]))
    return out
