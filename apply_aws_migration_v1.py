from pathlib import Path
import re

PYPROJECT = Path("pyproject.toml")
CONFIG = Path("app/config.py")
ASGI = Path("app/asgi.py")
LLM = Path("app/llm_visibility_api.py")
MCP = Path("app/mcp_server.py")

for path in [PYPROJECT, CONFIG, ASGI, LLM, MCP]:
    if not path.exists():
        raise SystemExit(f"Expected repo file not found: {path}")

pyproject = PYPROJECT.read_text(encoding="utf-8")
config = CONFIG.read_text(encoding="utf-8")
asgi = ASGI.read_text(encoding="utf-8")
llm = LLM.read_text(encoding="utf-8")
mcp = MCP.read_text(encoding="utf-8")

if '"boto3>=' not in pyproject:
    marker = '  "requests>=2.32,<3.0",\n'
    if marker not in pyproject:
        raise SystemExit("Could not find requests dependency.")
    pyproject = pyproject.replace(
        marker,
        marker + '  "boto3>=1.35,<2.0",\n',
        1,
    )

if "llm_visibility_dynamodb_table" not in config:
    marker = "    llm_visibility_data_path: str | None = None\n"
    addition = marker + (
        "\n"
        "    aws_region: str = \"us-east-1\"\n"
        "    llm_visibility_dynamodb_table: str | None = None\n"
        "    mcp_allowed_hosts: str = (\n"
        "        \"localhost,localhost:*,\"\n"
        "        \"127.0.0.1,127.0.0.1:*,\"\n"
        "        \"nolix-trapx-growth-api.onrender.com,\"\n"
        "        \"nolix-trapx-growth-api.onrender.com:*\"\n"
        "    )\n"
    )
    if marker not in config:
        raise SystemExit(
            "Could not find llm_visibility_data_path in config.py."
        )
    config = config.replace(marker, addition, 1)

if "settings = get_settings()" not in asgi:
    marker = (
        "from app.main import app as fastapi_app\n"
        "from app.mcp_server import mcp\n"
    )
    replacement = (
        "from app.config import get_settings\n"
        "from app.main import app as fastapi_app\n"
        "from app.mcp_server import mcp\n"
        "\n"
        "\n"
        "settings = get_settings()\n"
        "allowed_hosts = [\n"
        "    item.strip()\n"
        "    for item in settings.mcp_allowed_hosts.split(\",\")\n"
        "    if item.strip()\n"
        "]\n"
    )
    if marker not in asgi:
        raise SystemExit("Could not find ASGI imports.")
    asgi = asgi.replace(marker, replacement, 1)

old_hosts = '''    allowed_hosts=[
        "nolix-trapx-growth-api.onrender.com",
        "nolix-trapx-growth-api.onrender.com:*",
    ],
'''
if old_hosts in asgi:
    asgi = asgi.replace(
        old_hosts,
        "    allowed_hosts=allowed_hosts,\n",
        1,
    )

storage_import = (
    "from app.services.llm_visibility_store import "
    "persist_visibility_run, read_visibility_runs\n"
)
if storage_import not in llm:
    marker = "from app.security import require_api_key\n"
    if marker not in llm:
        raise SystemExit(
            "Could not find llm_visibility_api import marker."
        )
    llm = llm.replace(
        marker,
        marker + storage_import,
        1,
    )

persist_pattern = re.compile(
    r"def _persist_run\(payload: dict\) -> bool:\n"
    r".*?\n    return True\n",
    re.S,
)
persist_replacement = '''def _persist_run(
    payload: dict,
) -> bool:
    return persist_visibility_run(
        payload,
        get_settings(),
    )
'''
if "return persist_visibility_run(" not in llm:
    llm, count = persist_pattern.subn(
        persist_replacement,
        llm,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not replace _persist_run.")

history_pattern = re.compile(
    r"def _read_history\(brand: str, limit: int\) -> list\[dict\]:\n"
    r".*?"
    r"\n    return runs\[-limit:\]\[::-1\]\n",
    re.S,
)
history_replacement = '''def _read_history(
    brand: str,
    limit: int,
) -> list[dict]:
    return read_visibility_runs(
        brand,
        limit,
        get_settings(),
    )
'''
if "return read_visibility_runs(" not in llm:
    llm, count = history_pattern.subn(
        history_replacement,
        llm,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not replace _read_history.")

old_baseline_prefix = '''def _read_baselines(
    brand: str,
    limit: int,
) -> list[dict]:
    path = _history_path()

    if path is None or not path.exists():
        return []

    grouped: dict[str, list[dict]] = {}

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if item.get("brand") != brand:
                continue

            baseline_id = item.get("baseline_id")

            if not baseline_id:
                continue

            grouped.setdefault(
                str(baseline_id),
                [],
            ).append(item)
'''

new_baseline_prefix = '''def _read_baselines(
    brand: str,
    limit: int,
) -> list[dict]:
    source_runs = read_visibility_runs(
        brand,
        max(limit * 16, 200),
        get_settings(),
    )

    grouped: dict[str, list[dict]] = {}

    for item in source_runs:
        baseline_id = item.get("baseline_id")

        if not baseline_id:
            continue

        grouped.setdefault(
            str(baseline_id),
            [],
        ).append(item)
'''

if old_baseline_prefix in llm:
    llm = llm.replace(
        old_baseline_prefix,
        new_baseline_prefix,
        1,
    )
elif "source_runs = read_visibility_runs(" not in llm:
    raise SystemExit("Could not update _read_baselines.")

technical_block_pattern = re.compile(
    r'@mcp\.tool\(annotations=READ_ONLY\)\n'
    r'async def get_technical_audit\(\n'
    r'.*?'
    r'\n    \)\n',
    re.S,
)
matches = list(technical_block_pattern.finditer(mcp))
if len(matches) > 1:
    for match in reversed(matches[:-1]):
        mcp = mcp[:match.start()] + mcp[match.end():]

PYPROJECT.write_text(pyproject, encoding="utf-8")
CONFIG.write_text(config, encoding="utf-8")
ASGI.write_text(asgi, encoding="utf-8")
LLM.write_text(llm, encoding="utf-8")
MCP.write_text(mcp, encoding="utf-8")

print("Applied AWS Migration V1 repo changes.")
