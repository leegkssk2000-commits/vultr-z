from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_COMPOSITE_SOURCE_LIVE_PATCH_V1"
SUFFIXES = {".py", ".json", ".yaml", ".yml"}
EXCLUDED_TOKENS = ("backup", "archive", "quarantine", "fixture", "test", "__pycache__")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def excluded(path: Path) -> bool:
    return any(token in part.casefold() for part in path.parts for token in EXCLUDED_TOKENS)


def rows(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    unique: dict[str, Path] = {}
    for path in paths:
        try:
            if not path.is_file() or path.suffix.casefold() not in SUFFIXES or excluded(path):
                continue
            resolved = path.resolve()
            try:
                key = resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                key = "external:" + resolved.as_posix()
            unique[key] = resolved
        except OSError:
            continue
    result: list[dict[str, Any]] = []
    for key in sorted(unique):
        path = unique[key]
        raw = path.read_bytes()
        result.append(
            {
                "path": key,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "git_tracked": False,
                "source_scope": "LIVE_VPS",
            }
        )
    return result


def under(root: Path, relative: str) -> list[Path]:
    base = root / relative
    if not base.is_dir():
        return []
    return [path for path in base.rglob("*")]


def build(root: Path) -> dict[str, Any]:
    zbot = under(root, "backend/zbot")
    for relative in ("backend/api/zbot.py", "backend/advisors/zbot.py", "backend/zbot.py"):
        candidate = root / relative
        if candidate.is_file():
            zbot.append(candidate)

    lico = []
    for relative in (
        "backend/api/lico.py",
        "backend/api/lico_market_safety.py",
        "backend/contracts/ZOS_LICO_CONTRACT_v1.json",
        "backend/lico_market_safety_core.py",
        "backend/lico_market_safety_runtime.py",
        "backend/lico.py",
    ):
        candidate = root / relative
        if candidate.is_file():
            lico.append(candidate)
    lico.extend(under(root, "backend/lico"))

    zico = []
    for candidate in (
        Path("/opt/zico-ceo-canonical-adapter/adapter.py"),
        root / "canonical/zico/control.py",
        root / "backend/zico.py",
    ):
        if candidate.is_file():
            zico.append(candidate)

    zlice = under(root, "backend/zlice") + under(root, "canonical/zlice")
    delivery = root / "backend/alimi/zlice_delivery_entry.py"
    if delivery.is_file():
        zlice.append(delivery)

    bindings = {
        "ZBOT": {"selection_policy": "ACTIVE_ZBOT_PACKAGE_OR_ENTRYPOINT", "files": rows(root, zbot)},
        "LICO": {"selection_policy": "ACTIVE_LICO_CODE_AND_CONTRACT", "files": rows(root, lico)},
        "ZICO": {"selection_policy": "ACTIVE_SYSTEMD_RESOLVED_ZICO_ADAPTER", "files": rows(root, zico)},
        "ZLICE": {"selection_policy": "ACTIVE_ZLICE_PACKAGE_OR_DELIVERY_ENTRY", "files": rows(root, zlice)},
    }
    missing = [module_id for module_id, binding in bindings.items() if not binding["files"]]
    result = {
        "schema_version": "zel.composite.source_live_patch.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "root": str(root),
        "state": "PASS_LIVE_SOURCE_PATCH" if not missing else "HOLD_LIVE_SOURCE_PATCH",
        "bindings": bindings,
        "missing": missing,
        "active_data_b_1m_mutated": False,
        "runtime_registry_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    return result


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for relative in (
            "backend/zbot/core.py",
            "backend/api/lico.py",
            "backend/zico.py",
            "backend/alimi/zlice_delivery_entry.py",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative + "\n", encoding="utf-8")
        row = build(root)
        assert row["state"] == "PASS_LIVE_SOURCE_PATCH", row
        assert all(row["bindings"][module]["files"] for module in ("ZBOT", "LICO", "ZICO", "ZLICE"))
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    row = build(args.root.resolve())
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
