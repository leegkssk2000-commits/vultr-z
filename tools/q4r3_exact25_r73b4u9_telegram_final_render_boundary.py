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

SEND_METHODS = {
    "reply_text", "reply", "send_text", "send_message", "sendMessage",
    "answer", "respond", "write_message", "write_text",
}
TEXT_KEYWORDS = ("text", "message", "body", "content")
ERROR_RE = re.compile(
    r"Traceback|\bERROR\b|Exception|NameError|TypeError|AttributeError|SyntaxError",
    re.I,
)
STALE_TOKENS = (
    "closed=68", "pnl=53.613052R", "SL_TOUCH_CLOSED", "recent_rows=43",
    "last12=7.25R", "wr=37.209%", "ev=0.459302R",
    "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json",
)


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"NOT_JSON_OBJECT:{path}")
    return payload


def atomic_text(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temp = Path(raw)
    try:
        temp.write_text(text, encoding="utf-8")
        temp.chmod(mode)
        os.replace(temp, path)
        path.chmod(mode)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", 0o644)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def command_count(source: str, commands: list[str] | tuple[str, ...]) -> int:
    return sum(source.count(repr(command)) + source.count(json.dumps(command)) for command in commands)


def node_has_text(node: ast.AST, token: str) -> bool:
    return any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and token in child.value
        for child in ast.walk(node)
    )


def call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def text_argument(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg in TEXT_KEYWORDS:
            return keyword.value
    name = call_name(call)
    if name in {"reply_text", "reply", "send_text", "answer", "respond", "write_message", "write_text"}:
        return call.args[0] if call.args else None
    if name in {"send_message", "sendMessage"}:
        if len(call.args) >= 2:
            return call.args[1]
        if len(call.args) == 1:
            return call.args[0]
    return None


def pos_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    result: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node_has_text(node, "ZEL POS"):
            result.append(node)
    return result


def boundary_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[ast.expr], str]:
    outbound: list[ast.expr] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or call_name(node) not in SEND_METHODS:
            continue
        argument = text_argument(node)
        if argument is not None:
            outbound.append(argument)
    if outbound:
        return unique_nodes(outbound), "outbound_call"
    returns = [node.value for node in ast.walk(function) if isinstance(node, ast.Return) and node.value is not None]
    if returns:
        return unique_nodes(returns), "return_boundary"
    raise RuntimeError(f"POS_FINAL_BOUNDARY_NOT_FOUND:{function.name}")


def unique_nodes(nodes: list[ast.expr]) -> list[ast.expr]:
    result: list[ast.expr] = []
    seen: set[tuple[int, int, int, int]] = set()
    for node in nodes:
        key = (
            int(node.lineno), int(node.col_offset),
            int(node.end_lineno or node.lineno), int(node.end_col_offset or node.col_offset),
        )
        if key not in seen:
            seen.add(key)
            result.append(node)
    return result


def byte_span(source: str, node: ast.AST) -> tuple[int, int]:
    encoded_lines = source.encode("utf-8").splitlines(keepends=True)
    start = sum(len(line) for line in encoded_lines[: int(node.lineno) - 1]) + int(node.col_offset)
    end = sum(len(line) for line in encoded_lines[: int(node.end_lineno) - 1]) + int(node.end_col_offset)
    return start, end


def helper_source(artifact_path: str) -> str:
    return f'''
# R7.3B4U9 final outbound ZEL POS single-source boundary
import json as _r73b4u9_json
import re as _r73b4u9_re
from pathlib import Path as _R73B4U9Path
_R73B4U9_ARTIFACT = _R73B4U9Path({artifact_path!r})

def _r73b4u9_first(payload, *keys, default=None):
    for key in keys:
        if key in payload:
            return payload[key]
    return default

def _r73b4u9_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def _r73b4u9_plain(value):
    number = _r73b4u9_number(value)
    return str(int(number)) if number.is_integer() else (f"{{number:.9f}}".rstrip("0").rstrip("."))

def _r73b4u9_r(value):
    return _r73b4u9_plain(value) + "R"

def _r73b4u9_pct(value):
    return _r73b4u9_plain(value) + "%"

def _r73b4u9_last_close(value):
    if value in (None, "", "none", "None") or value == {{}}:
        return "none"
    if isinstance(value, dict):
        fields = []
        for key in ("symbol", "strategy", "side", "reason"):
            if value.get(key) not in (None, ""):
                fields.append(str(value[key]))
        pnl = _r73b4u9_first(value, "pnl_r", "net_r", "pnl")
        if pnl is not None:
            fields.append(_r73b4u9_r(pnl))
        return " ".join(fields) if fields else "none"
    return str(value)

def _r73b4u9_visible_pos(text):
    if not isinstance(text, str) or "ZEL POS" not in text:
        return text
    try:
        payload = _r73b4u9_json.loads(_R73B4U9_ARTIFACT.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {{}}
    except Exception:
        payload = {{}}
    closed = _r73b4u9_first(payload, "closed_count", "closed", default=0)
    pnl = _r73b4u9_first(payload, "pnl_r", "net_r", "pnl", default=0)
    last_close = _r73b4u9_last_close(_r73b4u9_first(payload, "last_close", "last_closed", default="none"))
    rows = _r73b4u9_first(payload, "recent_rows", "rows", default=0)
    last12 = _r73b4u9_first(payload, "last12_r", "last12", default=0)
    winrate = _r73b4u9_first(payload, "winrate_pct", "wr_pct", "wr", "winrate", "win_rate", default=0)
    ev = _r73b4u9_first(payload, "ev_r", "ev", "expectancy_r", "expectancy", default=0)
    state = _r73b4u9_first(payload, "state", default=None)
    action = _r73b4u9_first(payload, "action", default=None)
    rendered = []
    for line in text.splitlines():
        if line.startswith("last_close="):
            rendered.append("last_close=" + last_close)
            continue
        if line.startswith("recent_rows="):
            rendered.append(
                "recent_rows=" + _r73b4u9_plain(rows)
                + " last12=" + _r73b4u9_r(last12)
                + " wr=" + _r73b4u9_pct(winrate)
                + " ev=" + _r73b4u9_r(ev)
            )
            continue
        if "telegram_status_latest.json" in line and (line.startswith("/") or line.startswith("src=")):
            rendered.append("src=telegram_status_latest.json")
            continue
        line = _r73b4u9_re.sub(r"\\bclosed=[^\\s]+", "closed=" + _r73b4u9_plain(closed), line)
        line = _r73b4u9_re.sub(r"\\bpnl=[^\\s]+", "pnl=" + _r73b4u9_r(pnl), line)
        if line.startswith("state="):
            if state is not None:
                line = _r73b4u9_re.sub(r"\\bstate=[^\\s]+", "state=" + str(state), line)
            if action is not None:
                line = _r73b4u9_re.sub(r"\\baction=[^\\s]+", "action=" + str(action), line)
        rendered.append(line)
    return "\\n".join(rendered)
'''


def insertion_offset(source: str) -> int:
    tree = ast.parse(source)
    line = 0
    index = 0
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        line = int(tree.body[0].end_lineno or tree.body[0].lineno)
        index = 1
    while index < len(tree.body):
        node = tree.body[index]
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            line = int(node.end_lineno or node.lineno)
            index += 1
        else:
            break
    if line == 0 and source.startswith("#!"):
        line = 1
    return sum(len(item) for item in source.splitlines(keepends=True)[:line])


def patch_source(source: str, artifact_path: str) -> tuple[str, dict[str, Any]]:
    if "_r73b4u9_visible_pos" in source:
        raise RuntimeError("B4U9_ALREADY_PRESENT")
    tree = ast.parse(source)
    functions = pos_functions(tree)
    if len(functions) != 1:
        names = [function.name for function in functions]
        raise RuntimeError(f"POS_FUNCTION_COUNT:{len(functions)}:{names}")
    function = functions[0]
    boundaries, boundary_kind = boundary_nodes(function)
    edits: list[tuple[int, int]] = [byte_span(source, node) for node in boundaries]
    raw = source.encode("utf-8")
    for start, end in sorted(edits, reverse=True):
        segment = raw[start:end]
        raw = raw[:start] + b"_r73b4u9_visible_pos(" + segment + b")" + raw[end:]
    patched = raw.decode("utf-8")
    offset = insertion_offset(patched)
    patched = patched[:offset] + helper_source(artifact_path) + patched[offset:]
    compile(patched, "<r73b4u9-patched>", "exec")
    return patched, {
        "pos_function": function.name,
        "pos_function_count": 1,
        "boundary_kind": boundary_kind,
        "boundary_wrap_count": len(edits),
    }


def execute_helper_dryrun(patched_source: str, artifact_path: Path) -> tuple[str, int]:
    marker = "# R7.3B4U9 final outbound ZEL POS single-source boundary"
    start = patched_source.index(marker)
    function_marker = "def _r73b4u9_visible_pos(text):"
    function_start = patched_source.index(function_marker, start)
    tree = ast.parse(patched_source[function_start:])
    function_node = tree.body[0]
    assert isinstance(function_node, ast.FunctionDef)
    helper_end_relative = int(function_node.end_lineno or 1)
    helper_block = patched_source[start:].splitlines(keepends=True)
    prefix_line_count = patched_source[start:function_start].count("\n")
    helper_text = "".join(helper_block[: prefix_line_count + helper_end_relative])
    namespace: dict[str, Any] = {}
    exec(helper_text, namespace)
    stale = (
        "ZEL POS\n"
        "lane=ZEL_FOCUS mode=shadow epoch=Q4R3\n"
        "candidate=0 admitted=0 open=0 closed=68 pnl=53.613052R\n"
        "shadow_open=0 paper_open=0 live_open=0\n"
        "current={}\n"
        "last_close=BTCUSDT breakout long SL_TOUCH_CLOSED -0.75R\n"
        "state=HOLD_TELEGRAM_POS_ADAPTER_V2_ERROR action=hold\n"
        "recent_rows=43 last12=7.25R wr=37.209% ev=0.459302R\n"
        "order=blocked exec=none\n"
        + str(artifact_path)
    )
    rendered = namespace["_r73b4u9_visible_pos"](stale)
    residue = sum(token in rendered for token in STALE_TOKENS)
    expected = (
        "closed=0 pnl=0R", "last_close=none",
        "recent_rows=0 last12=0R wr=0% ev=0R",
        "src=telegram_status_latest.json",
    )
    if any(token not in rendered for token in expected):
        raise RuntimeError("DRYRUN_EXPECTED_OUTPUT_MISSING:" + rendered[-1000:])
    return rendered, residue


def first(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def is_zero(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    contract = read_json(args.contract)
    parent_path = Path(contract["parent_status"])
    b4u8_path = Path(contract["failed_b4u8_status"])
    source_path = Path(contract["telegram_source"])
    artifact_path = Path(contract["canonical_artifact"])
    shadow_path = Path(contract["shadow_snapshot"])
    ledger_path = Path(contract["formal_ledger"])
    required = (parent_path, b4u8_path, source_path, artifact_path, shadow_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        result = {"state":"HOLD","blockers":["MISSING:"+",".join(missing)],"blocker_count":1,"mutation_count":0}
        atomic_json(args.status, result); print(json.dumps(result, sort_keys=True)); return 2

    parent = read_json(parent_path)
    b4u8 = read_json(b4u8_path)
    shadow = read_json(shadow_path)
    artifact = read_json(artifact_path)
    blockers: list[str] = []
    if parent.get("state") != "PASS":
        blockers.append("B4U7_NOT_PASS")
    if b4u8.get("state") != "HOLD" or int(b4u8.get("mutation_count", -1)) != 0:
        blockers.append("B4U8_FAILURE_STATE_UNEXPECTED")
    if shadow.get("runtime_active") is not False or shadow.get("formal_ledger_bound") is not False:
        blockers.append("SHADOW_AUTHORITY_NOT_BLOCKED")
    checks = (
        first(artifact,"closed_count","closed"), first(artifact,"recent_rows","rows"),
        first(artifact,"last12_r","last12"), first(artifact,"winrate_pct","wr_pct","wr","winrate"),
        first(artifact,"ev_r","ev","expectancy_r"), first(artifact,"pnl_r","net_r","pnl"),
    )
    if any(not is_zero(value) for value in checks):
        blockers.append("CANONICAL_ARTIFACT_NOT_ZERO")
    if str(first(artifact,"last_close","last_closed",default="none")).strip().lower() not in {"none","","{}"}:
        blockers.append("CANONICAL_LAST_CLOSE_NOT_NONE")
    if blockers:
        result = {"state":"HOLD","blockers":blockers,"blocker_count":len(blockers),"mutation_count":0}
        atomic_json(args.status, result); print(json.dumps(result, sort_keys=True)); return 2

    original = source_path.read_text(encoding="utf-8", errors="strict")
    commands = tuple(str(item) for item in contract["required_commands"])
    before_commands = command_count(original, commands)
    try:
        patched, stats = patch_source(original, str(artifact_path))
        dryrun, dryrun_residue = execute_helper_dryrun(patched, artifact_path)
        if dryrun_residue != 0:
            raise RuntimeError(f"DRYRUN_VISIBLE_RESIDUE:{dryrun_residue}:{dryrun[-1000:]}")
    except Exception as exc:
        result = {
            "state":"HOLD","blockers":[str(exc)],"blocker_count":1,"mutation_count":0,
            "rollback_performed":False,"next_stage":"R7.3B4U9_DIAGNOSE",
        }
        atomic_json(args.status, result); print(json.dumps(result, sort_keys=True)); return 2

    backup_dir = Path(contract["backup_root"]) / str(time.time_ns())
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / source_path.name
    shutil.copy2(source_path, backup)
    mode = source_path.stat().st_mode & 0o777
    ledger_before = digest(ledger_path) if ledger_path.is_file() else ""
    mutations: list[str] = []
    try:
        stop = run(["systemctl", "stop", contract["telegram_unit"]])
        if stop.returncode != 0:
            raise RuntimeError("TELEGRAM_STOP_FAILED:" + stop.stderr[-300:])
        atomic_text(source_path, patched, mode or 0o755)
        mutations.append("ZEL_POS_FINAL_OUTBOUND_BOUNDARY_WRAPPED")
        compile_result = run(["python3", "-m", "py_compile", str(source_path)])
        if compile_result.returncode != 0:
            raise RuntimeError("TELEGRAM_COMPILE_FAILED:" + compile_result.stderr[-500:])
        installed = source_path.read_text(encoding="utf-8", errors="strict")
        after_commands = command_count(installed, commands)
        if after_commands != before_commands or after_commands < len(commands):
            raise RuntimeError(f"COMMAND_COUNT_CHANGED:{before_commands}->{after_commands}")
        if installed.count("_r73b4u9_visible_pos(") < stats["boundary_wrap_count"] + 1:
            raise RuntimeError("FINAL_BOUNDARY_STATIC_ASSERT_FAILED")
        started_at = int(time.time())
        start = run(["systemctl", "start", contract["telegram_unit"]])
        if start.returncode != 0:
            raise RuntimeError("TELEGRAM_START_FAILED:" + start.stderr[-300:])
        time.sleep(3)
        if run(["systemctl", "is-active", contract["telegram_unit"]]).stdout.strip() != "active":
            raise RuntimeError("TELEGRAM_UNIT_NOT_ACTIVE")
        journal = run([
            "journalctl", "-u", contract["telegram_unit"], "--since", f"@{started_at}",
            "--no-pager", "-o", "cat",
        ]).stdout
        runtime_errors = [line for line in journal.splitlines() if ERROR_RE.search(line)]
        if runtime_errors:
            raise RuntimeError("TELEGRAM_RUNTIME_ERRORS:" + " | ".join(runtime_errors[-5:]))
        if ledger_before and digest(ledger_path) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        shadow_after = read_json(shadow_path)
        if shadow_after.get("runtime_active") is not False or shadow_after.get("formal_ledger_bound") is not False:
            raise RuntimeError("SHADOW_AUTHORITY_CHANGED")
        result = {
            "schema":"q4r3_exact25_r73b4u9_telegram_final_render_boundary_status_v1",
            "state":"PASS","blockers":[],"blocker_count":0,"mutation_count":len(mutations),
            "mutations":mutations,"rollback_performed":False,"backup":str(backup),
            "telegram_pos_function":stats["pos_function"],"telegram_pos_function_count":stats["pos_function_count"],
            "telegram_boundary_kind":stats["boundary_kind"],"telegram_outbound_boundary_wrap_count":stats["boundary_wrap_count"],
            "telegram_command_count":after_commands,"telegram_compile_ok":True,"telegram_unit_active":True,
            "telegram_runtime_error_count":0,"dryrun_visible_residue_count":0,
            "canonical_closed_count":0,"canonical_recent_rows":0,"canonical_last12_r":0.0,
            "canonical_winrate_pct":0.0,"canonical_ev_r":0.0,"canonical_pnl_r":0.0,
            "canonical_last_close":"none","formal_ledger_change_count":0,"runtime_active":False,
            "next_stage":contract["next_stage"],
        }
        atomic_json(args.status, result); print(json.dumps(result, sort_keys=True)); return 0
    except Exception as exc:
        run(["systemctl", "stop", contract["telegram_unit"]])
        shutil.copy2(backup, source_path)
        source_path.chmod(mode or 0o755)
        run(["systemctl", "start", contract["telegram_unit"]])
        result = {
            "schema":"q4r3_exact25_r73b4u9_telegram_final_render_boundary_status_v1",
            "state":"HOLD","blockers":[str(exc)],"blocker_count":1,
            "mutation_count":len(mutations),"mutations":mutations,"rollback_performed":True,
            "backup":str(backup),"runtime_active":False,"next_stage":"R7.3B4U9_DIAGNOSE",
        }
        atomic_json(args.status, result); print(json.dumps(result, sort_keys=True)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
