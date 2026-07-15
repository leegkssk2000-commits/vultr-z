#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc
DIRECT_ORDER_LEAVES = {
    "create_order",
    "place_order",
    "submit_order",
    "send_order",
    "cancel_order",
    "amend_order",
    "private_api",
    "private_endpoint",
}
SENSITIVE_TARGET = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passphrase|private[_-]?key|access[_-]?key)"
)
KNOWN_SECRET_LITERAL = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})"
)
SAFE_LITERAL_VALUES = {
    "",
    "none",
    "null",
    "changeme",
    "change_me",
    "placeholder",
    "example",
    "redacted",
    "<redacted>",
    "disabled",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def target_names(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            yield from target_names(item)
    elif isinstance(node, ast.Attribute):
        yield dotted_name(node)


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_contract_versions(tree: ast.AST) -> list[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if re.fullmatch(r"zico-ceo-adapter/\d+(?:\.\d+){2,}", value):
                found.add(value)
    return sorted(found)


def audit_source(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    tree = ast.parse(text, filename=str(path))

    direct_order_calls: list[dict[str, Any]] = []
    sensitive_literals: list[dict[str, Any]] = []
    classes: set[str] = set()
    functions: set[str] = set()
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            leaf = name.rsplit(".", 1)[-1].lower()
            if leaf in DIRECT_ORDER_LEAVES:
                direct_order_calls.append({"call": name, "line": getattr(node, "lineno", 0)})
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value_node = node.value
            value = literal_string(value_node)
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [name for target in targets for name in target_names(target)]
            sensitive_name = next((name for name in names if SENSITIVE_TARGET.search(name)), None)
            normalized = value.strip().lower()
            secret_shape = bool(KNOWN_SECRET_LITERAL.search(value))
            suspicious_named_literal = bool(
                sensitive_name
                and len(value.strip()) >= 8
                and normalized not in SAFE_LITERAL_VALUES
                and not value.startswith(("http://", "https://"))
            )
            if secret_shape or suspicious_named_literal:
                sensitive_literals.append(
                    {
                        "line": getattr(node, "lineno", 0),
                        "target": sensitive_name or "literal",
                        "reason": "KNOWN_SECRET_SHAPE" if secret_shape else "SENSITIVE_NAMED_LITERAL",
                    }
                )

    return {
        "sha256": sha256_bytes(raw),
        "size_bytes": len(raw),
        "line_count": len(text.splitlines()),
        "classes": sorted(classes),
        "functions": sorted(functions),
        "imports": sorted(imports),
        "contract_versions": extract_contract_versions(tree),
        "direct_order_calls": direct_order_calls,
        "sensitive_literals": sensitive_literals,
    }


def run(args: argparse.Namespace) -> int:
    source = args.source.resolve(strict=True)
    audit = audit_source(source)
    blockers: list[dict[str, Any]] = []

    if audit["sha256"] != args.expected_sha256:
        blockers.append(
            {
                "code": "SOURCE_SHA_CHANGED_SINCE_R01",
                "expected": args.expected_sha256,
                "actual": audit["sha256"],
            }
        )
    if args.expected_contract_version not in audit["contract_versions"]:
        blockers.append(
            {
                "code": "CONTRACT_VERSION_NOT_FOUND",
                "expected": args.expected_contract_version,
                "found": audit["contract_versions"],
            }
        )
    if audit["direct_order_calls"]:
        blockers.append(
            {
                "code": "DIRECT_ORDER_SURFACE_PRESENT",
                "details": audit["direct_order_calls"],
            }
        )
    if audit["sensitive_literals"]:
        blockers.append(
            {
                "code": "EMBEDDED_SECRET_LITERAL_PRESENT",
                "details": audit["sensitive_literals"],
            }
        )

    state = "PASS" if not blockers else "HOLD"
    verdict = "R02_ZICO_SECURE_MIRROR_READY" if not blockers else "R02_ZICO_SECURE_MIRROR_BLOCKED"

    if not blockers:
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, args.destination)
        if sha256_bytes(args.destination.read_bytes()) != audit["sha256"]:
            raise RuntimeError("MIRROR_BYTE_PARITY_FAILED")

        manifest = {
            "schema": "q4r3_zico_canonical_manifest_v1",
            "canonical_name": "Zico",
            "component": "Zico",
            "contract_version": args.expected_contract_version,
            "runtime_unit": args.unit,
            "runtime_source_path": str(source),
            "git_mirror_path": str(args.destination),
            "source_sha256": audit["sha256"],
            "mirror_sha256": audit["sha256"],
            "byte_parity": True,
            "direct_order_calls": 0,
            "embedded_secret_literals": 0,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "mirrored_at": now_iso(),
        }
        atomic_json(args.manifest, manifest)

    evidence = {
        "schema": "q4r3_team_advisor_r02_zico_secure_mirror_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "source": str(source),
        "destination": str(args.destination),
        "unit": args.unit,
        "expected_sha256": args.expected_sha256,
        "expected_contract_version": args.expected_contract_version,
        "audit": audit,
        "blockers": blockers,
        "mirror_written": not blockers,
        "runtime_mutation_performed": False,
        "systemd_mutation_performed": False,
        "authority": {
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
        },
        "action": "hold",
    }
    atomic_json(args.evidence, evidence)
    print(json.dumps({
        "state": state,
        "verdict": verdict,
        "source_sha256": audit["sha256"],
        "direct_order_calls": len(audit["direct_order_calls"]),
        "embedded_secret_literals": len(audit["sensitive_literals"]),
        "mirror_written": not blockers,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if not blockers else 2


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--source", type=Path, required=True)
    value.add_argument("--destination", type=Path, required=True)
    value.add_argument("--manifest", type=Path, required=True)
    value.add_argument("--evidence", type=Path, required=True)
    value.add_argument("--unit", required=True)
    value.add_argument("--expected-sha256", required=True)
    value.add_argument("--expected-contract-version", required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
