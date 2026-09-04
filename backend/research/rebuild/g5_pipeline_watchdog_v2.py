#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import g5_pipeline_watchdog_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
R = ROOT / "backend/research/rebuild"
PREP = ROOT / "backend/research/prep"
EXIT_FEATURE = R / "g5_exit_feature_ledger_latest_v1.json"
EXIT_LAB = R / "g5_exit_family_lab_latest_v1.json"
EXIT_AI = PREP / "g5_exit_ai_research_latest.json"
SCHEMA = "zel.g5.pipeline_watchdog.v2"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        x = json.loads(path.read_text(encoding="utf-8"))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _http_status_from_error(value: Any) -> int | None:
    text = str(value or "")
    for code in (429, 500, 502, 503, 504, 400, 401, 403, 404):
        if str(code) in text:
            return code
    return None


def build() -> dict[str, Any]:
    base = v1.build()
    feature = _load(EXIT_FEATURE)
    lab = _load(EXIT_LAB)
    ai = _load(EXIT_AI)

    forward = base.get("forward_real") if isinstance(base.get("forward_real"), Mapping) else {}
    prod_t = int(forward.get("production_grade_T") or 0)
    feature_prod = int(feature.get("production_forward_real_T") or 0)
    feature_complete = int(feature.get("feature_complete_T") or 0)
    lab_t = int(lab.get("production_feature_T") or 0)

    root: list[str] = []
    dependent: list[str] = []
    economic: list[str] = []

    # Convert the V1 flat blocker list into root causes.  A downstream wait caused by
    # missing upstream evidence is not a second bottleneck.
    for b in base.get("bottlenecks") or []:
        b = str(b)
        if b.startswith("FORWARD_REAL:UPSTREAM_SIGNAL_STARVATION"):
            dependent.append(b)
        elif b.startswith("TRENDRIDER_BBO:BBO_CANDIDATE_SIGNAL_STARVATION"):
            root.append(b)
        elif b.endswith(":ECONOMIC_EVIDENCE_NEGATIVE"):
            economic.append(b)
        else:
            root.append(b)

    if prod_t == 0:
        dependent.append("EXIT_FEATURE_LEDGER:WAIT_UPSTREAM_FORWARD_REAL_T")
        dependent.append("EXIT_FAMILY_LAB:WAIT_UPSTREAM_EXIT_FEATURE_T")
    else:
        if feature_prod < prod_t:
            root.append(f"EXIT_FEATURE_LEDGER:PRODUCTION_T_MISMATCH:{feature_prod}<{prod_t}")
        if feature_complete < feature_prod:
            root.append(f"EXIT_FEATURE_LEDGER:V4_FEATURE_CAPTURE_GAP:{feature_complete}<{feature_prod}")
        elif feature_complete < 6:
            dependent.append(f"EXIT_FEATURE_LEDGER:ACCUMULATING:{feature_complete}/6")
        if lab_t < feature_complete:
            root.append(f"EXIT_FAMILY_LAB:INPUT_T_MISMATCH:{lab_t}<{feature_complete}")
        elif lab_t < 6:
            dependent.append(f"EXIT_FAMILY_LAB:ACCUMULATING:{lab_t}/6")

    ai_state = str(ai.get("state") or "MISSING")
    ai_http = _http_status_from_error(ai.get("provider_error"))
    if ai_state == "HOLD_PAID_AI_PROVIDER_ERROR":
        # Paid-AI outage must never masquerade as a data/strategy bottleneck. The
        # deterministic path keeps running; manual retry is allowed only explicitly.
        dependent.append(f"EXIT_AI:PROVIDER_BLOCKED_HTTP_{ai_http or 'UNKNOWN'}__DETERMINISTIC_CONTINUES")
    elif ai_state == "HOLD_GROUNDING_SOURCES_INSUFFICIENT":
        dependent.append("EXIT_AI:GROUNDING_INSUFFICIENT__NO_FORMAL_CREDIT")

    # A child/strategy with completed negative fresh evidence is an economic failure,
    # not an infrastructure blocker. Keep it visible but separate.
    root = list(dict.fromkeys(root))
    dependent = list(dict.fromkeys(dependent))
    economic = list(dict.fromkeys(economic))

    state = "G5_ROOT_BOTTLENECKS_PRESENT" if root else (
        "G5_EVIDENCE_ACCUMULATING" if dependent else "G5_PIPELINE_FLOWING"
    )
    out = dict(base)
    out.update({
        "schema_version": SCHEMA,
        "state": state,
        "root_bottlenecks": root,
        "dependent_waits": dependent,
        "economic_failures": economic,
        "bottlenecks": root,
        "exit_research": {
            "feature_ledger_state": feature.get("state"),
            "production_forward_real_T": feature_prod,
            "feature_complete_T": feature_complete,
            "microstructure_sample_T": int(feature.get("microstructure_sample_T") or 0),
            "post_exit_complete_T": int(feature.get("post_exit_complete_T") or 0),
            "family_lab_state": lab.get("state"),
            "family_lab_T": lab_t,
            "research_leader_non_authoritative": lab.get("research_leader_non_authoritative"),
            "g6_preregister_candidate_non_authoritative": lab.get("g6_preregister_candidate_non_authoritative"),
            "formal_credit": 0,
        },
        "paid_ai": {
            "state": ai_state,
            "http_status": ai_http,
            "provider_call_last_receipt": ai.get("provider_call_this_run"),
            "cache_hit": ai.get("cache_hit"),
            "paid_recall_blocked": ai.get("paid_recall_blocked"),
            "failure_signature_sha256": ai.get("failure_signature_sha256"),
            "formal_credit": 0,
        },
        "legacy_rr_geometry": {
            "automatic_trigger": False,
            "write_authority": False,
            "role": "RETIRED_ARCHIVE_ONLY",
        },
    })
    out.pop("receipt_sha256", None)
    out["receipt_sha256"] = v1.stable(out)
    return out


def self_test() -> int:
    assert _http_status_from_error("HTTP Error 429: Too Many Requests") == 429
    assert _http_status_from_error("x") is None
    print("PASS_G5_PIPELINE_WATCHDOG_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="out/g5_pipeline_watchdog_latest_v2.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    out = build()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": out["state"],
        "root_bottlenecks": out["root_bottlenecks"],
        "dependent_waits": out["dependent_waits"],
        "economic_failures": out["economic_failures"],
        "exit_research": out["exit_research"],
        "paid_ai": out["paid_ai"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
