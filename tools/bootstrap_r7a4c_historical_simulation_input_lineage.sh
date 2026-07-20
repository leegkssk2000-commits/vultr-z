#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=2
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT

export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4C_START' \
  'MODE=READ_ONLY_HISTORICAL_SIMULATION_INPUT_LINEAGE' \
  'HISTORICAL_MARKET_DATA_READ_ALLOWED=true' \
  'SCENARIO_PLAN_GENERATION_ALLOWED=true' \
  'HISTORICAL_SIMULATION_EXECUTION_ALLOWED=false' \
  'EXECUTION_COST_APPLICATION_ALLOWED=false' \
  'HISTORICAL_REPLAY_EXECUTION_ALLOWED=false' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A4C_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4c.XXXXXX)" || exit 2
for path in \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json \
  tools/r7a4c_historical_simulation_input_lineage.py \
  tools/r7a4c_historical_simulation_input_lineage_entry.py \
  tests/test_r7a4c_historical_simulation_input_lineage.py \
  tests/test_r7a4c_historical_market_array_adapter.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A4C_BOOTSTRAP_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4c_historical_simulation_input_lineage.py" \
  "$TMP/tools/r7a4c_historical_simulation_input_lineage_entry.py"
then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A4C_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4c_historical_simulation_input_lineage.py" \
  "$TMP/tests/test_r7a4c_historical_market_array_adapter.py"
then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A4C_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4c_historical_simulation_input_lineage_entry.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
RC=$?

MANIFEST="$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
if [[ -f "$MANIFEST" ]]; then
  python3 - "$MANIFEST" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print("MARKET_REJECTION_DIAGNOSTIC_ERROR=" + json.dumps(f"{type(exc).__name__}:{exc}"))
else:
    rows = payload.get("rejected_market_sources", [])
    normalized = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or "UNKNOWN")
        category = reason.split(":", 2)[1] if reason.startswith(("ValueError:", "TypeError:", "ParserError:")) and ":" in reason else reason.split(":", 1)[0]
        normalized.append({"path": str(row.get("path") or ""), "reason": reason, "category": category})
    histogram = Counter(item["category"] for item in normalized)
    print("REJECTED_MARKET_COUNT=" + str(len(normalized)))
    print("REJECTED_MARKET_REASON_HISTOGRAM=" + json.dumps(sorted(histogram.items(), key=lambda pair: (-pair[1], pair[0])), ensure_ascii=False))
    print("REJECTED_MARKET_SAMPLE=" + json.dumps(normalized[:20], ensure_ascii=False))
PY

  python3 - "$ROOT" "$MANIFEST" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
manifest_path = Path(sys.argv[2])
max_bytes = 16 * 1024 * 1024
max_depth = 4
max_nodes = 200
max_candidates = 24

aliases = {
    "open", "o", "high", "h", "low", "l", "close", "c",
    "timestamp", "time", "ts", "datetime", "date",
    "volume", "vol", "v", "symbol", "timeframe", "interval",
}
ohlc = {"open", "high", "low", "close"}


def norm_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def type_name(value: Any) -> str:
    return type(value).__name__


def first_non_null(items: list[Any]) -> Any:
    for item in items[:20]:
        if item is not None:
            return item
    return None


def inspect_payload(payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "root_type": type_name(payload),
        "root_keys": sorted(str(key) for key in payload.keys())[:40] if isinstance(payload, dict) else [],
        "root_length": len(payload) if isinstance(payload, (dict, list)) else None,
        "array_candidates": [],
        "columnar_candidates": [],
    }
    stack: list[tuple[str, Any, int]] = [("$", payload, 0)]
    visited = 0
    while stack and visited < max_nodes:
        path, node, depth = stack.pop()
        visited += 1
        if depth > max_depth:
            continue
        if isinstance(node, dict):
            normalized_keys = {norm_key(key): key for key in node.keys()}
            ohlc_hits = sorted(key for key in normalized_keys if key in ohlc)
            list_lengths = {
                norm_key(key): len(value)
                for key, value in node.items()
                if isinstance(value, list)
            }
            if len(ohlc_hits) >= 4 and list_lengths:
                result["columnar_candidates"].append({
                    "path": path,
                    "keys": sorted(normalized_keys)[:40],
                    "ohlc_hits": ohlc_hits,
                    "list_lengths": dict(sorted(list_lengths.items())[:20]),
                })
            for key, child in list(node.items())[:80]:
                if isinstance(child, (dict, list)):
                    stack.append((f"{path}.{key}", child, depth + 1))
        elif isinstance(node, list):
            sample = first_non_null(node)
            sample_keys: list[str] = []
            key_hits: list[str] = []
            ohlc_hits: list[str] = []
            if isinstance(sample, dict):
                normalized_keys = {norm_key(key) for key in sample.keys()}
                sample_keys = sorted(normalized_keys)[:40]
                key_hits = sorted(key for key in normalized_keys if key in aliases)
                ohlc_hits = sorted(key for key in normalized_keys if key in ohlc)
            result["array_candidates"].append({
                "path": path,
                "length": len(node),
                "sample_type": type_name(sample),
                "sample_keys": sample_keys,
                "key_hits": key_hits,
                "ohlc_hits": ohlc_hits,
            })
            if isinstance(sample, (dict, list)):
                stack.append((f"{path}[0]", sample, depth + 1))
        if len(result["array_candidates"]) >= max_candidates and len(result["columnar_candidates"]) >= max_candidates:
            break
    result["array_candidates"] = result["array_candidates"][:max_candidates]
    result["columnar_candidates"] = result["columnar_candidates"][:max_candidates]
    result["visited_nodes"] = visited
    return result


try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception as exc:
    print("JSON_SHAPE_PROBE_ERROR=" + json.dumps(f"MANIFEST:{type(exc).__name__}:{exc}"))
    raise SystemExit(0)

rows = manifest.get("rejected_market_sources", [])
probes: list[dict[str, Any]] = []
for row in rows if isinstance(rows, list) else []:
    if not isinstance(row, dict):
        continue
    reason = str(row.get("reason") or "")
    if "MARKET_COLUMNS_MISSING" not in reason:
        continue
    repo_path = str(row.get("path") or "")
    item: dict[str, Any] = {"path": repo_path, "prior_reason": reason}
    try:
        candidate = (root / repo_path).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("PATH_OUTSIDE_ROOT")
        item["exists"] = candidate.is_file()
        if not candidate.is_file():
            item["probe_error"] = "FILE_MISSING"
            probes.append(item)
            continue
        size = candidate.stat().st_size
        item["size_bytes"] = size
        if size > max_bytes:
            item["probe_error"] = f"FILE_TOO_LARGE:{size}"
            probes.append(item)
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        item.update(inspect_payload(payload))
    except Exception as exc:
        item["probe_error"] = f"{type(exc).__name__}:{exc}"
    probes.append(item)

print("JSON_SHAPE_PROBE_COUNT=" + str(len(probes)))
print("JSON_SHAPE_PROBE=" + json.dumps(probes, ensure_ascii=False, sort_keys=True))
PY
fi

echo 'R7A4C_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
