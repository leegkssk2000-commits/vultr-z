#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

PATH_SUFFIXES = (".json", ".jsonl", ".txt", ".log")


def parse_environment(*texts: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for text in texts:
        try:
            tokens = shlex.split(text, comments=True)
        except ValueError:
            tokens = text.replace("\n", " ").split()
        for token in tokens:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                values[key] = value.strip('"\'')
    return values


def discover_ports(text: str) -> list[int]:
    patterns = (
        r"--port(?:=|\s+)(\d{2,5})",
        r"\b(?:PORT|HTTP_PORT|API_PORT|LISTEN_PORT)\s*=\s*[\"']?(\d{2,5})",
        r"\b(?:127\.0\.0\.1|0\.0\.0\.0|localhost):([0-9]{2,5})\b",
        r"\b(?:listen|bind)\s*[:=]\s*[\"']?(?:127\.0\.0\.1:|0\.0\.0\.0:|localhost:)?(\d{2,5})",
    )
    found: list[int] = []
    for pattern in patterns:
        for value in re.findall(pattern, text, flags=re.I):
            port = int(value)
            if 1 <= port <= 65535 and port not in found:
                found.append(port)
    return found


def discover_routes(text: str) -> list[str]:
    found: list[str] = []
    patterns = (
        r"@(?:app|router)\.(?:get|route)\(\s*[\"']([^\"']*view[^\"']*)[\"']",
        r"add_url_rule\(\s*[\"']([^\"']*view[^\"']*)[\"']",
    )
    for pattern in patterns:
        for value in re.findall(pattern, text, flags=re.I):
            route = value if value.startswith("/") else "/" + value
            if route not in found:
                found.append(route)
    if "/view" in text and "/view" not in found:
        found.append("/view")
    return found or ["/view"]


def expand_text(text: str, env: dict[str, str]) -> str:
    expanded = text
    for key, value in env.items():
        expanded = expanded.replace("${" + key + "}", value).replace("$" + key, value)
    return os.path.expanduser(expanded)


def candidate_paths(text: str, *, root: Path, working_directory: Path | None,
                    source_parent: Path | None, env: dict[str, str]) -> list[Path]:
    expanded = expand_text(text, env)
    raw: list[str] = []
    raw.extend(re.findall(r"(/[A-Za-z0-9_./-]+(?:\.jsonl?|\.txt|\.log))", expanded))
    raw.extend(re.findall(r"[\"']([^\"']+(?:\.jsonl?|\.txt|\.log))[\"']", expanded))
    raw.extend(value for value in env.values() if value.endswith(PATH_SUFFIXES) or value.startswith("/home/z/z/"))
    bases = [base for base in (working_directory, source_parent, root) if base]
    output: list[Path] = []
    for value in raw:
        path = Path(value)
        options = [path] if path.is_absolute() else [base / path for base in bases]
        for option in options:
            normalized = option.resolve(strict=False)
            if normalized not in output:
                output.append(normalized)
    return output


def explicit_ledger_binding(text: str, ledger: Path) -> bool:
    lowered = text.lower()
    markers = (
        str(ledger).lower(), ledger.name.lower(),
        "formal_exact5_measurement", "forward_r_ledger",
    )
    return any(marker in lowered for marker in markers)
