#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
REBUILD = ROOT / "backend/research/rebuild"
SHADOW_PATH = REBUILD / "g5_clean_runner_shadow_v1.json"
POST_PATH = REBUILD / "g5_clean_runner_post_cutover_3bar_v1.json"


class PostCutoverBindError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PostCutoverBindError(f"OBJECT_REQUIRED:{path}")
    return value


def sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha_json(result)
    return result


def bind(shadow: Mapping[str, Any], post: Mapping[str, Any]) -> dict[str, Any]:
    if post.get("schema_version") != "zel.g5.clean_runner.post_cutover_3bar.v1":
        raise PostCutoverBindError("POST_SCHEMA_DRIFT")
    if post.get("post_cutover_3bar_pass") is not True:
        return dict(shadow)
    if not (
        post.get("production_ready") is True
        and post.get("source_parity") is True
        and post.get("child_parity") is True
        and int(post.get("duplicate") or 0) == 0
        and int(post.get("lookahead") or 0) == 0
        and int(post.get("formal_credit") or 0) == 0
        and all(post.get(name) for name in ("bar1", "bar2", "bar3"))
    ):
        raise PostCutoverBindError("POST_3BAR_INTEGRITY_REQUIRED")
    if not (
        shadow.get("state") == "CLEAN_RUNNER_SHADOW_PASS"
        and shadow.get("shadow_3bar_pass") is True
        and shadow.get("source_parity") is True
        and shadow.get("child_parity") is True
        and int(shadow.get("duplicate") or 0) == 0
        and int(shadow.get("lookahead") or 0) == 0
    ):
        raise PostCutoverBindError("SHADOW_INTEGRITY_REQUIRED")
    core = dict(shadow)
    core.pop("receipt_sha256", None)
    core.update({
        "post_cutover_3bar_pass": True,
        "post_cutover_bar1": post["bar1"],
        "post_cutover_bar2": post["bar2"],
        "post_cutover_bar3": post["bar3"],
        "post_cutover_receipt_sha256": post.get("receipt_sha256"),
        "production_ready": True,
        "formal_credit": 0,
    })
    return receipt(core)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow", type=Path, default=SHADOW_PATH)
    parser.add_argument("--post", type=Path, default=POST_PATH)
    args = parser.parse_args()
    shadow = read_json(args.shadow)
    post = read_json(args.post)
    result = bind(shadow, post)
    if result != shadow:
        args.shadow.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print("PASS_POST_CUTOVER_SHADOW_BIND")
    else:
        print("WAIT_POST_CUTOVER_3BAR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
