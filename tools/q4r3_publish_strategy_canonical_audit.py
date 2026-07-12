from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

SECTION_RE = re.compile(r"^\[(\d+)\]\s+(.+?)\s*$")
LOCATION_RE = re.compile(r"^(.*?):(\d+):(.*)$")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|private[_-]?key|access[_-]?token|refresh[_-]?token|bearer\s+|-----BEGIN [A-Z ]+PRIVATE KEY-----)"
)

SECTION_FILES = {
    "1": "watcher_status.txt",
    "2": "git_baseline.txt",
    "3": "strategy_registry_policy_files.txt",
    "4": "strategy_definition_locations.txt",
    "5": "external_knowledge_locations.txt",
    "6": "validation_evidence_locations.txt",
    "7": "temporary_legacy_candidate_files.txt",
    "9": "recent_relevant_files.txt",
}
LOCATION_ONLY = {"4", "5", "6"}
MAX_LINES_PER_SECTION = 12000


def split_sections(lines: Iterable[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current: str | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        match = SECTION_RE.match(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def sanitize_line(section: str, line: str) -> str | None:
    line = line.strip()
    if not line or SECRET_RE.search(line):
        return None
    if section in LOCATION_ONLY:
        match = LOCATION_RE.match(line)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
        return None
    return line[:2000]


def sanitize_section(section: str, lines: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for line in lines:
        sanitized = sanitize_line(section, line)
        if sanitized is None or sanitized in seen:
            continue
        seen.add(sanitized)
        output.append(sanitized)
        if len(output) >= MAX_LINES_PER_SECTION:
            break
    return output


def publish(source: Path, output_dir: Path) -> dict:
    raw = source.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    sections = split_sections(text.splitlines())
    output_dir.mkdir(parents=True, exist_ok=True)

    counts: Dict[str, int] = {}
    published_files: List[str] = []
    for section, filename in SECTION_FILES.items():
        sanitized = sanitize_section(section, sections.get(section, []))
        destination = output_dir / filename
        destination.write_text("\n".join(sanitized) + ("\n" if sanitized else ""), encoding="utf-8")
        counts[section] = len(sanitized)
        published_files.append(filename)

    manifest = {
        "schema": "q4r3_strategy_canonical_audit_sanitized_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": source.name,
        "source_size_bytes": len(raw),
        "source_line_count": len(text.splitlines()),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "published_files": published_files,
        "published_line_counts_by_section": counts,
        "raw_audit_published": False,
        "source_code_excerpts_published": False,
        "secrets_redacted": True,
        "location_only_sections": sorted(LOCATION_ONLY),
        "omitted_sections": ["8"],
        "purpose": "GitHub-readable strategy completeness audit without raw runtime rows or source excerpts",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if not args.source.is_file() or args.source.stat().st_size <= 0:
        raise SystemExit(f"SOURCE_AUDIT_MISSING:{args.source}")

    manifest = publish(args.source, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
