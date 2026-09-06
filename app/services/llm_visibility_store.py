from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


def _setting(settings: Any, name: str) -> str | None:
    value = getattr(settings, name, None)

    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _dynamodb_table(settings: Any):
    table_name = _setting(
        settings,
        "llm_visibility_dynamodb_table",
    )

    if not table_name:
        return None

    import boto3

    region = _setting(
        settings,
        "aws_region",
    ) or "us-east-1"

    resource = boto3.resource(
        "dynamodb",
        region_name=region,
    )

    return resource.Table(table_name)


def persist_visibility_run(
    payload: dict,
    settings: Any,
) -> bool:
    table = _dynamodb_table(settings)

    if table is not None:
        try:
            completed_at = str(
                payload.get("completed_at") or ""
            )
            brand = str(
                payload.get("brand") or ""
            )

            baseline_id = payload.get(
                "baseline_id"
            )
            prompt_index = payload.get(
                "prompt_index"
            )

            item = {
                "pk": brand,
                "sk": (
                    f"{completed_at}#"
                    f"{uuid4().hex}"
                ),
                "kind": "llm_visibility_run",
                "completed_at": completed_at,
                "payload_json": json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }

            if baseline_id is not None:
                item["baseline_id"] = str(
                    baseline_id
                )

            if prompt_index is not None:
                item["prompt_index"] = int(
                    prompt_index
                )

            table.put_item(
                Item=item
            )

            return True

        except Exception:
            logger.exception(
                "Failed to persist LLM visibility "
                "run to DynamoDB."
            )
            return False

    raw_path = _setting(
        settings,
        "llm_visibility_data_path",
    )

    if not raw_path:
        return False

    try:
        path = Path(
            raw_path
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                )
                + "\n"
            )

        return True

    except Exception:
        logger.exception(
            "Failed to persist LLM visibility "
            "run to JSONL fallback."
        )
        return False


def read_visibility_runs(
    brand: str,
    limit: int,
    settings: Any,
) -> list[dict]:
    table = _dynamodb_table(
        settings
    )

    if table is not None:
        try:
            from boto3.dynamodb.conditions import Key

            target = max(
                int(limit),
                1,
            )

            items: list[dict] = []
            last_key = None

            while len(items) < target:
                kwargs = {
                    "KeyConditionExpression": Key(
                        "pk"
                    ).eq(
                        brand
                    ),
                    "ScanIndexForward": False,
                    "Limit": min(
                        max(
                            target - len(items),
                            1,
                        ),
                        1000,
                    ),
                }

                if last_key:
                    kwargs[
                        "ExclusiveStartKey"
                    ] = last_key

                response = table.query(
                    **kwargs
                )

                for item in response.get(
                    "Items",
                    [],
                ):
                    raw = item.get(
                        "payload_json"
                    )

                    if not raw:
                        continue

                    try:
                        payload = json.loads(
                            raw
                        )
                    except json.JSONDecodeError:
                        continue

                    items.append(
                        payload
                    )

                    if len(items) >= target:
                        break

                last_key = response.get(
                    "LastEvaluatedKey"
                )

                if not last_key:
                    break

            return items[:target]

        except Exception:
            logger.exception(
                "Failed to read LLM visibility "
                "runs from DynamoDB."
            )
            return []

    raw_path = _setting(
        settings,
        "llm_visibility_data_path",
    )

    if not raw_path:
        return []

    path = Path(
        raw_path
    )

    if not path.exists():
        return []

    runs: list[dict] = []

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                line = line.strip()

                if not line:
                    continue

                try:
                    item = json.loads(
                        line
                    )
                except json.JSONDecodeError:
                    continue

                if item.get(
                    "brand"
                ) == brand:
                    runs.append(
                        item
                    )

    except Exception:
        logger.exception(
            "Failed to read LLM visibility "
            "runs from JSONL fallback."
        )
        return []

    return runs[
        -limit:
    ][::-1]