#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/contracts/g5_clean_runner_contract_v1.json"
SHADOW_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_shadow_v1.json"
EVIDENCE_PATH = ROOT / "backend/research/rebuild/g5_data_stale_evidence_v1.json"


class CadenceAuthorityError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CadenceAuthorityError(f"OBJECT_REQUIRED:{path}")
    return value


def sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha_json(result)
    return result


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def derive_authority(
    contract: Mapping[str, Any], shadow: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    interval_ms = int((contract.get("source") or {}).get("interval_ms") or 0)
    if interval_ms <= 0:
        raise CadenceAuthorityError("CONTRACT_INTERVAL_REQUIRED")

    if not (
        shadow.get("state") == "CLEAN_RUNNER_SHADOW_PASS"
        and shadow.get("shadow_3bar_pass") is True
        and int(shadow.get("complete_bar_count") or 0) >= 3
        and int(shadow.get("consecutive_complete_bar_count") or 0) >= 3
        and shadow.get("source_parity") is True
        and shadow.get("child_parity") is True
        and int(shadow.get("duplicate") or 0) == 0
        and int(shadow.get("lookahead") or 0) == 0
        and int(shadow.get("formal_credit") or 0) == 0
    ):
        raise CadenceAuthorityError("CLEAN_RUNNER_3BAR_INTEGRITY_REQUIRED")

    if evidence.get("schema_version") != "zel.g5.data_stale.evidence.v1":
        raise CadenceAuthorityError("EVIDENCE_SCHEMA_DRIFT")
    if evidence.get("timestamp_integrity") != "PASS":
        raise CadenceAuthorityError("TIMESTAMP_INTEGRITY_REQUIRED")
    if int(evidence.get("normal_N") or 0) <= 0:
        raise CadenceAuthorityError("NORMAL_EVIDENCE_REQUIRED")
    if int(evidence.get("fresh_credit") or 0) != 0:
        raise CadenceAuthorityError("FRESH_CREDIT_MUST_REMAIN_ZERO")
    if evidence.get("ssot_mutated") is not False:
        raise CadenceAuthorityError("INPUT_EVIDENCE_MUTATION_FLAG_DRIFT")

    # The real-failure collector already defines a missed genuine cadence as
    # evaluation_age_ms >= contract.source.interval_ms. Waiting for an actual
    # outage before defining the same boundary makes a healthy runner unable
    # to progress. Bind the authority to the frozen cadence, not to a fitted
    # failure distribution. No threshold sweep or economic/strategy mutation.
    core = dict(evidence)
    core.pop("receipt_sha256", None)
    core.update({
        "state": "DATA_STALE_AUTHORITY_PASS_CADENCE_LOCK",
        "first_blocker": None,
        "authority_value": interval_ms,
        "authority_unit": "ms",
        "authority_created": True,
        "authority_source": "CONTRACT_GENUINE_CADENCE_LOCK",
        "authority_rule": "evaluation_age_ms>=contract.source.interval_ms",
        "authority_empirical_fit": False,
        "authority_requires_observed_outage": False,
        "data_stale_authority_allowed": True,
        "threshold_surface_allowed": False,
        "false_stale_false_fresh_tradeoff_computable": False,
        "robust_plateau": None,
        "strategy_mutation": False,
        "economic_mutation": False,
        "contract_mutation": False,
        "ssot_mutated": False,
        "fresh_credit": 0,
        "formal_credit": 0,
        "next": "MANUAL_CUTOVER_THEN_POST_CUTOVER_3_GENUINE_BARS",
    })
    return receipt(core)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--shadow", type=Path, default=SHADOW_PATH)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--output", type=Path, default=EVIDENCE_PATH)
    args = parser.parse_args()
    result = derive_authority(read_json(args.contract), read_json(args.shadow), read_json(args.evidence))
    write_json(args.output, result)
    print(json.dumps({
        "state": result["state"],
        "authority_value": result["authority_value"],
        "authority_unit": result["authority_unit"],
        "authority_source": result["authority_source"],
        "data_stale_authority_allowed": result["data_stale_authority_allowed"],
        "fresh_credit": result["fresh_credit"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
