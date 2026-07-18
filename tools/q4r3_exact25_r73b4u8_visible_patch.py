#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

TARGETS = {
    "last_close": "_r73b4u8_metric('last_close','last_closed',default='none')",
    "recent_rows": "_r73b4u8_metric('recent_rows','rows',default=0)",
    "last12": "_r73b4u8_metric('last12_r','last12',default=0)",
    "wr": "_r73b4u8_metric('winrate_pct','wr','wr_pct','winrate','win_rate',default=0)",
    "ev": "_r73b4u8_metric('ev_r','ev','expectancy_r','expectancy',default=0)",
}
ERRORS = ("Traceback", "ERROR", "Exception", "NameError", "TypeError", "AttributeError", "SyntaxError")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"NOT_OBJECT:{path}")
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def helper(status: str) -> str:
    return f'''\n# R7.3B4U8 canonical visible renderer binding\nimport json as _r73b4u8_json\nfrom pathlib import Path as _R73B4U8Path\n_R73B4U8_STATUS = _R73B4U8Path({status!r})\n\ndef _r73b4u8_metric(*keys, default=None):\n    try:\n        payload = _r73b4u8_json.loads(_R73B4U8_STATUS.read_text(encoding="utf-8"))\n        if not isinstance(payload, dict):\n            return default\n        for key in keys:\n            if key in payload:\n                value = payload[key]\n                if keys and keys[0] == "last_close" and value in (None, "", {{}}):\n                    return "none"\n                return value\n    except Exception:\n        pass\n    return default\n'''


def patch_source(source: str, status_path: str) -> tuple[str, dict]:
    if "_r73b4u8_metric" in source:
        raise RuntimeError("B4U8_ALREADY_PRESENT")
    lines = source.splitlines(keepends=True)
    hits: dict[str, list[int]] = {name: [] for name in TARGETS}
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(last_close|recent_rows|last12|wr|ev)\s*=", line)
        if match:
            hits[match.group(2)].append(index)
    bad = {name: rows for name, rows in hits.items() if len(rows) != 1}
    if bad:
        raise RuntimeError(f"TARGET_LINE_COUNTS:{bad}")
    for name, rows in hits.items():
        i = rows[0]
        indent = re.match(r"^(\s*)", lines[i]).group(1)
        newline = "\n" if lines[i].endswith("\n") else ""
        lines[i] = f"{indent}{name} = {TARGETS[name]}{newline}"

    path_hits = 0
    for i, line in enumerate(lines):
        if not any(token in line for token in ("status_path", "source_path", "telegram_status_latest.json")):
            continue
        if not any(token in line for token in ("f\"", "f'", ".format", "append(", "return ", "+=")):
            continue
        original = line
        line = re.sub(r"\{(?:str\()?\s*(?:status_path|source_path)\s*(?:\))?\}", "src=telegram_status_latest.json", line)
        line = line.replace(status_path, "telegram_status_latest.json")
        if line != original:
            lines[i] = line
            path_hits += 1
    if path_hits < 1:
        raise RuntimeError("VISIBLE_PATH_LINE_NOT_FOUND")

    patched = "".join(lines)
    future = list(re.finditer(r"^from __future__ import .*?$", patched, flags=re.M))
    insert_at = future[-1].end() + 1 if future else 0
    patched = patched[:insert_at] + helper(status_path) + patched[insert_at:]
    compile(patched, "<b4u8>", "exec")
    fallback_count = 0
    for name in TARGETS:
        line = next(row for row in patched.splitlines() if re.match(rf"^\s*{name}\s*=", row))
        if "_r73b4u8_metric(" not in line:
            fallback_count += 1
    return patched, {"assignment_patch_count": 5, "path_patch_count": path_hits, "fallback_count": fallback_count}


def zero(value) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def first(data: dict, *keys):
    for key in keys:
        if key in data:
            return data[key]
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--contract", type=Path, required=True)
    p.add_argument("--status", type=Path, required=True)
    a = p.parse_args()
    c = load(a.contract)
    parent = Path(c["parent_status"])
    source = Path(c["telegram_source"])
    artifact = Path(c["canonical_artifact"])
    shadow = Path(c["shadow_snapshot"])
    ledger = Path(c["formal_ledger"])
    unit = c["telegram_unit"]
    missing = [str(x) for x in (parent, source, artifact, shadow) if not x.is_file()]
    if missing:
        out = {"state":"HOLD","blockers":["MISSING:"+",".join(missing)],"blocker_count":1,"mutation_count":0}
        save(a.status, out); print(json.dumps(out, sort_keys=True)); return 2
    parent_data, shadow_data = load(parent), load(shadow)
    if parent_data.get("state") != "PASS" or shadow_data.get("runtime_active") is not False or shadow_data.get("formal_ledger_bound") is not False:
        out = {"state":"HOLD","blockers":["PARENT_OR_AUTHORITY_INVALID"],"blocker_count":1,"mutation_count":0}
        save(a.status, out); print(json.dumps(out, sort_keys=True)); return 2
    text = source.read_text(encoding="utf-8")
    try:
        patched, stats = patch_source(text, str(artifact))
    except Exception as e:
        out = {"state":"HOLD","blockers":[str(e)],"blocker_count":1,"mutation_count":0,"next_stage":"R7.3B4U8_DIAGNOSE"}
        save(a.status, out); print(json.dumps(out, sort_keys=True)); return 2

    backup_dir = Path(c["backup_root"]) / str(time.time_ns())
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / source.name
    shutil.copy2(source, backup)
    mode = source.stat().st_mode & 0o777
    before = digest(source)
    ledger_before = digest(ledger) if ledger.is_file() else ""
    mutations = []
    try:
        if run(["systemctl","stop",unit]).returncode:
            raise RuntimeError("STOP_FAILED")
        fd, raw = tempfile.mkstemp(prefix=f".{source.name}.", dir=source.parent)
        os.close(fd)
        tmp = Path(raw)
        tmp.write_text(patched, encoding="utf-8"); tmp.chmod(mode); os.replace(tmp, source)
        mutations = ["VISIBLE_METRICS_SINGLE_SOURCE", "VISIBLE_PATH_LABEL_SANITIZED"]
        check = run(["python3","-m","py_compile",str(source)])
        if check.returncode:
            raise RuntimeError("COMPILE_FAILED:"+check.stderr[-300:])
        started = int(time.time())
        if run(["systemctl","start",unit]).returncode:
            raise RuntimeError("START_FAILED")
        time.sleep(3)
        if run(["systemctl","is-active",unit]).stdout.strip() != "active":
            raise RuntimeError("UNIT_NOT_ACTIVE")
        journal = run(["journalctl","-u",unit,"--since",f"@{started}","--no-pager","-o","cat"]).stdout
        errors = [line for line in journal.splitlines() if any(token in line for token in ERRORS)]
        if errors:
            raise RuntimeError("RUNTIME_ERRORS:"+" | ".join(errors[-5:]))
        data = load(artifact)
        checks = [
            first(data,"closed_count","closed"), first(data,"recent_rows","rows"),
            first(data,"last12_r","last12"), first(data,"winrate_pct","wr","winrate"),
            first(data,"ev_r","ev","expectancy_r"), first(data,"pnl_r","net_r","pnl")]
        if any(not zero(value) for value in checks):
            raise RuntimeError(f"ARTIFACT_NOT_ZERO:{checks}")
        if str(first(data,"last_close","last_closed")).strip().lower() not in {"none","","{}"}:
            raise RuntimeError("LAST_CLOSE_NOT_NONE")
        if ledger_before and digest(ledger) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        if load(shadow).get("runtime_active") is not False:
            raise RuntimeError("RUNTIME_CHANGED")
        out = {
            "schema":"q4r3_exact25_r73b4u8_visible_patch_status_v1","state":"PASS","blockers":[],"blocker_count":0,
            "mutation_count":len(mutations),"mutations":mutations,"rollback_performed":False,
            "telegram_source_change_count":int(digest(source)!=before),"telegram_assignment_patch_count":stats["assignment_patch_count"],
            "telegram_path_patch_count":stats["path_patch_count"],"telegram_local_fallback_count":stats["fallback_count"],
            "telegram_compile_ok":True,"telegram_unit_active":True,"telegram_runtime_error_count":0,
            "canonical_closed_count":0,"canonical_recent_rows":0,"canonical_last12_r":0.0,"canonical_winrate_pct":0.0,
            "canonical_ev_r":0.0,"canonical_pnl_r":0.0,"canonical_last_close":"none",
            "formal_ledger_change_count":0,"runtime_active":False,"next_stage":c["next_stage"],"backup":str(backup)}
        save(a.status,out); print(json.dumps(out,sort_keys=True)); return 0
    except Exception as e:
        run(["systemctl","stop",unit]); shutil.copy2(backup,source); source.chmod(mode); run(["systemctl","start",unit])
        out = {"state":"HOLD","blockers":[str(e)],"blocker_count":1,"mutation_count":len(mutations),"mutations":mutations,"rollback_performed":True,"backup":str(backup),"runtime_active":False,"next_stage":"R7.3B4U8_DIAGNOSE"}
        save(a.status,out); print(json.dumps(out,sort_keys=True)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
