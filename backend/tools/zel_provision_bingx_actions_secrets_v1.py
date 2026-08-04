from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_PROVISION_BINGX_ACTIONS_SECRETS_V2"
TARGET_NAMES = ("BINGX_API_KEY", "BINGX_SECRET_KEY")
KEY_ALIASES = {
    "bingxapikey",
    "bingxkey",
    "bingxaccesskey",
    "bingxapiaccesskey",
    "bingxkeyid",
}
SECRET_ALIASES = {
    "bingxsecretkey",
    "bingxapisecret",
    "bingxsecret",
    "bingxapisecretkey",
}
SEARCH_ROOTS = (
    Path("/home/z"),
    Path("/opt"),
    Path("/etc/z-os"),
    Path("/etc/zel"),
    Path("/etc/default"),
    Path("/etc/systemd/system"),
)
MAX_FILE_BYTES = 1_048_576
NAME_HINTS = (
    ".env",
    "env",
    "secret",
    "credential",
    "config",
    "bingx",
    "exchange",
    "key",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".service",
)
ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+|Environment=)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$"
)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def classify_name(value: str, context: str = "") -> str | None:
    normalized = normalize_name(value)
    ctx = normalize_name(context)
    if normalized in KEY_ALIASES:
        return "BINGX_API_KEY"
    if normalized in SECRET_ALIASES:
        return "BINGX_SECRET_KEY"
    if "bingx" in ctx:
        if normalized in {"apikey", "accesskey", "key", "keyid"}:
            return "BINGX_API_KEY"
        if normalized in {"secret", "secretkey", "apisecret", "apisecretkey"}:
            return "BINGX_SECRET_KEY"
    return None


def unquote(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
        value = value[1:-1]
    else:
        value = value.split(" #", 1)[0].strip()
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        return ""
    return value


def candidate_files() -> list[Path]:
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                if size <= 0 or size > MAX_FILE_BYTES:
                    continue
                low = path.name.lower()
                if not any(hint in low for hint in NAME_HINTS):
                    continue
                found.append(path)
            except (OSError, PermissionError):
                continue
    return sorted(set(found))


def add_value(values: dict[str, str], name: str, raw: Any, context: str = "") -> None:
    target = classify_name(name, context)
    if target is None or not isinstance(raw, (str, int, float)):
        return
    value = unquote(str(raw))
    if len(value) < 8:
        return
    values[target] = value


def walk_json(node: Any, values: dict[str, str], context: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_context = f"{context}.{key}" if context else str(key)
            add_value(values, str(key), value, context)
            walk_json(value, values, child_context)
    elif isinstance(node, list):
        for item in node:
            walk_json(item, values, context)


def parse_candidate(path: Path) -> tuple[dict[str, str], list[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, PermissionError):
        return {}, []
    values: dict[str, str] = {}
    aliases: list[str] = []
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        source_name = match.group("name")
        target = classify_name(source_name, path.name)
        if target is None:
            continue
        value = unquote(match.group("value"))
        if len(value) >= 8:
            values[target] = value
            aliases.append(source_name)
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("{", "[")):
        try:
            walk_json(json.loads(text), values, path.name)
        except json.JSONDecodeError:
            pass
    return values, sorted(set(aliases))


def find_unique_pair() -> tuple[dict[str, str] | None, list[str], list[str], str | None]:
    pairs: dict[str, tuple[dict[str, str], list[str], set[str]]] = {}
    partials: dict[str, list[tuple[str, str]]] = {name: [] for name in TARGET_NAMES}
    for path in candidate_files():
        values, aliases = parse_candidate(path)
        for name in TARGET_NAMES:
            if name in values:
                partials[name].append((str(path), values[name]))
        if all(name in values for name in TARGET_NAMES):
            material = {name: values[name] for name in TARGET_NAMES}
            fingerprint = stable_sha(material)
            if fingerprint not in pairs:
                pairs[fingerprint] = (material, [], set())
            pairs[fingerprint][1].append(str(path))
            pairs[fingerprint][2].update(aliases)
    if len(pairs) == 1:
        material, paths, aliases = next(iter(pairs.values()))
        return material, paths, sorted(aliases), None
    if len(pairs) > 1:
        return None, [], [], "MULTIPLE_DISTINCT_BINGX_CREDENTIAL_PAIRS"

    unique: dict[str, set[str]] = {
        name: {value for _, value in partials[name]} for name in TARGET_NAMES
    }
    if all(len(unique[name]) == 1 for name in TARGET_NAMES):
        material = {name: next(iter(unique[name])) for name in TARGET_NAMES}
        paths = sorted({path for name in TARGET_NAMES for path, _ in partials[name]})
        return material, paths, [], None
    return None, [], [], "BINGX_CREDENTIAL_PAIR_NOT_FOUND"


def run_quiet(command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=os.environ.copy(),
    )


def provision(repo: str, values: dict[str, str]) -> tuple[bool, str | None, list[str]]:
    gh = shutil.which("gh")
    if not gh:
        return False, "GH_CLI_NOT_FOUND", []
    auth = run_quiet([gh, "auth", "status", "--hostname", "github.com"])
    if auth.returncode != 0:
        return False, "GH_AUTH_NOT_AVAILABLE_ON_VPS", []
    for name in TARGET_NAMES:
        result = run_quiet(
            [gh, "secret", "set", name, "--repo", repo],
            stdin=values[name],
        )
        if result.returncode != 0:
            return False, f"GH_SECRET_SET_FAILED:{name}", []
    listed = run_quiet([gh, "secret", "list", "--repo", repo, "--json", "name"])
    if listed.returncode != 0:
        return False, "GH_SECRET_LIST_FAILED", []
    try:
        names = sorted(
            str(row.get("name"))
            for row in json.loads(listed.stdout or "[]")
            if isinstance(row, dict) and row.get("name")
        )
    except json.JSONDecodeError:
        return False, "GH_SECRET_LIST_INVALID_JSON", []
    if not all(name in names for name in TARGET_NAMES):
        return False, "GH_SECRET_NAME_VERIFICATION_FAILED", names
    return True, None, names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    values, paths, aliases, discovery_blocker = find_unique_pair()
    passed = False
    blocker = discovery_blocker
    names: list[str] = []
    if values is not None and blocker is None:
        passed, blocker, names = provision(args.repo, values)

    receipt = {
        "schema_version": "zel.bingx.actions_secret_provision.receipt.v2",
        "version": VERSION,
        "state": "PASS_BINGX_ACTIONS_SECRETS_PROVISIONED" if passed else "HOLD_BINGX_ACTIONS_SECRETS_PROVISION",
        "evaluated_at": utc_now(),
        "repository": args.repo,
        "source_file_count": len(paths),
        "source_path_sha256": stable_sha(sorted(paths)) if paths else None,
        "detected_alias_names": aliases,
        "verified_secret_names": [name for name in TARGET_NAMES if name in names],
        "secret_values_logged": False,
        "secret_values_artifacted": False,
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "blocker": blocker,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    out.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "blocker": blocker, "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
