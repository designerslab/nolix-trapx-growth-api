import json
from datetime import datetime,timezone
def _table(settings):
    import boto3
    name=str(getattr(settings,"llm_visibility_dynamodb_table","") or "").strip()
    if not name: raise RuntimeError("DynamoDB publishing audit storage is not configured.")
    region=str(getattr(settings,"aws_region","") or "us-east-1")
    return boto3.resource("dynamodb",region_name=region).Table(name)
def get_publish_audit(*,brand,idempotency_key,settings):
    i=_table(settings).get_item(Key={"pk":brand,"sk":f"publish#{idempotency_key}"}).get("Item")
    return json.loads(i["payload_json"]) if i and i.get("payload_json") else None
def save_publish_audit(*,brand,idempotency_key,draft_id,actor,content_hash,shopify_article,settings):
    now=datetime.now(timezone.utc).isoformat()
    r={"brand":brand,"draft_id":draft_id,"idempotency_key":idempotency_key,"actor":actor,"content_hash":content_hash,"destination":"shopify_blog_article","shopify_article":shopify_article,"created_at":now,"publish_executed":True,"publicly_published":False}
    _table(settings).put_item(Item={"pk":brand,"sk":f"publish#{idempotency_key}","kind":"content_publish_audit","draft_id":draft_id,"created_at":now,"payload_json":json.dumps(r,separators=(",",":"))},ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)")
    return r
