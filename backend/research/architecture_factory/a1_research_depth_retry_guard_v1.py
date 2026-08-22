#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
MAP = ROOT / "backend/research/architecture_factory/a1_external_research_exact25_map_v1.json"
A5 = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
SUPPLEMENT = ROOT / "backend/research/contracts/a1_high_value_evidence_supplement_v1.json"
BLACKLIST = ROOT / "backend/research/contracts/a1_research_mistake_blacklist_v1.json"
ROADMAP = ROOT / "backend/research/contracts/a1_a5_evidence_backed_roadmap_v1.json"
BASELINE = ROOT / "backend/research/contracts/a1_a5_original_baseline_integrity_v1.json"
DEFAULT_OUT = ROOT / "backend/research/architecture_factory/a1_research_depth_retry_guard_latest.json"

HIGH_TIERS = {
    "peer_reviewed", "primary_preprint", "working_paper", "peer_reviewed_validation",
    "official_exchange_documentation", "discovered_primary_abstract",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def source_family(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("source_family") or "").strip()
    if explicit:
        return explicit
    title = str(row.get("title") or "").lower()
    ident = str(row.get("identifier") or "").lower()
    if ident.startswith("bingx:"):
        return "BingX Official"
    if "ssrn:" in ident:
        return "SSRN"
    if "econStor".lower() in ident:
        return "EconStor"
    if "youtube:" in ident:
        return "YouTube"
    # Existing frozen map entries do not store venue; keep identifier families distinct
    # only for support-diversity diagnostics, never as an alpha-quality score.
    if ident.startswith("doi:"):
        doi = ident[4:]
        return "DOI:" + "/".join(doi.split("/")[:1])
    if "bitcoin" in title or "crypto" in title:
        return "FrozenCryptoResearchMap"
    return "FrozenResearchMap"


def merge_sources(mapping: Mapping[str, Any], a5: Mapping[str, Any], supplement: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    for sid, raw in (mapping.get("sources") or {}).items():
        if isinstance(raw, Mapping):
            rows.append({"id": str(sid), **dict(raw), "origin": "exact25_map"})
    for raw in a5.get("external_evidence") or []:
        if isinstance(raw, Mapping) and raw.get("id"):
            rows.append({**dict(raw), "origin": "a5_no_idle"})
    for raw in supplement.get("sources") or []:
        if isinstance(raw, Mapping) and raw.get("id"):
            rows.append({**dict(raw), "origin": "high_value_supplement"})

    by_id: dict[str, dict[str, Any]] = {}
    seen_identifier: dict[str, str] = {}
    duplicate_identifiers: list[str] = []
    for row in rows:
        sid = str(row.get("id") or "")
        ident = str(row.get("identifier") or sid).strip().lower()
        if not sid:
            continue
        if ident in seen_identifier:
            duplicate_identifiers.append(f"{sid}->{seen_identifier[ident]}:{ident}")
            # Preserve both IDs for roadmap references, but do not count the duplicate document twice.
            row["duplicate_of"] = seen_identifier[ident]
        else:
            seen_identifier[ident] = sid
        by_id[sid] = row
    return by_id, duplicate_identifiers


def unique_documents(by_id: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    out: list[Mapping[str, Any]] = []
    for row in by_id.values():
        ident = str(row.get("identifier") or row.get("id") or "").strip().lower()
        if ident in seen:
            continue
        seen.add(ident)
        out.append(row)
    return out


def contains_any(row: Mapping[str, Any], terms: set[str]) -> bool:
    text = " ".join([
        str(row.get("title") or ""), str(row.get("claim") or ""), str(row.get("use") or ""),
        str(row.get("mechanism") or ""), " ".join(str(x) for x in (row.get("roles") or [])),
    ]).lower()
    return any(term in text for term in terms)


def audit() -> dict[str, Any]:
    mapping, a5, supplement, blacklist, roadmap, baseline = map(read, [MAP, A5, SUPPLEMENT, BLACKLIST, ROADMAP, BASELINE])
    by_id, duplicate_identifiers = merge_sources(mapping, a5, supplement)
    docs = unique_documents(by_id)
    depth = roadmap.get("evidence_depth_policy") or {}
    defects: list[str] = []

    total = len(docs)
    high = sum(1 for x in docs if str(x.get("tier") or "") in HIGH_TIERS)
    validation = sum(1 for x in docs if contains_any(x, {"validation", "backtest overfitting", "selection bias", "multiple testing", "anti_cherrypick"}))
    crypto = sum(1 for x in docs if contains_any(x, {"crypto", "bitcoin", "ethereum", "perpetual"}))
    derivatives = sum(1 for x in docs if contains_any(x, {"crypto_derivatives", "perpetual futures", "bitcoin futures", "market microstructure", "price discovery"}))
    official = sum(1 for x in docs if str(x.get("tier") or "") == "official_exchange_documentation")
    families = sorted({source_family(x) for x in docs if source_family(x)})

    checks = {
        "unique_documents": (total, int(depth.get("minimum_unique_documents") or 0)),
        "high_tier_documents": (high, int(depth.get("minimum_high_tier_documents") or 0)),
        "validation_documents": (validation, int(depth.get("minimum_validation_documents") or 0)),
        "crypto_specific_documents": (crypto, int(depth.get("minimum_crypto_specific_documents") or 0)),
        "crypto_derivatives_or_microstructure_documents": (derivatives, int(depth.get("minimum_crypto_derivatives_or_microstructure_documents") or 0)),
        "official_exchange_documents": (official, int(depth.get("minimum_official_exchange_documents") or 0)),
        "source_families": (len(families), int(depth.get("minimum_source_families") or 0)),
    }
    for name, (observed, required) in checks.items():
        if observed < required:
            defects.append(f"EVIDENCE_DEPTH_FAIL:{name}:observed={observed}:required={required}")

    # Curated supplement rows must carry a mechanism and a limitation; raw source count alone is not enough.
    for row in supplement.get("sources") or []:
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("id") or "<missing>")
        if not str(row.get("mechanism") or "").strip():
            defects.append(f"SUPPLEMENT_MECHANISM_MISSING:{sid}")
        if not str(row.get("limitations") or "").strip():
            defects.append(f"SUPPLEMENT_LIMITATION_MISSING:{sid}")

    # Every next A5 axis needs multiple independent evidence documents and families.
    min_support = int(depth.get("minimum_supporting_documents_per_next_axis") or 3)
    min_support_families = int(depth.get("minimum_source_families_per_next_axis") or 2)
    axis_rows: list[dict[str, Any]] = []
    for row in roadmap.get("a5_next_axes") or []:
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("strategy_id") or "")
        axis = str(row.get("next_axis") or "")
        ids = [str(x) for x in (row.get("evidence_ids") or [])]
        missing = [x for x in ids if x not in by_id]
        resolved = [by_id[x] for x in ids if x in by_id]
        support_families = sorted({source_family(x) for x in resolved})
        if missing:
            defects.append(f"AXIS_EVIDENCE_ID_MISSING:{sid}:{axis}:{','.join(missing)}")
        if len(resolved) < min_support:
            defects.append(f"AXIS_SUPPORT_TOO_THIN:{sid}:{axis}:observed={len(resolved)}:required={min_support}")
        if len(support_families) < min_support_families:
            defects.append(f"AXIS_SOURCE_FAMILY_TOO_THIN:{sid}:{axis}:observed={len(support_families)}:required={min_support_families}")
        axis_rows.append({"strategy_id": sid, "axis": axis, "evidence_ids": ids, "source_families": support_families})

    required_codes = {
        "DERIVED_LINEAGE_AS_CANONICAL_BASELINE", "TECHNICAL_FAILURE_RELABELED_ECONOMIC_FAIL",
        "GENERIC_SCOUT_CERTIFIES_ALPHA", "SCREENING_METRIC_AS_SURVIVOR_METRIC", "NOOP_AXIS_REPORTED_PASS",
        "POST_OUTCOME_RESCUE", "SOURCE_GRANULARITY_MISMATCH", "MICROSTRUCTURE_PAYER_INVERSION",
        "UNIVERSAL_8H_FUNDING_ASSUMPTION", "TERMINAL_RETRY_WITH_SAME_IDENTITY", "A3_BYPASS",
    }
    got_codes = {str(x.get("code")) for x in (blacklist.get("global_block_rules") or []) if isinstance(x, Mapping)}
    missing_codes = sorted(required_codes - got_codes)
    if missing_codes:
        defects.append("MISTAKE_GUARD_CODES_MISSING:" + ",".join(missing_codes))

    attempts = [x for x in (blacklist.get("known_attempts") or []) if isinstance(x, Mapping)]
    break_noop = next((x for x in attempts if x.get("strategy_id") == "break_and_continue" and x.get("terminal_class") == "NO_EFFECT"), None)
    if not break_noop or break_noop.get("retry_same_identity") is not False:
        defects.append("BREAK_RELATIVE_VOLUME_NO_EFFECT_NOT_BLACKLISTED")

    p = baseline.get("policy") or {}
    for key in ("canonical_baseline_required_for_improvement_claim", "same_strategy_id_required", "one_axis_only", "no_threshold_sweep", "derived_lineage_cannot_replace_original_baseline", "transport_or_parser_failure_is_not_economic_failure"):
        if p.get(key) is not True:
            defects.append(f"BASELINE_INTEGRITY_POLICY_MISSING:{key}")

    fresh = roadmap.get("fresh_gate_lane") or {}
    if fresh.get("order") != ["A1_CONTROLS_AND_MIN_SAMPLE", "A2_AFTER_COST_ECONOMICS", "A3_DURABILITY_AND_FRAGILITY"]:
        defects.append("A1_A2_A3_GATE_ORDER_INVALID")
    if fresh.get("parent_pass_inheritance") is not False or fresh.get("historical_substitution_for_fresh") is not False:
        defects.append("FRESH_GATE_SUBSTITUTION_NOT_BLOCKED")

    state = "PASS_RESEARCH_DEPTH_RETRY_GUARD" if not defects else "HOLD_RESEARCH_DEPTH_RETRY_GUARD"
    out: dict[str, Any] = {
        "schema_version": "zel.a1.research_depth_retry_guard.v1",
        "state": state,
        "action": "hold" if defects else "route_change",
        "evidence_counts": {name: {"observed": v[0], "required": v[1]} for name, v in checks.items()},
        "source_families": families,
        "duplicate_identifier_aliases": duplicate_identifiers,
        "a5_axis_support": axis_rows,
        "mistake_guard_code_count": len(got_codes),
        "known_attempt_count": len(attempts),
        "fresh_gate_lane": fresh,
        "integrity_defects": defects,
        "next": "RUN_A5_EVIDENCE_BACKED_AXES_AND_CONTINUE_FRESH_A1_TO_A3" if not defects else "FIX_GUARD_DEFECTS_BEFORE_NEW_REPLAY",
        "authority": roadmap.get("authority"),
    }
    out["receipt_sha256"] = sha(out)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args()
    out = audit()
    if not args.self_test:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": out["state"], "evidence_counts": out["evidence_counts"], "defect_count": len(out["integrity_defects"]), "defects": out["integrity_defects"], "next": out["next"]}, sort_keys=True))
    return 0 if not out["integrity_defects"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
