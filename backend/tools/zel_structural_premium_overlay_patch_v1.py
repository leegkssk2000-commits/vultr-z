from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import tempfile
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH_V2_SIX_AXIS"
SCHEMA = "zel.structural_premium.overlay.v1"
MARKER = "# ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH_V2_SIX_AXIS"
ENTRY_OWNERS = ("vwap_revert", "support_resistance", "liquidity_sweep", "trend_rider")
MAIN_OWNERS = ("vwap_revert", "support_resistance")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_candidate(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text())
    if row.get("schema_version") != SCHEMA:
        raise RuntimeError(f"OVERLAY_SCHEMA:{row.get('schema_version')}")
    params = row.get("parameters")
    if not isinstance(params, dict):
        raise RuntimeError("OVERLAY_PARAMETERS_REQUIRED")
    stop = float(params.get("stop_distance_mult", 1.0))
    target = float(params.get("target_distance_mult", 1.0))
    confidence = params.get("min_confidence")
    confidence = None if confidence is None else float(confidence)
    cooldown = float(params.get("cooldown_min", 0.0))
    min_risk = float(params.get("min_risk_distance_pct", 0.0))
    max_hold = float(params.get("max_hold_min", 120.0))
    owners = params.get("enabled_entry_owners")
    if not isinstance(owners, list) or not owners:
        owners = list(ENTRY_OWNERS)
    owners = [name for name in ENTRY_OWNERS if name in {str(x) for x in owners}]
    if not all(name in owners for name in MAIN_OWNERS):
        raise RuntimeError(f"MAIN_ENTRY_OWNERS_REQUIRED:{owners}")
    if not 0.70 <= stop <= 1.25:
        raise RuntimeError(f"STOP_MULT_RANGE:{stop}")
    if not 0.80 <= target <= 1.50:
        raise RuntimeError(f"TARGET_MULT_RANGE:{target}")
    if confidence is not None and not 0.0 <= confidence <= 0.90:
        raise RuntimeError(f"CONFIDENCE_RANGE:{confidence}")
    if not 0.0 <= cooldown <= 120.0:
        raise RuntimeError(f"COOLDOWN_RANGE:{cooldown}")
    if not 0.0 <= min_risk <= 2.0:
        raise RuntimeError(f"MIN_RISK_DISTANCE_RANGE:{min_risk}")
    if not 15.0 <= max_hold <= 240.0:
        raise RuntimeError(f"MAX_HOLD_RANGE:{max_hold}")
    normalized = {
        "schema_version": SCHEMA,
        "candidate_id": str(row.get("candidate_id") or "UNKNOWN"),
        "generation": int(row.get("generation") or 0),
        "axis": str(row.get("axis") or "BASELINE"),
        "closed_loop_axes": list(row.get("closed_loop_axes") or []),
        "parameters": {
            "stop_distance_mult": stop,
            "target_distance_mult": target,
            "min_confidence": confidence,
            "cooldown_min": cooldown,
            "min_risk_distance_pct": min_risk,
            "max_hold_min": max_hold,
            "enabled_entry_owners": owners,
        },
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    normalized["overlay_sha256"] = stable_sha(normalized)
    return normalized


def overlay_source(candidate: dict[str, Any]) -> str:
    encoded = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
    return f'''\n{MARKER}\n_ZEL_OVERLAY = json.loads({encoded!r})\n_ZEL_BASE_RESTORE = _restore_structural_premium_registry\n\nclass _ZelOverlayOwnerProxy:\n    def __init__(self, base, strategy):\n        self._base = base\n        self.strategy = strategy\n        self.owner_path = getattr(base, "owner_path", "")\n        self.owner_sha256 = getattr(base, "owner_sha256", "")\n    def __getattr__(self, name):\n        return getattr(self._base, name)\n\ndef _zel_float(value):\n    try:\n        value = float(value)\n        return value if value == value and abs(value) != float("inf") else None\n    except Exception:\n        return None\n\ndef _zel_find_confidence(node):\n    if not isinstance(node, dict):\n        return None\n    for key in ("confidence", "score", "strength", "signal_score"):\n        value = _zel_float(node.get(key))\n        if value is not None:\n            return value\n    for key in ("result", "signal", "setup", "trade", "order"):\n        value = _zel_find_confidence(node.get(key))\n        if value is not None:\n            return value\n    return None\n\ndef _zel_is_long(node):\n    if not isinstance(node, dict):\n        return False\n    values = []\n    for key in ("action", "signal", "side", "direction"):\n        value = node.get(key)\n        if isinstance(value, str):\n            values.append(value.strip().lower())\n    if any(value in {{"long", "buy", "bull", "enter_long", "open_long"}} for value in values):\n        return True\n    for key in ("result", "signal", "setup", "trade", "order"):\n        if isinstance(node.get(key), dict) and _zel_is_long(node.get(key)):\n            return True\n    return False\n\ndef _zel_hold(node, reason):\n    if not isinstance(node, dict):\n        return node\n    out = dict(node)\n    changed = False\n    for key in ("action", "signal"):\n        value = out.get(key)\n        if isinstance(value, str) and value.strip().lower() in {{"long", "buy", "bull", "enter_long", "open_long"}}:\n            out[key] = "hold"\n            changed = True\n    for key in ("result", "signal", "setup", "trade", "order"):\n        if isinstance(out.get(key), dict):\n            nested = _zel_hold(out[key], reason)\n            if nested != out[key]:\n                changed = True\n            out[key] = nested\n    if changed:\n        out["overlay_blocked"] = True\n        out["overlay_block_reason"] = reason\n    return out\n\ndef _zel_find_geometry(node):\n    if not isinstance(node, dict):\n        return None\n    entry_key = next((key for key in ("entry", "entry_price", "price") if _zel_float(node.get(key)) is not None), None)\n    sl_key = next((key for key in ("sl", "stop", "stop_loss", "stop_price") if _zel_float(node.get(key)) is not None), None)\n    tp_key = next((key for key in ("tp", "target", "take_profit", "tp_price") if _zel_float(node.get(key)) is not None), None)\n    if entry_key is not None:\n        entry = _zel_float(node.get(entry_key))\n        sl = _zel_float(node.get(sl_key)) if sl_key is not None else None\n        tp = _zel_float(node.get(tp_key)) if tp_key is not None else None\n        return entry, sl, tp\n    for key in ("result", "signal", "setup", "trade", "order"):\n        found = _zel_find_geometry(node.get(key))\n        if found is not None:\n            return found\n    return None\n\ndef _zel_adjust_geometry(node, stop_mult, target_mult):\n    if not isinstance(node, dict):\n        return node\n    out = dict(node)\n    entry_key = next((key for key in ("entry", "entry_price", "price") if _zel_float(out.get(key)) is not None), None)\n    sl_key = next((key for key in ("sl", "stop", "stop_loss", "stop_price") if _zel_float(out.get(key)) is not None), None)\n    tp_key = next((key for key in ("tp", "target", "take_profit", "tp_price") if _zel_float(out.get(key)) is not None), None)\n    if entry_key is not None:\n        entry = _zel_float(out.get(entry_key))\n        if sl_key is not None:\n            sl = _zel_float(out.get(sl_key))\n            if sl is not None and entry is not None and sl < entry:\n                out[sl_key] = entry - (entry - sl) * stop_mult\n                out["overlay_stop_distance_mult"] = stop_mult\n        if tp_key is not None:\n            tp = _zel_float(out.get(tp_key))\n            if tp is not None and entry is not None and tp > entry:\n                out[tp_key] = entry + (tp - entry) * target_mult\n                out["overlay_target_distance_mult"] = target_mult\n    for key in ("result", "signal", "setup", "trade", "order"):\n        if isinstance(out.get(key), dict):\n            out[key] = _zel_adjust_geometry(out[key], stop_mult, target_mult)\n    return out\n\ndef _zel_current_epoch(current):\n    try:\n        if current is None or len(current) == 0:\n            return None\n        row = current.iloc[-1]\n        value = row.get("timestamp_ms") if hasattr(row, "get") else None\n        if value is not None:\n            number = _zel_float(value)\n            if number is not None:\n                return number / 1000.0 if number > 10_000_000_000 else number\n        value = row.get("timestamp") if hasattr(row, "get") else None\n        if value is not None and hasattr(value, "timestamp"):\n            return float(value.timestamp())\n    except Exception:\n        return None\n    return None\n\ndef _zel_disabled_strategy(current, state=None, risk_action="hold"):\n    return {{"action": "hold", "overlay_blocked": True, "overlay_block_reason": "PORTFOLIO_OWNER_DISABLED"}}\n\ndef _zel_wrap_strategy(fn):\n    params = _ZEL_OVERLAY["parameters"]\n    stop_mult = float(params.get("stop_distance_mult", 1.0))\n    target_mult = float(params.get("target_distance_mult", 1.0))\n    min_conf = params.get("min_confidence")\n    cooldown_min = float(params.get("cooldown_min", 0.0))\n    min_risk_distance_pct = float(params.get("min_risk_distance_pct", 0.0))\n    last_entry_epoch = None\n\n    def wrapped(current, state=None, risk_action="hold"):\n        nonlocal last_entry_epoch\n        result = fn(current, state, risk_action)\n        if not isinstance(result, dict):\n            return result\n        if not _zel_is_long(result):\n            return result\n        if min_conf is not None:\n            confidence = _zel_find_confidence(result)\n            if confidence is not None and 0.0 <= confidence <= 1.0 and confidence < float(min_conf):\n                return _zel_hold(result, "MIN_CONFIDENCE")\n        if state is None and cooldown_min > 0.0:\n            now_epoch = _zel_current_epoch(current)\n            if now_epoch is not None and last_entry_epoch is not None and now_epoch - last_entry_epoch < cooldown_min * 60.0:\n                return _zel_hold(result, "COOLDOWN")\n        if min_risk_distance_pct > 0.0:\n            geometry = _zel_find_geometry(result)\n            if geometry is not None:\n                entry, sl, _ = geometry\n                if entry is not None and entry > 0 and sl is not None and sl < entry:\n                    risk_pct = (entry - sl) / entry * 100.0\n                    if risk_pct < min_risk_distance_pct:\n                        return _zel_hold(result, "MIN_RISK_DISTANCE")\n        adjusted = _zel_adjust_geometry(result, stop_mult, target_mult)\n        if state is None and _zel_is_long(adjusted):\n            now_epoch = _zel_current_epoch(current)\n            if now_epoch is not None:\n                last_entry_epoch = now_epoch\n        return adjusted\n\n    wrapped.__name__ = getattr(fn, "__name__", "overlay_wrapped_strategy")\n    return wrapped\n\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    restored = _ZEL_BASE_RESTORE(source_root, raw_registry)\n    enabled = set(_ZEL_OVERLAY["parameters"].get("enabled_entry_owners") or [])\n    out = {{}}\n    for logical_id, owner in restored.items():\n        strategy = getattr(owner, "strategy", None)\n        if not callable(strategy):\n            raise RuntimeError(f"OVERLAY_STRATEGY_NOT_CALLABLE:{{logical_id}}")\n        wrapped = _zel_wrap_strategy(strategy) if logical_id in enabled else _zel_disabled_strategy\n        out[logical_id] = _ZelOverlayOwnerProxy(owner, wrapped)\n    return out\n'''


def patch_engine(engine_path: Path, candidate_path: Path, receipt_path: Path) -> dict[str, Any]:
    candidate = load_candidate(candidate_path)
    text = engine_path.read_text()
    if MARKER in text:
        raise RuntimeError("OVERLAY_ALREADY_PATCHED")
    if text.count("def _restore_structural_premium_registry(") != 1:
        raise RuntimeError("RESTORE_HELPER_COUNT_MISMATCH")
    anchor = 'if __name__ == "__main__":'
    if text.count(anchor) != 1:
        raise RuntimeError("MAIN_GUARD_COUNT_MISMATCH")
    max_hold = float(candidate["parameters"]["max_hold_min"])
    hold_anchor = "MAX_HOLD_MIN = 120.0"
    if text.count(hold_anchor) != 1:
        raise RuntimeError("MAX_HOLD_ANCHOR_MISMATCH")
    before_sha = hashlib.sha256(text.encode()).hexdigest()
    text = text.replace(hold_anchor, f"MAX_HOLD_MIN = {max_hold!r}")
    patched = text.replace(anchor, overlay_source(candidate) + "\n\n" + anchor)
    engine_path.write_text(patched)
    py_compile.compile(str(engine_path), doraise=True)
    after_sha = hashlib.sha256(engine_path.read_bytes()).hexdigest()
    receipt = {
        "schema_version": "zel.structural_premium.overlay_patch_receipt.v2",
        "state": "PASS_STRUCTURAL_PREMIUM_OVERLAY_PATCHED",
        "version": VERSION,
        "candidate": candidate,
        "engine_path": str(engine_path),
        "engine_sha256_before": before_sha,
        "engine_sha256_after": after_sha,
        "max_hold_min_patched": max_hold,
        "canonical_source_mutations": 0,
        "isolated_replay_patch_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def self_test() -> None:
    candidate = {
        "schema_version": SCHEMA,
        "candidate_id": "SELFTEST",
        "generation": 0,
        "axis": "SIX_AXIS",
        "closed_loop_axes": ["FREQUENCY", "COST_EXECUTION", "RISK_EXPOSURE", "INTERACTION", "PORTFOLIO", "ROBUSTNESS"],
        "parameters": {
            "stop_distance_mult": 0.9,
            "target_distance_mult": 1.1,
            "min_confidence": 0.55,
            "cooldown_min": 5.0,
            "min_risk_distance_pct": 1.5,
            "max_hold_min": 90.0,
            "enabled_entry_owners": ["vwap_revert", "support_resistance", "trend_rider"],
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = root / "candidate.json"
        c.write_text(json.dumps(candidate))
        e = root / "engine.py"
        e.write_text(
            "import json\n"
            "from types import SimpleNamespace\n"
            "MAX_HOLD_MIN = 120.0\n"
            "def _restore_structural_premium_registry(source_root, raw_registry):\n"
            "    def strategy(current, state=None, risk_action='hold'):\n"
            "        return {'action':'enter_long','entry':100.0,'sl':99.0,'tp':102.0,'confidence':0.8}\n"
            "    return {\n"
            "      'vwap_revert': SimpleNamespace(strategy=strategy, owner_path='x.py', owner_sha256='0'*64),\n"
            "      'support_resistance': SimpleNamespace(strategy=strategy, owner_path='y.py', owner_sha256='1'*64),\n"
            "      'liquidity_sweep': SimpleNamespace(strategy=strategy, owner_path='z.py', owner_sha256='2'*64),\n"
            "      'trend_rider': SimpleNamespace(strategy=strategy, owner_path='w.py', owner_sha256='3'*64),\n"
            "    }\n"
            "if __name__ == \"__main__\":\n    pass\n"
        )
        r = patch_engine(e, c, root / "receipt.json")
        namespace: dict[str, Any] = {"__name__": "overlay_test"}
        exec(compile(e.read_text(), str(e), "exec"), namespace)
        assert abs(namespace["MAX_HOLD_MIN"] - 90.0) < 1e-9
        owners = namespace["_restore_structural_premium_registry"](None, {})
        assert owners["liquidity_sweep"].strategy(None, None, "hold")["action"] == "hold"
        class Frame:
            def __init__(self, ts):
                self.iloc = self
                self.ts = ts
            def __len__(self):
                return 1
            def __getitem__(self, idx):
                return {"timestamp_ms": self.ts}
        out = owners["vwap_revert"].strategy(Frame(1_700_000_000_000), None, "hold")
        assert out["overlay_blocked"] is True and out["overlay_block_reason"] == "MIN_RISK_DISTANCE"
        assert r["state"] == "PASS_STRUCTURAL_PREMIUM_OVERLAY_PATCHED"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-v1", type=Path)
    parser.add_argument("--candidate-json", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.engine_v1, args.candidate_json, args.receipt)):
        parser.error("engine-v1, candidate-json and receipt are required")
    row = patch_engine(args.engine_v1.resolve(), args.candidate_json.resolve(), args.receipt.resolve())
    print(json.dumps({
        "state": row["state"],
        "candidate_id": row["candidate"]["candidate_id"],
        "axis": row["candidate"]["axis"],
        "receipt_sha256": row["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
