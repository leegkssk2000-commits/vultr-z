#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
REBUILD = ROOT / "backend/research/rebuild"
SHADOW_PATH = REBUILD / "g5_clean_runner_shadow_v1.json"
STALE_PATH = REBUILD / "g5_data_stale_evidence_v1.json"
CUTOVER_PATH = REBUILD / "g5_clean_runner_cutover_receipt_v1.json"
POST_PATH = REBUILD / "g5_clean_runner_post_cutover_3bar_v1.json"
ANCHOR_PATH = REBUILD / "g5_clean_runner_cutover_anchor_v1.json"


class CutoverProgressError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CutoverProgressError(f"OBJECT_REQUIRED:{path}")
    return value


def maybe_json(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.exists() else None


def sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha_json(result)
    return result


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def parse_iso(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def derive(
    shadow: Mapping[str, Any],
    stale: Mapping[str, Any],
    current_cutover: Mapping[str, Any],
    anchor: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not (
        shadow.get("state") == "CLEAN_RUNNER_SHADOW_PASS"
        and shadow.get("shadow_3bar_pass") is True
        and int(shadow.get("consecutive_complete_bar_count") or 0) >= 3
        and shadow.get("source_parity") is True
        and shadow.get("child_parity") is True
        and int(shadow.get("duplicate") or 0) == 0
        and int(shadow.get("lookahead") or 0) == 0
    ):
        raise CutoverProgressError("CLEAN_RUNNER_3BAR_PASS_REQUIRED")
    if not (
        stale.get("authority_created") is True
        and stale.get("data_stale_authority_allowed") is True
        and stale.get("timestamp_integrity") == "PASS"
        and isinstance(stale.get("authority_value"), (int, float))
        and not isinstance(stale.get("authority_value"), bool)
        and float(stale["authority_value"]) > 0
        and stale.get("authority_unit") == "ms"
    ):
        raise CutoverProgressError("DATA_STALE_AUTHORITY_REQUIRED")
    if current_cutover.get("automatic_cutover") is not False:
        raise CutoverProgressError("AUTOMATIC_CUTOVER_MUST_REMAIN_FALSE")
    if current_cutover.get("eligible") is not True and anchor is None:
        raise CutoverProgressError("CUTOVER_ELIGIBILITY_REQUIRED")

    if anchor is None:
        anchor_bar = shadow.get("bar3")
        if not anchor_bar:
            raise CutoverProgressError("CUTOVER_ANCHOR_BAR_REQUIRED")
        anchor = receipt({
            "schema_version": "zel.g5.clean_runner.cutover_anchor.v1",
            "state": "CUTOVER_EXECUTED_ANCHOR_FROZEN",
            "executed_at_utc": now_iso(),
            "anchor_bar_close_utc": anchor_bar,
            "approval_source": "USER_AUTHORIZED_G5_AUTOMATION",
            "automatic_cutover": False,
            "clean_runner_authority": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "formal_credit": 0,
        })
    elif anchor.get("schema_version") != "zel.g5.clean_runner.cutover_anchor.v1":
        raise CutoverProgressError("CUTOVER_ANCHOR_SCHEMA_DRIFT")

    anchor_ms = parse_iso(str(anchor["anchor_bar_close_utc"]))
    bars: list[str] = []
    for name in ("bar1", "bar2", "bar3"):
        value = shadow.get(name)
        if value and parse_iso(str(value)) > anchor_ms:
            bars.append(str(value))
    bars = sorted(set(bars), key=parse_iso)
    post_count = len(bars)
    passed = post_count >= 3

    cutover = receipt({
        "schema_version": "zel.g5.clean_runner.cutover_receipt.v1",
        "generated_at_utc": now_iso(),
        "state": "CLEAN_RUNNER_PRODUCTION_READY" if passed else "CUTOVER_EXECUTED_WAIT_POST_3BAR",
        "eligible": True,
        "executed": True,
        "clean_runner_authority": True,
        "production_ready": passed,
        "legacy_state": "RETIRED_DIAGNOSTIC_ONLY",
        "automatic_cutover": False,
        "binding_epoch": shadow.get("binding_epoch"),
        "binding_gate_current_child_only": shadow.get("binding_gate_current_child_only") is True,
        "cutover_anchor_bar_close_utc": anchor["anchor_bar_close_utc"],
        "post_cutover_bars": post_count,
        "formal_credit": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    })
    post = receipt({
        "schema_version": "zel.g5.clean_runner.post_cutover_3bar.v1",
        "generated_at_utc": now_iso(),
        "state": "POST_CUTOVER_3BAR_PASS" if passed else "POST_CUTOVER_3BAR_ACCUMULATING",
        "cutover_executed": True,
        "cutover_anchor_bar_close_utc": anchor["anchor_bar_close_utc"],
        "bar1": bars[0] if len(bars) >= 1 else None,
        "bar2": bars[1] if len(bars) >= 2 else None,
        "bar3": bars[2] if len(bars) >= 3 else None,
        "post_cutover_bars": post_count,
        "post_cutover_3bar_pass": passed,
        "production_ready": passed,
        "source_parity": shadow.get("source_parity") is True,
        "child_parity": shadow.get("child_parity") is True,
        "duplicate": int(shadow.get("duplicate") or 0),
        "lookahead": int(shadow.get("lookahead") or 0),
        "formal_credit": 0,
    })
    return dict(anchor), cutover, post


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow", type=Path, default=SHADOW_PATH)
    parser.add_argument("--stale", type=Path, default=STALE_PATH)
    parser.add_argument("--cutover", type=Path, default=CUTOVER_PATH)
    parser.add_argument("--post", type=Path, default=POST_PATH)
    parser.add_argument("--anchor", type=Path, default=ANCHOR_PATH)
    args = parser.parse_args()
    anchor, cutover, post = derive(
        read_json(args.shadow), read_json(args.stale), read_json(args.cutover), maybe_json(args.anchor)
    )
    write_json(args.anchor, anchor)
    write_json(args.cutover, cutover)
    write_json(args.post, post)
    print(json.dumps({
        "cutover_state": cutover["state"],
        "post_state": post["state"],
        "post_cutover_bars": post["post_cutover_bars"],
        "production_ready": post["production_ready"],
        "formal_credit": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
