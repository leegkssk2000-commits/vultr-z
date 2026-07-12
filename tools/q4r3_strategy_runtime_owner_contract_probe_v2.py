from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

BASE_PATH = Path(__file__).with_name('q4r3_strategy_runtime_owner_contract_probe.py')


def load_base():
    spec = importlib.util.spec_from_file_location('q4r3_strategy_runtime_owner_contract_probe_base', BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'BASE_PROBE_LOAD_FAILED:{BASE_PATH}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_base()


def repo_paths(value: Any) -> list[str]:
    text = str(value or '')
    found = []
    for match in re.findall(r'/home/z/z/[^\s;\}\]\)"\']+', text):
        cleaned = match.rstrip(',:')
        if cleaned not in found:
            found.append(cleaned)
    return found[:20]


def service_names(value: Any) -> list[str]:
    text = str(value or '')
    return sorted(set(re.findall(r'[A-Za-z0-9_.@-]+\.service', text)))[:20]


def sanitize(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if not isinstance(value, dict):
        return value

    output = {}
    collected_paths: list[str] = []
    collected_units: list[str] = []
    for key, item in value.items():
        if key in {'cmdline', 'exec_start', 'cwd'}:
            collected_paths.extend(repo_paths(item))
            continue
        if key == 'cgroup':
            collected_units.extend(service_names(item))
            continue
        if key == 'stack':
            continue
        output[key] = sanitize(item)
    if collected_paths:
        output['repo_paths'] = sorted(set(collected_paths))[:20]
    if collected_units:
        output['service_units'] = sorted(set(collected_units))[:20]
    return output


def atomic_json_sanitized(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(sanitize(payload), ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def main() -> None:
    BASE.atomic_json = atomic_json_sanitized
    BASE.main()


if __name__ == '__main__':
    main()
