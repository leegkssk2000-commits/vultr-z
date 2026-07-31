from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.tools import zel_component_gemini_v2 as active

VERSION = "ZEL_COMPONENT_GEMINI_V2_GUARD"


def read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def guard(result_path: str, registry_path: str, previous_path: str | None, out_path: str) -> int:
    result = read(result_path)
    fingerprint = str(result.get("data_fingerprint") or "")
    out = Path(out_path)
    out.mkdir(parents=True, exist_ok=True)
    previous = read(previous_path) if previous_path and Path(previous_path).is_file() else {}
    if previous.get("data_fingerprint") == fingerprint and previous.get("GEMINI_USED") is True:
        artifact = {
            "schema_version": "2.1",
            "version": VERSION,
            "state": "SKIP_UNCHANGED_COMPONENT_FINGERPRINT",
            "GEMINI_USED": False,
            "data_fingerprint": fingerprint,
            "previous_receipt_sha256": previous.get("receipt_sha256"),
            "hypotheses": [],
            "replay_allowed": False,
            **active.SAFE,
        }
        artifact["receipt_sha256"] = active.stable_sha(artifact)
        active.write_json(out / "gemini_artifact.json", artifact)
        print(artifact["state"], artifact["receipt_sha256"])
        return 0
    rc = active.run(result, read(registry_path), out)
    artifact_path = out / "gemini_artifact.json"
    artifact = read(artifact_path)
    artifact["data_fingerprint"] = fingerprint
    artifact["same_fingerprint_repeat_forbidden"] = True
    artifact.pop("receipt_sha256", None)
    artifact["receipt_sha256"] = active.stable_sha(artifact)
    active.write_json(artifact_path, artifact)
    print("PASS_COMPONENT_GEMINI_V2_GUARD", artifact["state"], artifact["receipt_sha256"])
    return rc


def fixture(out_path: str) -> int:
    out = Path(out_path); out.mkdir(parents=True, exist_ok=True)
    previous = {"data_fingerprint": "f" * 64, "GEMINI_USED": True, "receipt_sha256": "p" * 64}
    result = {"data_fingerprint": "f" * 64}
    registry = {"sources": []}
    for name, value in (("previous.json", previous), ("result.json", result), ("registry.json", registry)):
        (out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rc = guard(str(out / "result.json"), str(out / "registry.json"), str(out / "previous.json"), str(out / "artifact"))
    artifact = read(out / "artifact" / "gemini_artifact.json")
    assert rc == 0 and artifact["state"] == "SKIP_UNCHANGED_COMPONENT_FINGERPRINT"
    assert artifact["GEMINI_USED"] is False and artifact["replay_allowed"] is False
    print("PASS_COMPONENT_GEMINI_V2_GUARD_FIXTURE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run"); run.add_argument("--result", required=True); run.add_argument("--video-registry", required=True); run.add_argument("--previous"); run.add_argument("--out", required=True)
    test = sub.add_parser("fixture"); test.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "fixture": return fixture(args.out)
    return guard(args.result, args.video_registry, args.previous, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
