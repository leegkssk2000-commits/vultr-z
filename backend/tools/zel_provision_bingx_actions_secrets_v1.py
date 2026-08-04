from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_PROVISION_BINGX_ACTIONS_SECRETS_V4"
TARGET_NAMES = ("BINGX_API_KEY", "BINGX_SECRET_KEY")
KEY_ALIASES = {"bingxapikey", "bingxkey", "bingxaccesskey", "bingxapiaccesskey", "bingxkeyid"}
SECRET_ALIASES = {"bingxsecretkey", "bingxapisecret", "bingxsecret", "bingxapisecretkey"}
SEARCH_ROOTS = (Path("/home/z"), Path("/opt"), Path("/etc/z-os"), Path("/etc/zel"), Path("/etc/default"), Path("/etc/systemd/system"))
PRUNE_DIRS = {".git", ".cache", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "artifacts", "checkpoints", "logs", "tmp"}
MAX_FILE_BYTES = 1_048_576
NAME_HINTS = (".env", "env", "secret", "credential", "config", "bingx", "exchange", "key", ".json", ".yaml", ".yml", ".toml", ".ini", ".service")
ASSIGNMENT = re.compile(r"^\s*(?:export\s+|Environment=)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$")
BINGX_BASE = "https://open-api.bingx.com"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


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
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
        value = value[1:-1]
    else:
        value = value.split(" #", 1)[0].strip()
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        return ""
    return value


def add_value(values: dict[str, str], name: str, raw: Any, context: str = "") -> str | None:
    target = classify_name(name, context)
    if target is None or not isinstance(raw, (str, int, float)):
        return None
    value = unquote(str(raw))
    if len(value) < 8:
        return None
    values[target] = value
    return name


def walk_json(node: Any, values: dict[str, str], aliases: set[str], context: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_context = f"{context}.{key}" if context else str(key)
            alias = add_value(values, str(key), value, context)
            if alias:
                aliases.add(alias)
            walk_json(value, values, aliases, child_context)
    elif isinstance(node, list):
        for item in node:
            walk_json(item, values, aliases, context)


def parse_text(text: str, context: str) -> tuple[dict[str, str], set[str]]:
    values: dict[str, str] = {}
    aliases: set[str] = set()
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        alias = add_value(values, match.group("name"), match.group("value"), context)
        if alias:
            aliases.add(alias)
    if text.lstrip().startswith(("{", "[")):
        try:
            walk_json(json.loads(text), values, aliases, context)
        except json.JSONDecodeError:
            pass
    return values, aliases


def source_priority(source: str) -> int:
    low = source.lower()
    if low.startswith("process_env:"):
        score = 100
    elif low.startswith("/home/z/z/"):
        score = 85
    elif low.startswith("/etc/"):
        score = 75
    elif low.startswith("/opt/"):
        score = 65
    else:
        score = 50
    if any(token in low for token in ("backup", "archive", "old", "disabled", "sample", "example", "test", "vst")):
        score -= 40
    return score


def process_environment_pairs() -> list[tuple[dict[str, str], str, set[str]]]:
    out: list[tuple[dict[str, str], str, set[str]]] = []
    proc = Path("/proc")
    if not proc.exists():
        return out
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "environ").read_bytes()
        except (OSError, PermissionError):
            continue
        values, aliases = parse_text(raw.replace(b"\x00", b"\n").decode("utf-8", errors="ignore"), "process_env")
        if all(name in values for name in TARGET_NAMES):
            out.append((values, f"process_env:{entry.name}", aliases))
    return out


def candidate_files() -> list[Path]:
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [d for d in dirs if d not in PRUNE_DIRS and not d.startswith(".")]
            for filename in files:
                low = filename.lower()
                if not any(hint in low for hint in NAME_HINTS):
                    continue
                path = Path(current) / filename
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    size = path.stat().st_size
                    if 0 < size <= MAX_FILE_BYTES:
                        found.append(path)
                except (OSError, PermissionError):
                    continue
    return sorted(set(found))


def file_pairs() -> list[tuple[dict[str, str], str, set[str]]]:
    out: list[tuple[dict[str, str], str, set[str]]] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, PermissionError):
            continue
        values, aliases = parse_text(text, path.name)
        if all(name in values for name in TARGET_NAMES):
            out.append((values, str(path), aliases))
    return out


def live_validate(values: dict[str, str]) -> tuple[bool, str | None]:
    params = {"recvWindow": 5000, "timestamp": int(time.time() * 1000)}
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    signature = hmac.new(values["BINGX_SECRET_KEY"].encode(), query.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        f"{BINGX_BASE}/openApi/swap/v2/user/commissionRate?{query}&signature={signature}",
        headers={"X-BX-APIKEY": values["BINGX_API_KEY"], "X-SOURCE-KEY": "BX-AI-SKILL", "User-Agent": VERSION},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read())
    except Exception:
        return False, None
    if int(payload.get("code", -1)) != 0:
        return False, stable_sha({"code": payload.get("code"), "msg": payload.get("msg")})
    return True, stable_sha(payload.get("data"))


def select_pair() -> tuple[dict[str, str] | None, list[str], list[str], int, int, str | None]:
    grouped: dict[str, dict[str, Any]] = {}
    for values, source, aliases in process_environment_pairs() + file_pairs():
        material = {name: values[name] for name in TARGET_NAMES}
        fingerprint = stable_sha(material)
        row = grouped.setdefault(fingerprint, {"values": material, "sources": [], "aliases": set(), "priority": -999})
        row["sources"].append(source)
        row["aliases"].update(aliases)
        row["priority"] = max(int(row["priority"]), source_priority(source))
    if not grouped:
        return None, [], [], 0, 0, "BINGX_CREDENTIAL_PAIR_NOT_FOUND"
    valid: list[dict[str, Any]] = []
    for row in grouped.values():
        ok, response_sha = live_validate(row["values"])
        if ok:
            row["response_sha"] = response_sha
            valid.append(row)
    if not valid:
        return None, [], [], len(grouped), 0, "NO_VALID_LIVE_BINGX_CREDENTIAL_PAIR"
    valid.sort(key=lambda row: int(row["priority"]), reverse=True)
    top_priority = int(valid[0]["priority"])
    top = [row for row in valid if int(row["priority"]) == top_priority]
    if len(top) != 1:
        return None, [], [], len(grouped), len(valid), "MULTIPLE_VALID_LIVE_BINGX_PAIRS_SAME_PRIORITY"
    selected = top[0]
    return selected["values"], sorted(selected["sources"]), sorted(selected["aliases"]), len(grouped), len(valid), None


def run_quiet(command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, env=os.environ.copy())


def provision(repo: str, values: dict[str, str]) -> tuple[bool, str | None, list[str]]:
    gh = shutil.which("gh")
    if not gh:
        return False, "GH_CLI_NOT_FOUND", []
    if run_quiet([gh, "auth", "status", "--hostname", "github.com"]).returncode != 0:
        return False, "GH_AUTH_NOT_AVAILABLE_ON_VPS", []
    for name in TARGET_NAMES:
        if run_quiet([gh, "secret", "set", name, "--repo", repo], stdin=values[name]).returncode != 0:
            return False, f"GH_SECRET_SET_FAILED:{name}", []
    listed = run_quiet([gh, "secret", "list", "--repo", repo, "--json", "name"])
    if listed.returncode != 0:
        return False, "GH_SECRET_LIST_FAILED", []
    try:
        names = sorted(str(row.get("name")) for row in json.loads(listed.stdout or "[]") if isinstance(row, dict) and row.get("name"))
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
    values, sources, aliases, pair_count, valid_count, blocker = select_pair()
    passed = False
    names: list[str] = []
    if values is not None and blocker is None:
        passed, blocker, names = provision(args.repo, values)
    receipt = {
        "schema_version": "zel.bingx.actions_secret_provision.receipt.v4",
        "version": VERSION,
        "state": "PASS_BINGX_ACTIONS_SECRETS_PROVISIONED" if passed else "HOLD_BINGX_ACTIONS_SECRETS_PROVISION",
        "evaluated_at": utc_now(),
        "repository": args.repo,
        "discovered_pair_count": pair_count,
        "live_valid_pair_count": valid_count,
        "selected_source_count": len(sources),
        "selected_source_identity_sha256": stable_sha(sorted(sources)) if sources else None,
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
    print(json.dumps({"state": receipt["state"], "blocker": blocker, "discovered_pair_count": pair_count, "live_valid_pair_count": valid_count, "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
