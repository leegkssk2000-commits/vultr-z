#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/g5_broad_w2_failfast_v1.json"
TARGET = ROOT / "backend/research/prep/g5_trendrider_broad30_product_oos_v1.py"

OLD = '''    if not w2_ready:\n        state = "WAIT_G5_W2_12"\n    elif not w3_ready:\n        state = "WAIT_G5_W3_12"\n    elif all(checks.values()):\n        state = "PASS_G5_PRODUCT_OOS_WALK_FORWARD_STRESS"\n    else:\n        state = "HOLD_G5_PRODUCT_VALIDATION_FAIL"\n'''
NEW = '''    if not w2_ready:\n        state = "WAIT_G5_W2_12"\n    elif not checks["w2_economics_nonfail"]:\n        state = "FAIL_G5_W2_ECONOMICS_STOP_W3"\n    elif not w3_ready:\n        state = "WAIT_G5_W3_12"\n    elif all(checks.values()):\n        state = "PASS_G5_PRODUCT_OOS_WALK_FORWARD_STRESS"\n    else:\n        state = "HOLD_G5_PRODUCT_VALIDATION_FAIL"\n'''
ANCHOR = '        "checks": checks,\n'
META = '''        "stage_stop_policy": {\n            "contract": "backend/research/contracts/g5_broad_w2_failfast_v1.json",\n            "w2_terminal_failfast_enabled": True,\n            "w2_target_T": 12,\n            "w3_required_only_if_w2_economics_nonfail": True,\n            "terminal_fail_state": "FAIL_G5_W2_ECONOMICS_STOP_W3",\n        },\n'''


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def validate_contract() -> dict:
    c = read_json(CONTRACT)
    if c.get("state") != "PREREGISTERED_W2_TERMINAL_FAILFAST_BEFORE_W2_COMPLETION":
        raise RuntimeError("FAILFAST_CONTRACT_STATE_DRIFT")
    obs = c.get("current_observation_at_registration") or {}
    if int(obs.get("W2_closed_T") or 0) != 6 or int(obs.get("W2_target_T") or 0) != 12:
        raise RuntimeError("FAILFAST_NOT_PREREGISTERED_AT_6_OF_12")
    if c.get("terminal_fail_state") != "FAIL_G5_W2_ECONOMICS_STOP_W3":
        raise RuntimeError("TERMINAL_FAIL_STATE_DRIFT")
    integ = c.get("integrity") or {}
    for key in ("strategy_policy_retune", "threshold_retune", "symbol_retune", "exit_retune", "cost_retune", "W2_sample_selection", "W3_sample_selection"):
        if integ.get(key) is not False:
            raise RuntimeError(f"INTEGRITY_DRIFT:{key}")
    return c


def apply() -> None:
    validate_contract()
    text = TARGET.read_text(encoding="utf-8")
    if NEW in text and META in text:
        print("PASS_W2_FAILFAST_ALREADY_APPLIED")
        return
    if text.count(OLD) != 1:
        raise RuntimeError(f"EXPECTED_EXACT_OLD_STATE_BLOCK_ONCE:{text.count(OLD)}")
    if text.count(ANCHOR) != 1:
        raise RuntimeError(f"EXPECTED_CHECKS_ANCHOR_ONCE:{text.count(ANCHOR)}")
    text = text.replace(OLD, NEW, 1)
    text = text.replace(ANCHOR, META + ANCHOR, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("PASS_W2_FAILFAST_APPLIED")


def verify() -> None:
    validate_contract()
    text = TARGET.read_text(encoding="utf-8")
    assert OLD not in text
    assert text.count(NEW) == 1
    assert text.count(META) == 1
    assert 'FAIL_G5_W2_ECONOMICS_STOP_W3' in text
    print("PASS_W2_FAILFAST_PATCH_VERIFY")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        apply()
    else:
        validate_contract()
        print("PASS_W2_FAILFAST_PATCH_PREREGISTRATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
