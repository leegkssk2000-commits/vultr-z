from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_exact25_survivor_gate_v1 import load_external_hardening_evidence
from backend.tools import zel_economic_hardening_gate_v1 as hardening_engine

ROOT = Path(__file__).resolve().parents[3]
AUTO_SEARCH_ROOTS = (
    ROOT / "backend/research/rebuild/hardening_evidence",
    ROOT / "backend/research/economic_hardening",
)


def _identity_views(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = [value]
    for key in ("identity", "binding", "candidate", "strategy_binding", "receipt_binding"):
        row = value.get(key)
        if isinstance(row, Mapping):
            out.append(row)
    return out


def _first_identity(value: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for view in _identity_views(value):
        for key in keys:
            raw = view.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    return None


def _receipt_identity(receipt: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "strategy_id": str(receipt.get("strategy_id") or "").strip() or None,
        "policy_sha": str(receipt.get("policy_sha") or "").strip() or None,
        "config_sha": str(receipt.get("config_sha") or "").strip() or None,
        "boundary_utc": str(receipt.get("boundary_utc") or "").strip() or None,
        "cost_authority_sha256": str(receipt.get("cost_authority_sha256") or "").strip() or None,
    }


def evidence_matches_receipt(evidence: Mapping[str, Any], receipt: Mapping[str, Any]) -> bool:
    """Require exact strategy+policy identity; reject generic or fixture evidence.

    Optional config/boundary/cost bindings become mandatory matches when the
    evidence declares them. This prevents a valid H4/OOS receipt for one frozen
    candidate from silently satisfying another candidate's survivor gate.
    """
    identity = _receipt_identity(receipt)
    if not identity["strategy_id"] or not identity["policy_sha"]:
        return False

    state = str(evidence.get("state") or "").upper()
    if evidence.get("fixture") is True or "FIXTURE" in state:
        return False

    strategy_id = _first_identity(evidence, ("strategy_id", "strategy"))
    policy_sha = _first_identity(evidence, ("policy_sha", "policy_source_sha", "policy_config_source_sha"))
    if strategy_id != identity["strategy_id"] or policy_sha != identity["policy_sha"]:
        return False

    optional = {
        "config_sha": ("config_sha",),
        "boundary_utc": ("boundary_utc", "prospective_boundary_utc"),
        "cost_authority_sha256": ("cost_authority_sha256", "cost_model_sha256", "cost_sha256"),
    }
    for target_key, aliases in optional.items():
        declared = _first_identity(evidence, aliases)
        if declared is not None and declared != identity[target_key]:
            return False
    return True


def _candidate_files() -> list[Path]:
    candidates: set[Path] = set()
    for root in AUTO_SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for pattern in ("*hardening*evidence*.json", "*survivor*evidence*.json", "*oos*h4*.json", "*hardening*receipt*.json"):
            candidates.update(root.rglob(pattern))
    return sorted(p for p in candidates if p.is_file())


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _has_survivor_evidence_shape(value: Mapping[str, Any]) -> bool:
    # A standalone generic H4 fixture is not enough. Auto-attachment is for a
    # candidate-specific bundle containing at least one survivor-hardening field;
    # the survivor gate still validates all missing fields as PENDING.
    return any(key in value for key in ("retention_pct", "oos", "h4_receipt", "negative_control"))


def _auto_discover(receipt: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in _candidate_files():
        value = _read_object(path)
        if value is None or not _has_survivor_evidence_shape(value):
            continue
        if evidence_matches_receipt(value, receipt):
            matches.append((path, value))
    if len(matches) != 1:
        # zero = no evidence yet; >1 = ambiguous lineage. Both fail closed.
        return None, None
    path, value = matches[0]
    return value, str(path.relative_to(ROOT))


def _verify_and_normalize(evidence: Mapping[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
    out = dict(evidence)
    h4 = out.get("h4_receipt")
    if h4 is not None:
        verified = hardening_engine.verify_embedded_receipt(
            h4,
            field="A1.survivor_gate.h4_receipt",
            expected_state="PASS_PLACEBO_NEGATIVE_CONTROLS",
            fixture_allowed=False,
        )
        if verified.get("schema_version") != "zel.economic_hardening.h4.receipt.v2":
            raise RuntimeError("A1_H4_RECEIPT_SCHEMA_INVALID")
        if verified.get("control") != "H4_PLACEBO_NEGATIVE_CONTROLS":
            raise RuntimeError("A1_H4_RECEIPT_CONTROL_INVALID")
        if verified.get("same_windows_costs_trade_budget_verified") is not True:
            raise RuntimeError("A1_H4_LINEAGE_OR_BUDGET_NOT_VERIFIED")
        results = verified.get("control_results")
        if not isinstance(results, dict) or not results:
            raise RuntimeError("A1_H4_CONTROL_RESULTS_MISSING")
        if any(not isinstance(row, dict) or row.get("pass") is not True for row in results.values()):
            raise RuntimeError("A1_H4_CONTROL_RESULT_NOT_PASS")
        out["negative_control"] = {
            "state": "PASS_DETERMINISTIC_REPLAY_RESULT",
            "p_value": max(float(row["p_value"]) for row in results.values()),
            "candidate_minus_control_ci_low_R": min(float(row["candidate_minus_control_ci_low_R"]) for row in results.values()),
            "equal_trade_budget": True,
            "identical_cost_model_sha": True,
            "identical_window_sha": True,
            "controls": {name: {"state": "PASS", "source_receipt_sha256": row.get("source_receipt_sha256")} for name, row in results.items()},
            "verified_h4_receipt_sha256": verified["receipt_sha256"],
            "verified_by_existing_hardening_engine": True,
        }
    if source_path:
        out["auto_attached_source_path"] = source_path
    return out


def load_verified_hardening_evidence(receipt: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Load explicit or automatically discovered candidate-matched hardening evidence.

    No H4/OOS/retention value is synthesized. Automatic discovery requires exact
    frozen strategy+policy identity and rejects fixtures/ambiguity. The existing
    hardening engine remains the authority for cryptographic H4 verification.
    """
    explicit = load_external_hardening_evidence()
    if explicit is not None:
        if receipt is not None and not evidence_matches_receipt(explicit, receipt):
            return None
        return _verify_and_normalize(explicit, source_path=os.environ.get("A1_HARDENING_RECEIPT_PATH") or None)

    if receipt is None:
        return None
    discovered, source_path = _auto_discover(receipt)
    if discovered is None:
        return None
    return _verify_and_normalize(discovered, source_path=source_path)
