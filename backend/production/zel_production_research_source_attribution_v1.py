from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_improvement_controller_v1 import stable_sha

SCHEMA = "zel.production_research_source_attribution.v1"
EVENT_SCHEMA = "zel.production_research_source_attribution_event.v1"
POLICY_SCHEMA = "zel.production_research_source_attribution_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_research_source_attribution_v1.json")
METRIC_KEYS = ("trade_count", "win_rate_pct", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct")
PASS_EXTERNAL = "PASS_EXTERNAL_RESEARCH_EVIDENCE_READY"
PREFERRED = "CHALLENGER_RESEARCH_PREFERRED"
REFERENCE = "REFERENCE_RESEARCH_PREFERRED"


def safety() -> dict[str, Any]:
    return {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
    }


def authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "OBSERVER_ONLY_SOURCE_ATTRIBUTION_NOT_ROUTE":
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_ROLE_DRIFT")
    required = (
        "external_evidence_path",
        "next_hypothesis_path",
        "comparison_path",
        "history_path",
        "output_path",
    )
    paths: list[str] = []
    for key in required:
        value = str(policy.get(key) or "").strip()
        if not value:
            raise RuntimeError(f"RESEARCH_SOURCE_ATTRIBUTION_PATH_MISSING:{key}")
        paths.append(value)
    if len(paths) != len(set(paths)):
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_PATH_COLLISION")
    authority_guard(policy, "RESEARCH_SOURCE_ATTRIBUTION_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_MUTATION_FORBIDDEN")
    return dict(policy)


def finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"RESEARCH_SOURCE_ATTRIBUTION_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"RESEARCH_SOURCE_ATTRIBUTION_NUMERIC_NONFINITE:{label}")
    return out


def stable_source_id(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_SOURCE_URL_MISSING")
    return "ext_" + stable_sha({"url": text})[:20]


def _trim(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def source_catalog(external_evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for raw in external_evidence.get("search_sources") or []:
        if not isinstance(raw, Mapping):
            continue
        url = _trim(raw.get("url"), 2000)
        if not url:
            continue
        source_id = stable_source_id(url)
        catalog[source_id] = {
            "source_id": source_id,
            "source_type": "EXTERNAL_SEARCH",
            "source_kind": _trim(raw.get("source_kind"), 80),
            "url": url,
            "title": _trim(raw.get("title"), 300),
            "publisher": _trim(raw.get("publisher"), 200),
            "credibility_tier": raw.get("credibility_tier"),
            "mechanism": _trim(raw.get("mechanism"), 1000),
            "local_test_needed": _trim(raw.get("local_test_needed"), 1000),
            "view_count_verified": None,
            "observed_views": None,
        }
    for raw in external_evidence.get("youtube_extracts") or []:
        if not isinstance(raw, Mapping) or raw.get("status") != "USE":
            continue
        url = _trim(raw.get("url"), 2000)
        if not url:
            continue
        source_id = stable_source_id(url)
        mechanisms = [
            {
                "mechanism": _trim(item.get("mechanism"), 1000),
                "architecture_layer": _trim(item.get("architecture_layer"), 80),
                "local_test_needed": _trim(item.get("local_test_needed"), 1000),
                "limitations": _trim(item.get("limitations"), 1000),
            }
            for item in (raw.get("reproducible_mechanisms") or [])
            if isinstance(item, Mapping)
        ][:8]
        catalog[source_id] = {
            "source_id": source_id,
            "source_type": "YOUTUBE",
            "source_kind": "YOUTUBE",
            "url": url,
            "title": _trim(raw.get("title"), 300),
            "publisher": _trim(raw.get("channel"), 200),
            "credibility_tier": None,
            "mechanism": mechanisms,
            "local_test_needed": "",
            "view_count_verified": raw.get("view_count_verified") is True,
            "observed_views": raw.get("observed_views") if raw.get("view_count_verified") is True else None,
        }
    return catalog


def direction_map(external_evidence: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    url_to_id = {str(row.get("url")): source_id for source_id, row in catalog.items()}
    out: dict[str, dict[str, Any]] = {}
    for raw in external_evidence.get("hypothesis_directions") or []:
        if not isinstance(raw, Mapping):
            continue
        family_id = _trim(raw.get("family_id"), 80)
        if not family_id:
            continue
        explicit_ids = [str(x) for x in (raw.get("evidence_source_ids") or []) if str(x) in catalog]
        explicit_urls = [_trim(x, 2000) for x in (raw.get("evidence_urls") or []) if _trim(x, 2000)]
        ids = list(dict.fromkeys(explicit_ids + [url_to_id[url] for url in explicit_urls if url in url_to_id]))
        out[family_id] = {
            "family_id": family_id,
            "mechanism": _trim(raw.get("mechanism"), 1000),
            "required_sources": sorted({str(x) for x in (raw.get("required_sources") or []) if str(x)}),
            "falsification_test": _trim(raw.get("falsification_test"), 1000),
            "distinct_from_current": _trim(raw.get("distinct_from_current"), 1000),
            "evidence_source_ids": ids,
            "evidence_urls_declared": explicit_urls,
        }
    return out


def proposal_map(next_hypothesis: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in next_hypothesis.get("proposals") or []:
        if not isinstance(raw, Mapping):
            continue
        family_id = _trim(raw.get("family_id"), 80)
        if not family_id:
            continue
        out[family_id] = {
            "family_id": family_id,
            "proposal_id": _trim(raw.get("proposal_id"), 80),
            "proposal_type": _trim(raw.get("proposal_type"), 80),
            "economic_mechanism": _trim(raw.get("economic_mechanism"), 1000),
            "required_sources": sorted({str(x) for x in (raw.get("required_sources") or []) if str(x)}),
            "template_id": _trim(raw.get("template_id"), 120),
        }
    return out


def comparison_rows(comparison: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_rows = comparison.get("comparisons")
    if not isinstance(raw_rows, list):
        raw_rows = [comparison] if comparison.get("challenger_family_id") else []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        family_id = _trim(raw.get("challenger_family_id"), 80)
        delta = raw.get("delta_challenger_minus_reference")
        if not family_id or not isinstance(delta, Mapping):
            continue
        rows.append(
            {
                "challenger_family_id": family_id,
                "research_preference": _trim(raw.get("research_preference"), 80),
                "delta_challenger_minus_reference": {key: finite(delta.get(key), key) for key in METRIC_KEYS},
            }
        )
    return rows


def build_event(
    policy: Mapping[str, Any],
    *,
    external_evidence: Mapping[str, Any],
    next_hypothesis: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> dict[str, Any]:
    validate_policy(policy)
    authority_guard(external_evidence, "RESEARCH_SOURCE_ATTRIBUTION_EXTERNAL_EVIDENCE")
    authority_guard(next_hypothesis, "RESEARCH_SOURCE_ATTRIBUTION_NEXT_HYPOTHESIS")
    authority_guard(comparison, "RESEARCH_SOURCE_ATTRIBUTION_COMPARISON")
    evidence_receipt = _trim(external_evidence.get("receipt_sha256"), 128)
    next_receipt = _trim(next_hypothesis.get("receipt_sha256"), 128)
    comparison_receipt = _trim(comparison.get("receipt_sha256"), 128)
    if not evidence_receipt or not next_receipt or not comparison_receipt:
        raise RuntimeError("RESEARCH_SOURCE_ATTRIBUTION_SOURCE_RECEIPT_MISSING")

    catalog = source_catalog(external_evidence)
    directions = direction_map(external_evidence, catalog)
    proposals = proposal_map(next_hypothesis)
    comparisons = comparison_rows(comparison)
    attributed: list[dict[str, Any]] = []
    missing_proposal: list[str] = []
    missing_direction: list[str] = []
    missing_explicit_evidence_ref: list[str] = []
    for row in comparisons:
        family_id = row["challenger_family_id"]
        proposal = proposals.get(family_id)
        direction = directions.get(family_id)
        if proposal is None:
            missing_proposal.append(family_id)
            continue
        if direction is None:
            missing_direction.append(family_id)
            continue
        refs = [source_id for source_id in direction["evidence_source_ids"] if source_id in catalog]
        if not refs:
            missing_explicit_evidence_ref.append(family_id)
            continue
        attributed.append(
            {
                "family_id": family_id,
                "proposal_id": proposal["proposal_id"],
                "proposal_type": proposal["proposal_type"],
                "template_id": proposal["template_id"],
                "native_sources": proposal["required_sources"],
                "proposal_mechanism": proposal["economic_mechanism"],
                "external_direction_mechanism": direction["mechanism"],
                "external_falsification_test": direction["falsification_test"],
                "evidence_source_ids": refs,
                "evidence_sources": [dict(catalog[source_id]) for source_id in refs],
                "joint_evidence_association": len(refs) > 1,
                "research_preference": row["research_preference"],
                "delta_challenger_minus_reference": row["delta_challenger_minus_reference"],
                "attribution_mode": "EXACT_FAMILY_PLUS_EXPLICIT_EVIDENCE_REF_ASSOCIATION",
            }
        )

    fingerprint = stable_sha(
        {
            "external_evidence_receipt_sha256": evidence_receipt,
            "next_hypothesis_receipt_sha256": next_receipt,
            "comparison_receipt_sha256": comparison_receipt,
        }
    )
    event = {
        "schema_version": EVENT_SCHEMA,
        "event_fingerprint_sha256": fingerprint,
        "external_evidence_state": _trim(external_evidence.get("state"), 160),
        "external_evidence_error_class": _trim(external_evidence.get("error_class"), 160),
        "external_evidence_error_code": _trim(external_evidence.get("error_code"), 800),
        "external_evidence_receipt_sha256": evidence_receipt,
        "next_hypothesis_receipt_sha256": next_receipt,
        "comparison_receipt_sha256": comparison_receipt,
        "comparison_count": len(comparisons),
        "attributed_comparison_count": len(attributed),
        "preferred_attributed_count": sum(row["research_preference"] == PREFERRED for row in attributed),
        "reference_preferred_attributed_count": sum(row["research_preference"] == REFERENCE for row in attributed),
        "source_catalog_count": len(catalog),
        "attributed_source_count": len({source_id for row in attributed for source_id in row["evidence_source_ids"]}),
        "attributions": attributed,
        "unattributed": {
            "missing_proposal_family_ids": sorted(set(missing_proposal)),
            "missing_external_direction_family_ids": sorted(set(missing_direction)),
            "missing_explicit_evidence_ref_family_ids": sorted(set(missing_explicit_evidence_ref)),
        },
        "attribution_scope": "SOURCE_AND_NATIVE_INPUT_ASSOCIATION_NOT_CAUSAL_OR_MARGINAL_PNL_ATTRIBUTION",
        **safety(),
    }
    event["receipt_sha256"] = stable_sha(event)
    return event


def _metric_slot() -> dict[str, Any]:
    return {
        "association_count": 0,
        "preferred_count": 0,
        "reference_preferred_count": 0,
        "delta_sum": {key: 0.0 for key in METRIC_KEYS},
        "delta_average": {key: 0.0 for key in METRIC_KEYS},
        "family_ids": [],
    }


def _accumulate(slot: dict[str, Any], attribution: Mapping[str, Any]) -> None:
    slot["association_count"] += 1
    slot["preferred_count"] += int(attribution.get("research_preference") == PREFERRED)
    slot["reference_preferred_count"] += int(attribution.get("research_preference") == REFERENCE)
    family_id = str(attribution.get("family_id") or "")
    if family_id and family_id not in slot["family_ids"]:
        slot["family_ids"].append(family_id)
    delta = attribution.get("delta_challenger_minus_reference")
    if isinstance(delta, Mapping):
        for key in METRIC_KEYS:
            slot["delta_sum"][key] += float(delta.get(key) or 0.0)
    count = int(slot["association_count"])
    slot["delta_average"] = {
        key: float(slot["delta_sum"][key]) / count if count else 0.0 for key in METRIC_KEYS
    }


def aggregate(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(history)
    source_breakdown: dict[str, dict[str, Any]] = {}
    native_breakdown: dict[str, dict[str, Any]] = {}
    family_breakdown: dict[str, dict[str, Any]] = {}
    total_attributed = 0
    preferred = 0
    reference_preferred = 0
    for event in rows:
        for attribution in event.get("attributions") or []:
            if not isinstance(attribution, Mapping):
                continue
            total_attributed += 1
            preferred += int(attribution.get("research_preference") == PREFERRED)
            reference_preferred += int(attribution.get("research_preference") == REFERENCE)
            family_id = str(attribution.get("family_id") or "")
            if family_id:
                slot = family_breakdown.setdefault(family_id, _metric_slot())
                _accumulate(slot, attribution)
            for native in attribution.get("native_sources") or []:
                key = str(native)
                slot = native_breakdown.setdefault(key, _metric_slot())
                _accumulate(slot, attribution)
            for source in attribution.get("evidence_sources") or []:
                if not isinstance(source, Mapping):
                    continue
                source_id = str(source.get("source_id") or "")
                if not source_id:
                    continue
                if source_id not in source_breakdown:
                    slot = _metric_slot()
                    slot.update(
                        {
                            "source_type": source.get("source_type"),
                            "source_kind": source.get("source_kind"),
                            "url": source.get("url"),
                            "title": source.get("title"),
                            "publisher": source.get("publisher"),
                            "view_count_verified": source.get("view_count_verified"),
                            "observed_views": source.get("observed_views"),
                        }
                    )
                    source_breakdown[source_id] = slot
                _accumulate(source_breakdown[source_id], attribution)
    return {
        "generation_count": len(rows),
        "attributed_comparison_count": total_attributed,
        "preferred_attributed_count": preferred,
        "reference_preferred_attributed_count": reference_preferred,
        "preferred_attributed_rate_pct": 100.0 * preferred / total_attributed if total_attributed else 0.0,
        "source_breakdown": source_breakdown,
        "native_source_breakdown": native_breakdown,
        "family_breakdown": family_breakdown,
    }


def attribution_tick(
    policy: Mapping[str, Any],
    *,
    external_evidence: Mapping[str, Any],
    next_hypothesis: Mapping[str, Any],
    comparison: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    try:
        event = build_event(
            cfg,
            external_evidence=external_evidence,
            next_hypothesis=next_hypothesis,
            comparison=comparison,
        )
    except Exception as exc:
        out = {
            "schema_version": SCHEMA,
            "state": "HOLD_RESEARCH_SOURCE_ATTRIBUTION_SOURCE_INVALID",
            "role": cfg["role"],
            "error_class": type(exc).__name__,
            "error_code": str(exc)[:500],
            "history_append_required": False,
            "attribution_scope": "SOURCE_AND_NATIVE_INPUT_ASSOCIATION_NOT_CAUSAL_OR_MARGINAL_PNL_ATTRIBUTION",
            **safety(),
        }
        out["receipt_sha256"] = stable_sha(out)
        return out, None

    seen = {str(row.get("event_fingerprint_sha256") or "") for row in history}
    append_required = event["event_fingerprint_sha256"] not in seen
    effective = list(history) + ([event] if append_required else [])
    external_state = event["external_evidence_state"]
    if external_state != PASS_EXTERNAL:
        state = "HOLD_RESEARCH_SOURCE_ATTRIBUTION_EXTERNAL_EVIDENCE_NOT_READY"
    elif event["comparison_count"] <= 0:
        state = "HOLD_RESEARCH_SOURCE_ATTRIBUTION_COMPARISON_NOT_READY"
    elif event["attributed_comparison_count"] <= 0:
        state = "HOLD_RESEARCH_SOURCE_ATTRIBUTION_EXPLICIT_LINK_NOT_READY"
    elif event["preferred_attributed_count"] > 0:
        state = "PASS_RESEARCH_SOURCE_ATTRIBUTION_POSITIVE_SIGNAL_CAPTURED"
    else:
        state = "PASS_RESEARCH_SOURCE_ATTRIBUTION_CAPTURED_NO_POSITIVE_SIGNAL"

    out = {
        "schema_version": SCHEMA,
        "state": state,
        "role": cfg["role"],
        "current_event_fingerprint_sha256": event["event_fingerprint_sha256"],
        "history_append_required": append_required,
        "current": {
            "external_evidence_state": external_state,
            "external_evidence_error_class": event["external_evidence_error_class"],
            "external_evidence_error_code": event["external_evidence_error_code"],
            "comparison_count": event["comparison_count"],
            "attributed_comparison_count": event["attributed_comparison_count"],
            "attributed_source_count": event["attributed_source_count"],
            "preferred_attributed_count": event["preferred_attributed_count"],
            "reference_preferred_attributed_count": event["reference_preferred_attributed_count"],
            "unattributed": event["unattributed"],
        },
        "aggregate": aggregate(effective),
        "attribution_scope": event["attribution_scope"],
        **safety(),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out, event if append_required else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Observer-only research source attribution")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--self-test", action="store_true")
    ns = ap.parse_args(argv)
    if ns.self_test:
        print("PASS_RESEARCH_SOURCE_ATTRIBUTION_MODULE_LOAD")
        return 0
    raise SystemExit("OBSERVER_RUNTIME_WIRED_BY_GITHUB_ACTION")


if __name__ == "__main__":
    raise SystemExit(main())
