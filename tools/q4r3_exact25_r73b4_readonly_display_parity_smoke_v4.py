#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
CONTROL_UNIT = "zel-alimi-paper-control-api-w208.service"
TELEGRAM_UNIT = "zel-q4r3-telegram-pos-adapter-v2.service"
CONTEXTS: dict[str, dict[str, Any]] = {}
DIAGNOSTICS: dict[str, Any] = {}
LAST_VIEW: tuple[str, str] = ("", "")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load("r73b4_collector_base", HERE / "q4r3_exact25_r73b4_readonly_display_parity_smoke.py")
metrics = load("r73b4_metrics_v3", HERE / "q4r3_exact25_r73b4_metric_helpers_v3.py")
discovery = load("r73b4_binding_discovery", HERE / "q4r3_exact25_r73b4_binding_discovery.py")
collector.metrics = metrics


def system_value(unit: str, prop: str) -> str:
    return collector.command(["systemctl", "show", unit, "-p", prop, "--value"])


def environment_file_paths(text: str) -> list[Path]:
    output: list[Path] = []
    for value in re.findall(r"(/[A-Za-z0-9_./-]+)", text):
        path = Path(value)
        if path not in output:
            output.append(path)
    return output


def listening_ports(pid: str) -> list[int]:
    if not pid or pid == "0":
        return []
    result = subprocess.run(["ss", "-ltnpH"], text=True, capture_output=True, check=False, timeout=10)
    if result.returncode != 0:
        return []
    output: list[int] = []
    for line in result.stdout.splitlines():
        if f"pid={pid}," not in line:
            continue
        match = re.search(r"\s(?:\[[^]]+\]|[^\s]+):([0-9]{1,5})\s", line)
        if match:
            port = int(match.group(1))
            if 1 <= port <= 65535 and port not in output:
                output.append(port)
    return output


def unit_info(unit: str) -> dict[str, str]:
    info = {
        "unit": unit,
        "active": system_value(unit, "ActiveState"),
        "fragment": system_value(unit, "FragmentPath"),
        "exec_start": system_value(unit, "ExecStart"),
        "working_directory": system_value(unit, "WorkingDirectory"),
        "environment": system_value(unit, "Environment"),
        "environment_files": system_value(unit, "EnvironmentFiles"),
        "main_pid": system_value(unit, "MainPID"),
    }
    fragment_text = collector.read_small(Path(info["fragment"])) if info["fragment"] else ""
    source = collector.source_path(info)
    source_text = collector.read_small(source) if source else ""
    env_file_texts: list[str] = []
    for path in environment_file_paths(info["environment_files"]):
        text = collector.read_small(path)
        if text:
            env_file_texts.append(text)
    env = discovery.parse_environment(info["environment"], *env_file_texts)
    CONTEXTS[unit] = {
        "info": info,
        "fragment_text": fragment_text,
        "source": source,
        "source_text": source_text,
        "environment_file_texts": env_file_texts,
        "environment": env,
        "combined": "\n".join((info["exec_start"], info["environment"], fragment_text,
                                 source_text, *env_file_texts)),
    }
    return info


def unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def fetch_view(urls: list[str]) -> tuple[str, str, list[str]]:
    global LAST_VIEW
    context = CONTEXTS.get(CONTROL_UNIT, {})
    combined = str(context.get("combined", ""))
    info = context.get("info", {}) if isinstance(context.get("info"), dict) else {}
    ports = discovery.discover_ports(combined)
    for port in listening_ports(str(info.get("main_pid", ""))):
        if port not in ports:
            ports.append(port)
    routes = discovery.discover_routes(combined)
    attempted = list(urls)
    for port in ports:
        for route in routes:
            attempted.append(f"http://127.0.0.1:{port}{route}")
    attempted = unique(attempted)
    errors: list[str] = []
    for url in attempted:
        command = ["curl", "-fsSL", "--max-time", "12"]
        if "127.0.0.1" in url:
            command.extend(["-H", "Host: alimi.vip"])
        result = subprocess.run(command + [url], text=True, capture_output=True, check=False, timeout=15)
        if result.returncode == 0 and result.stdout:
            LAST_VIEW = (url, result.stdout[:collector.MAX_BYTES])
            DIAGNOSTICS.update({"view_attempted_urls": attempted, "view_discovered_ports": ports,
                                "view_discovered_routes": routes})
            return LAST_VIEW[0], LAST_VIEW[1], errors
        errors.append(f"{url}:curl={result.returncode}")
    DIAGNOSTICS.update({"view_attempted_urls": attempted, "view_discovered_ports": ports,
                        "view_discovered_routes": routes})
    return "", "", errors


def artifact_score(text: str) -> int:
    parsed = metrics.text_metrics(text)
    return sum(1 for key in ("closed_count", "winrate_pct", "total_r", "latest_trace_id") if key in parsed)


def choose_artifact(source_text: str, ledger: Path) -> tuple[str, str, int]:
    context = CONTEXTS.get(TELEGRAM_UNIT, {})
    info = context.get("info", {}) if isinstance(context.get("info"), dict) else {}
    combined = str(context.get("combined", source_text))
    env = context.get("environment", {}) if isinstance(context.get("environment"), dict) else {}
    working_value = str(info.get("working_directory", ""))
    working = Path(working_value) if working_value.startswith("/") else None
    source = context.get("source") if isinstance(context.get("source"), Path) else None
    paths = discovery.candidate_paths(
        combined, root=Path("/home/z/z"), working_directory=working,
        source_parent=source.parent if source else None, env=env,
    )
    candidates: list[tuple[int, int, Path, str]] = []
    explicit_ledger = discovery.explicit_ledger_binding(combined, ledger)
    for path in paths:
        if path == ledger:
            continue
        text = collector.read_small(path)
        if not text:
            continue
        score = artifact_score(text)
        if score >= 3:
            candidates.append((score, path.stat().st_mtime_ns, path, text))
    candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
    DIAGNOSTICS.update({
        "telegram_binding_mode": "FILE_ARTIFACT" if candidates else ("DIRECT_LEDGER" if explicit_ledger else "UNRESOLVED"),
        "telegram_candidate_paths": [str(path) for path in paths[:100]],
        "telegram_explicit_ledger_binding": explicit_ledger,
    })
    if candidates:
        selected = candidates[0]
        return str(selected[2]), selected[3], len(candidates)
    if explicit_ledger:
        canonical = metrics.ledger_metrics(ledger)
        return "DIRECT_LEDGER:" + str(ledger), json.dumps(canonical, sort_keys=True), 1
    view_url, view_text = LAST_VIEW
    if view_url and ("/view" in combined or "alimi.vip" in combined):
        DIAGNOSTICS["telegram_binding_mode"] = "VIEW_ENDPOINT"
        return "VIEW_ENDPOINT:" + view_url, view_text, 1
    return "", "", 0


def output_path() -> Path | None:
    try:
        return Path(sys.argv[sys.argv.index("--output") + 1])
    except (ValueError, IndexError):
        return None


collector.unit_info = unit_info
collector.fetch_view = fetch_view
collector.choose_artifact = choose_artifact


if __name__ == "__main__":
    result = int(collector.main())
    path = output_path()
    if path and path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["binding_discovery"] = DIAGNOSTICS
        payload["telegram_unit_context"] = {
            key: str(value) for key, value in CONTEXTS.get(TELEGRAM_UNIT, {}).get("info", {}).items()
        }
        payload["view_unit_context"] = {
            key: str(value) for key, value in CONTEXTS.get(CONTROL_UNIT, {}).get("info", {}).items()
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    raise SystemExit(result)
