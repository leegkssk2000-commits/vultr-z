#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

KEY_MAP = {
    "closed": "closed_count",
    "closed_count": "closed_count",
    "recent_rows": "recent_rows",
    "rows": "recent_rows",
    "last12": "last12_r",
    "last12_r": "last12_r",
    "wr": "winrate_pct",
    "wr_pct": "winrate_pct",
    "winrate": "winrate_pct",
    "winrate_pct": "winrate_pct",
    "win_rate": "winrate_pct",
    "ev": "ev_r",
    "ev_r": "ev_r",
    "expectancy": "ev_r",
    "expectancy_r": "ev_r",
    "pnl": "pnl_r",
    "pnl_r": "pnl_r",
    "net_r": "pnl_r",
    "last_close": "last_close",
    "last_closed": "last_close",
}
DISPLAY_PATH_NAMES = {
    "status_path", "source_path", "telegram_status_path", "telegram_source_path",
    "display_source", "source_label", "status_file", "source_file"
}
CANONICAL_ALIASES = {
    "closed_count": ("closed_count", "closed"),
    "recent_rows": ("recent_rows", "rows"),
    "last12_r": ("last12_r", "last12"),
    "winrate_pct": ("winrate_pct", "wr", "winrate", "win_rate"),
    "ev_r": ("ev_r", "ev", "expectancy_r"),
    "pnl_r": ("pnl_r", "net_r", "pnl"),
    "last_close": ("last_close", "last_closed"),
}
WRITER_LABEL = "configured=7 · active=0 · VV/TR/LS/MO/VB/MS/SR"


def run(command: list[str], check: bool = False, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check, timeout=timeout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode)
        os.replace(tmp, path)
        path.chmod(mode)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", 0o644)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return payload


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    probe = f"{url}{'&' if '?' in url else '?'}r73b4u3u4={time.time_ns()}"
    cmd = ["curl", "-sS", "-L", "--max-time", "15", "-H", "Cache-Control: no-cache", "-w", "\n%{http_code}"]
    if url.startswith("https://alimi.z-os.vip/"):
        cmd.extend(["--resolve", "alimi.z-os.vip:443:127.0.0.1"])
    cmd.append(probe)
    result = run(cmd, timeout=20)
    body, _, raw_code = result.stdout.rpartition("\n")
    try:
        code = int(raw_code or 0)
    except ValueError:
        code = 0
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    return code, payload if isinstance(payload, dict) else {}


def target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def key_from_slice(node: ast.Subscript) -> str | None:
    value = node.slice
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def helper_call(key: str, default: ast.expr | None = None) -> ast.Call:
    args: list[ast.expr] = [ast.Constant(KEY_MAP[key])]
    if default is not None:
        args.append(default)
    return ast.Call(func=ast.Name(id="_r73b4u3_value", ctx=ast.Load()), args=args, keywords=[])


class CanonicalizeTelegram(ast.NodeTransformer):
    def __init__(self, canonical_path: str, secondary_paths: set[str], display_label: str) -> None:
        self.canonical_path = canonical_path
        self.secondary_paths = secondary_paths
        self.display_label = display_label
        self.metric_rewrite_count = 0
        self.path_rewrite_count = 0
        self.display_path_rewrite_count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if node.name.startswith("_r73b4u3_"):
            return node
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        if node.name.startswith("_r73b4u3_"):
            return node
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value in KEY_MAP:
                default = node.args[1] if len(node.args) > 1 else None
                self.metric_rewrite_count += 1
                return ast.copy_location(helper_call(first.value, default), node)
        return node

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        node = self.generic_visit(node)
        if isinstance(node, ast.Subscript):
            key = key_from_slice(node)
            if key in KEY_MAP:
                self.metric_rewrite_count += 1
                return ast.copy_location(helper_call(key), node)
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        node = self.generic_visit(node)
        names = [target_name(target) for target in node.targets]
        metric = next((name for name in names if name in KEY_MAP), None)
        if metric:
            self.metric_rewrite_count += 1
            node.value = helper_call(metric)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        node = self.generic_visit(node)
        name = target_name(node.target)
        if name in KEY_MAP:
            self.metric_rewrite_count += 1
            node.value = helper_call(name)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, str):
            value = node.value
            if value in self.secondary_paths:
                self.path_rewrite_count += 1
                return ast.copy_location(ast.Constant(self.canonical_path), node)
            if "q4r3_shadow_closed_ledger_latest.json" in value:
                self.path_rewrite_count += 1
                return ast.copy_location(ast.Constant(value.replace("q4r3_shadow_closed_ledger_latest.json", self.display_label)), node)
        return node

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        node = self.generic_visit(node)
        new_values: list[ast.expr] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                name = target_name(value.value)
                if name in DISPLAY_PATH_NAMES:
                    self.display_path_rewrite_count += 1
                    new_values.append(ast.Constant(self.display_label))
                    continue
            new_values.append(value)
        node.values = new_values
        return node


def inject_helpers(tree: ast.Module, canonical_path: str, display_label: str) -> ast.Module:
    alias_json = json.dumps(CANONICAL_ALIASES, sort_keys=True)
    helper_source = f'''
import json as _r73b4u3_json
from pathlib import Path as _R73B4U3Path
_R73B4U3_CANONICAL_PATH = _R73B4U3Path({canonical_path!r})
_R73B4U3_DISPLAY_LABEL = {display_label!r}
_R73B4U3_ALIASES = {alias_json}
_R73B4U3_CACHE = {{"mtime": None, "payload": {{}}}}

def _r73b4u3_payload():
    try:
        stamp = _R73B4U3_CANONICAL_PATH.stat().st_mtime_ns
        if _R73B4U3_CACHE["mtime"] != stamp:
            payload = _r73b4u3_json.loads(_R73B4U3_CANONICAL_PATH.read_text(encoding="utf-8"))
            _R73B4U3_CACHE["payload"] = payload if isinstance(payload, dict) else {{}}
            _R73B4U3_CACHE["mtime"] = stamp
    except Exception:
        _R73B4U3_CACHE["payload"] = {{}}
    return _R73B4U3_CACHE["payload"]

def _r73b4u3_value(key, default=None):
    payload = _r73b4u3_payload()
    for alias in _R73B4U3_ALIASES.get(key, (key,)):
        if alias in payload:
            value = payload[alias]
            if key == "last_close" and isinstance(value, dict):
                return "none" if not value else value
            return value
    if key == "last_close":
        return "none"
    return default
'''
    helper_nodes = ast.parse(helper_source).body
    insert_at = 0
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        insert_at = 1
    while insert_at < len(tree.body) and isinstance(tree.body[insert_at], ast.ImportFrom) and tree.body[insert_at].module == "__future__":
        insert_at += 1
    tree.body[insert_at:insert_at] = helper_nodes
    return tree


def direct_metric_access_count(source: str) -> int:
    tree = ast.parse(source)
    count = 0
    helper_depth = 0

    class Scan(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            nonlocal helper_depth
            if node.name.startswith("_r73b4u3_"):
                helper_depth += 1
                self.generic_visit(node)
                helper_depth -= 1
            else:
                self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            nonlocal count
            if not helper_depth and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value in KEY_MAP:
                    count += 1
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> None:
            nonlocal count
            if not helper_depth and key_from_slice(node) in KEY_MAP:
                count += 1
            self.generic_visit(node)

    Scan().visit(tree)
    return count


def patch_telegram(source: str, canonical_path: str, secondary_paths: set[str], display_label: str) -> tuple[str, dict[str, int]]:
    tree = ast.parse(source)
    transformer = CanonicalizeTelegram(canonical_path, secondary_paths, display_label)
    tree = transformer.visit(tree)
    assert isinstance(tree, ast.Module)
    tree = inject_helpers(tree, canonical_path, display_label)
    ast.fix_missing_locations(tree)
    rendered = ast.unparse(tree) + "\n"
    if source.startswith("#!"):
        rendered = source.splitlines()[0] + "\n" + rendered
    compile(rendered, "<telegram-patched>", "exec")
    return rendered, {
        "metric_rewrite_count": transformer.metric_rewrite_count,
        "path_rewrite_count": transformer.path_rewrite_count,
        "display_path_rewrite_count": transformer.display_path_rewrite_count,
    }


def patch_view(source: str, display_label: str) -> tuple[str, dict[str, int]]:
    patched = source
    legacy_source_count = patched.count("q4r3_shadow_closed_ledger_latest.json")
    patched = patched.replace("q4r3_shadow_closed_ledger_latest.json", display_label)
    team_lane_count = patched.count("A/B/G/D team lane")
    patched = patched.replace("A/B/G/D team lane", "")

    writer_replacements = 0
    patterns = (
        r"writer_count\s*=\s*\$\{[^}]+\}\s*·\s*\$\{[^}]+\}(?:\s+\$\{[^}]+\}){0,3}",
        r"writer_count\s*=\s*\$\{[^}]+\}(?:\s*·\s*[^<`\"']+)?",
        r"writer_count\s*=\s*0\s*·\s*[—\-\s]+",
    )
    for pattern in patterns:
        patched, count = re.subn(pattern, WRITER_LABEL, patched, count=1, flags=re.I)
        writer_replacements += count
        if count:
            break
    if writer_replacements == 0 and "writer_count=" in patched:
        patched = patched.replace("writer_count=", "configured=7 · active=", 1)
        writer_replacements = 1
    return patched, {
        "legacy_source_replacement_count": legacy_source_count,
        "team_lane_replacement_count": team_lane_count,
        "writer_card_replacement_count": writer_replacements,
    }


def metric(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    contract = read_json(args.contract)
    parent_path = Path(contract["parent_status"])
    canonical_path = Path(contract["canonical_telegram_artifact"])
    view_path = Path(contract["view_index"])
    ledger_path = Path(contract["formal_ledger"])
    snapshot_path = Path(contract["shadow_snapshot"])
    backup_root = Path(contract["backup_root"])
    display_label = str(contract["canonical_display_label"])
    blockers: list[str] = []

    required = [parent_path, canonical_path, view_path, snapshot_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        payload = {"state": "HOLD", "blockers": ["REQUIRED_INPUT_MISSING:" + ",".join(missing)], "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    parent = read_json(parent_path)
    canonical = read_json(canonical_path)
    snapshot = read_json(snapshot_path)
    renderer = parent.get("telegram_renderer", {}) if isinstance(parent.get("telegram_renderer"), dict) else {}
    source_path = Path(str(renderer.get("source_path") or contract["telegram_source_fallback"]))
    secondary_paths = {str(item) for item in renderer.get("secondary_json_paths", []) if isinstance(item, str)}
    expected_registry = {str(k): str(v) for k, v in contract["expected_writer_registry"].items()}
    actual_registry = {
        str(row.get("writer_id")): str(row.get("strategy"))
        for row in canonical.get("writers", []) if isinstance(row, dict)
    }

    if parent.get("state") != "PASS" or int(parent.get("mutation_count", -1)) != 0:
        blockers.append("B4U2_PARENT_INVALID")
    if int(metric(canonical, "closed_count", "closed", default=-1)) != 0:
        blockers.append("CANONICAL_CLOSED_NOT_ZERO")
    if int(metric(canonical, "recent_rows", "rows", default=-1)) != 0:
        blockers.append("CANONICAL_RECENT_ROWS_NOT_ZERO")
    if float(metric(canonical, "pnl_r", "net_r", default=-1.0)) != 0.0:
        blockers.append("CANONICAL_PNL_NOT_ZERO")
    if int(canonical.get("writer_count", -1)) != 7 or int(canonical.get("active_writer_count", -1)) != 0:
        blockers.append("CANONICAL_WRITER_COUNTS_INVALID")
    if actual_registry != expected_registry:
        blockers.append("CANONICAL_WRITER_REGISTRY_INVALID")
    if snapshot.get("runtime_active") is not False or snapshot.get("formal_ledger_bound") is not False:
        blockers.append("SNAPSHOT_AUTHORITY_INVALID")
    if not source_path.is_file():
        blockers.append("TELEGRAM_SOURCE_MISSING")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = str(time.time_ns())
    source_backup = backup_root / f"telegram.{stamp}.py"
    view_backup = backup_root / f"view.{stamp}.html"
    shutil.copy2(source_path, source_backup)
    shutil.copy2(view_path, view_backup)
    source_mode = source_path.stat().st_mode & 0o777
    view_mode = view_path.stat().st_mode & 0o777
    ledger_before = sha256(ledger_path) if ledger_path.is_file() else ""
    mutations: list[str] = []
    rollback_performed = False

    try:
        patched_source, telegram_stats = patch_telegram(
            source_path.read_text(encoding="utf-8", errors="strict"),
            str(canonical_path),
            secondary_paths,
            display_label,
        )
        if telegram_stats["metric_rewrite_count"] < 1:
            raise RuntimeError("NO_TELEGRAM_METRIC_ACCESS_REWRITTEN")
        if secondary_paths and telegram_stats["path_rewrite_count"] < 1:
            raise RuntimeError("NO_SECONDARY_SOURCE_PATH_REWRITTEN")
        atomic_text(source_path, patched_source, source_mode or 0o755)
        mutations.append("TELEGRAM_FORMATTER_CANONICALIZED")

        patched_view, view_stats = patch_view(view_path.read_text(encoding="utf-8", errors="strict"), display_label)
        if view_stats["legacy_source_replacement_count"] < 1:
            raise RuntimeError("VIEW_LEGACY_LEDGER_MARKER_NOT_FOUND")
        if view_stats["writer_card_replacement_count"] < 1:
            raise RuntimeError("VIEW_WRITER_CARD_NOT_REWRITTEN")
        atomic_text(view_path, patched_view, view_mode or 0o644)
        mutations.extend(["VIEW_LEGACY_LEDGER_LABEL_REMOVED", "VIEW_WRITERS7_LABEL_CORRECTED"])
        if view_stats["team_lane_replacement_count"]:
            mutations.append("VIEW_STATIC_TEAM_LANE_REMOVED")

        compile_result = run(["python3", "-m", "py_compile", str(source_path)])
        if compile_result.returncode != 0:
            raise RuntimeError("TELEGRAM_SOURCE_COMPILE_FAILED:" + compile_result.stderr[-300:])
        if direct_metric_access_count(source_path.read_text(encoding="utf-8")) != 0:
            raise RuntimeError("DIRECT_TELEGRAM_METRIC_FALLBACK_REMAINS")
        active_source = source_path.read_text(encoding="utf-8")
        secondary_remaining = [path for path in secondary_paths if path in active_source]
        if secondary_remaining:
            raise RuntimeError("SECONDARY_JSON_PATH_REMAINS:" + ",".join(secondary_remaining))
        if "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json" in active_source:
            # The canonical absolute path is allowed for reads but may not be rendered.
            tree = ast.parse(active_source)
            rendered_path_count = 0
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr):
                    for value in node.values:
                        if isinstance(value, ast.Constant) and isinstance(value.value, str) and "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json" in value.value:
                            rendered_path_count += 1
            if rendered_path_count:
                raise RuntimeError("CANONICAL_ABSOLUTE_PATH_STILL_RENDERED")

        restart = run(["systemctl", "restart", contract["telegram_unit"]])
        if restart.returncode != 0:
            raise RuntimeError("TELEGRAM_UNIT_RESTART_FAILED:" + restart.stderr[-300:])
        time.sleep(2)
        active = run(["systemctl", "is-active", contract["telegram_unit"]]).stdout.strip()
        if active != "active":
            raise RuntimeError("TELEGRAM_UNIT_NOT_ACTIVE:" + active)

        view_live = view_path.read_text(encoding="utf-8")
        legacy_remaining = sum(view_live.count(marker) for marker in contract["legacy_view_markers"])
        if legacy_remaining:
            raise RuntimeError(f"VIEW_LEGACY_MARKER_REMAINS:{legacy_remaining}")
        if "configured=7" not in view_live or "active=0" not in view_live:
            raise RuntimeError("VIEW_WRITER_CARD_LABEL_NOT_CONFIRMED")

        http_status, endpoint = fetch_json(contract["alimi_endpoint"])
        if http_status != 200:
            raise RuntimeError(f"ALIMI_HTTP_{http_status}")
        if int(metric(endpoint, "closed_count", "closed", default=-1)) != 0:
            raise RuntimeError("ALIMI_CLOSED_NOT_ZERO")
        if float(metric(endpoint, "pnl_r", "net_r", default=-1.0)) != 0.0:
            raise RuntimeError("ALIMI_PNL_NOT_ZERO")
        if ledger_before and sha256(ledger_path) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        snapshot_after = read_json(snapshot_path)
        if snapshot_after.get("runtime_active") is not False or snapshot_after.get("formal_ledger_bound") is not False:
            raise RuntimeError("RUNTIME_OR_LEDGER_AUTHORITY_CHANGED")

        payload = {
            "schema": "q4r3_exact25_r73b4u3u4_rendered_residue_eradication_status_v1",
            "state": "PASS",
            "blockers": [],
            "blocker_count": 0,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": False,
            "telegram_source": str(source_path),
            "telegram_metric_rewrite_count": telegram_stats["metric_rewrite_count"],
            "telegram_secondary_json_path_rewrite_count": telegram_stats["path_rewrite_count"],
            "telegram_display_path_rewrite_count": telegram_stats["display_path_rewrite_count"],
            "telegram_secondary_json_path_count": 0,
            "telegram_direct_metric_fallback_count": 0,
            "telegram_compile_ok": True,
            "telegram_unit_active": True,
            "view_legacy_source_replacement_count": view_stats["legacy_source_replacement_count"],
            "view_team_lane_replacement_count": view_stats["team_lane_replacement_count"],
            "view_writer_card_replacement_count": view_stats["writer_card_replacement_count"],
            "view_legacy_marker_count": 0,
            "view_writer_card_configured_label": True,
            "alimi_http_status": http_status,
            "alimi_closed_count": int(metric(endpoint, "closed_count", "closed", default=0)),
            "alimi_pnl_r": float(metric(endpoint, "pnl_r", "net_r", default=0.0)),
            "formal_ledger_change_count": 0,
            "runtime_active": False,
            "next_stage": contract["next_stage"],
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        rollback_performed = True
        shutil.copy2(source_backup, source_path)
        shutil.copy2(view_backup, view_path)
        source_path.chmod(source_mode or 0o755)
        view_path.chmod(view_mode or 0o644)
        run(["systemctl", "restart", contract["telegram_unit"]])
        payload = {
            "schema": "q4r3_exact25_r73b4u3u4_rendered_residue_eradication_status_v1",
            "state": "HOLD",
            "blockers": [str(exc)],
            "blocker_count": 1,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": rollback_performed,
            "runtime_active": False,
            "next_stage": "R7.3B4U3U4_DIAGNOSE",
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
