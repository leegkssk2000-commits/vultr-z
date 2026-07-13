from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

CORE4 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SYMBOL_RE = re.compile(r"\b[A-Z0-9]{2,15}USDT\b")
ALLOWED_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".env", ".txt", ".conf"}
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "backups",
    "backup", "archive", "archives", "runtime_results", "_trash", "trash",
    "tests", "test", "tmp",
}


def normalize_symbols(values: Iterable[str]) -> Tuple[str, ...]:
    normalized: List[str] = []
    for raw in values:
        symbol = str(raw).upper().replace("/", "").replace(":", "").replace("-", "").replace("_", "")
        if symbol.endswith("USDT") and symbol not in normalized:
            normalized.append(symbol)
    return tuple(normalized)


def exact5_or_none(values: Iterable[str]) -> Tuple[str, ...] | None:
    symbols = normalize_symbols(values)
    if len(symbols) != 5:
        return None
    if not set(CORE4).issubset(set(symbols)):
        return None
    return symbols


def strings_from_value(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from strings_from_value(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings_from_value(child)


def json_candidates(value: Any, prefix: str = "$") -> Iterable[Tuple[str, Tuple[str, ...]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}"
            if isinstance(child, list):
                raw: List[str] = []
                for item in child:
                    if isinstance(item, str):
                        raw.extend(SYMBOL_RE.findall(item.upper()))
                exact = exact5_or_none(raw)
                if exact:
                    yield child_prefix, exact
            elif isinstance(child, str):
                exact = exact5_or_none(SYMBOL_RE.findall(child.upper()))
                if exact:
                    yield child_prefix, exact
            yield from json_candidates(child, child_prefix)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from json_candidates(child, f"{prefix}[{index}]")


def text_candidates(text: str) -> Iterable[Tuple[str, Tuple[str, ...]]]:
    for line_no, line in enumerate(text.splitlines(), 1):
        exact = exact5_or_none(SYMBOL_RE.findall(line.upper()))
        if exact:
            yield f"line:{line_no}", exact
    exact = exact5_or_none(SYMBOL_RE.findall(text.upper()))
    if exact:
        yield "whole_file", exact


def score_candidate(path: Path, location: str) -> int:
    text = f"{path} {location}".lower()
    score = 0
    if "ssot" in text:
        score += 140
    if "exact5" in text or "exact_5" in text:
        score += 120
    if "symbol_universe" in text or "symbol-universe" in text:
        score += 100
    if "universe" in text:
        score += 60
    if "symbols" in text or "symbol" in text:
        score += 45
    if "canonical" in text:
        score += 35
    if "config" in text:
        score += 25
    if "runtime" in text:
        score -= 15
    if "latest" in text or "generated" in text or "result" in text:
        score -= 40
    return score


def eligible_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
        return False
    if any(part.lower() in EXCLUDED_PARTS for part in path.parts):
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return 0 < size <= 2_000_000


def scan_paths(root: Path, explicit_file: Path | None = None) -> List[Dict[str, Any]]:
    paths: List[Path] = []
    if explicit_file is not None:
        paths.append(explicit_file)
    for base in (
        root / "backend" / "config",
        root / "config",
        root / "runtime" / "ssot",
        root / "runtime" / "config",
        Path("/etc/default"),
    ):
        if not base.exists():
            continue
        if base.is_file():
            paths.append(base)
            continue
        for path in base.rglob("*"):
            if eligible_file(path):
                paths.append(path)

    candidates: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, Tuple[str, ...]]] = set()
    for path in sorted(set(paths)):
        if not eligible_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found: List[Tuple[str, Tuple[str, ...]]] = []
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                found.extend(json_candidates(payload))
        found.extend(text_candidates(text))
        for location, symbols in found:
            key = (str(path), location, symbols)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "path": str(path),
                "location": location,
                "symbols": list(symbols),
                "score": score_candidate(path, location),
            })
    candidates.sort(key=lambda row: (-int(row["score"]), row["path"], row["location"]))
    return candidates


def resolve(root: Path, explicit_file: Path | None = None) -> Dict[str, Any]:
    env_symbols = os.environ.get("Q4R3_EXACT5_SYMBOLS")
    if env_symbols:
        exact = exact5_or_none(SYMBOL_RE.findall(env_symbols.upper()))
        if exact is None:
            raise RuntimeError("Q4R3_EXACT5_SYMBOLS_NOT_EXACT5_CORE4_SUPERSET")
        return {
            "status": "PASS_Q4R3_EXACT5_SYMBOL_SSOT_RESOLVER",
            "verdict": "EXACT5_RESOLVED_FROM_EXPLICIT_ENV",
            "resolved": True,
            "symbols": list(exact),
            "source_path": "env:Q4R3_EXACT5_SYMBOLS",
            "source_location": "environment",
            "candidate_count": 1,
            "candidates": [],
        }

    candidates = scan_paths(root, explicit_file)
    if not candidates:
        return {
            "status": "PASS_Q4R3_EXACT5_SYMBOL_SSOT_RESOLVER",
            "verdict": "EXACT5_SSOT_NOT_FOUND",
            "resolved": False,
            "symbols": [],
            "source_path": None,
            "source_location": None,
            "candidate_count": 0,
            "candidates": [],
        }

    top = candidates[0]
    same_symbols = [row for row in candidates if row["symbols"] == top["symbols"]]
    competing = [row for row in candidates if row["symbols"] != top["symbols"]]
    next_score = max((int(row["score"]) for row in competing), default=-10_000)
    resolved = int(top["score"]) >= 80 and (int(top["score"]) - next_score >= 15)
    return {
        "status": "PASS_Q4R3_EXACT5_SYMBOL_SSOT_RESOLVER",
        "verdict": "EXACT5_SSOT_RESOLVED_UNIQUE" if resolved else "EXACT5_SSOT_AMBIGUOUS_OR_LOW_CONFIDENCE",
        "resolved": resolved,
        "symbols": top["symbols"] if resolved else [],
        "source_path": top["path"] if resolved else None,
        "source_location": top["location"] if resolved else None,
        "top_score": top["score"],
        "next_competing_score": None if next_score == -10_000 else next_score,
        "same_symbol_evidence_count": len(same_symbols),
        "candidate_count": len(candidates),
        "candidates": candidates[:30],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--explicit-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = resolve(args.root.resolve(), args.explicit_file.resolve() if args.explicit_file else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(args.output)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
