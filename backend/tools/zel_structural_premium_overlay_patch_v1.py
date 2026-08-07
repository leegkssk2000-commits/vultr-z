from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import tempfile
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH_V1"
SCHEMA = "zel.structural_premium.overlay.v1"
MARKER = "# ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH_V1"


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
    if not 0.70 <= stop <= 1.25:
        raise RuntimeError(f"STOP_MULT_RANGE:{stop}")
    if not 0.80 <= target <= 1.50:
        raise RuntimeError(f"TARGET_MULT_RANGE:{target}")
    if confidence is not None and not 0.0 <= confidence <= 0.90:
        raise RuntimeError(f"CONFIDENCE_RANGE:{confidence}")
    normalized = {
        "schema_version": SCHEMA,
        "candidate_id": str(row.get("candidate_id") or "UNKNOWN"),
        "generation": int(row.get("generation") or 0),
        "axis": str(row.get("axis") or "BASELINE"),
        "parameters": {
            "stop_distance_mult": stop,
            "target_distance_mult": target,
            "min_confidence": confidence,
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
    return f'''\n{MARKER}\n_ZEL_OVERLAY = json.loads({encoded!r})\n_ZEL_BASE_RESTORE = _restore_structural_premium_registry\n\nclass _ZelOverlayOwnerProxy:\n    def __init__(self, base, strategy):\n        self._base = base\n        self.strategy = strategy\n        self.owner_path = getattr(base, "owner_path", "")\n        self.owner_sha256 = getattr(base, "owner_sha256", "")\n    def __getattr__(self, name):\n        return getattr(self._base, name)\n\ndef _zel_float(value):\n    try:\n        value = float(value)\n        return value if value == value and abs(value) != float("inf") else None\n    except Exception:\n        return None\n\ndef _zel_find_confidence(node):\n    if not isinstance(node, dict):\n        return None\n    for key in ("confidence", "score", "strength", "signal_score"):\n        value = _zel_float(node.get(key))\n        if value is not None:\n            return value\n    for key in ("result", "signal", "setup", "trade", "order"):\n        value = _zel_find_confidence(node.get(key))\n        if value is not None:\n            return value\n    return None\n\ndef _zel_is_long(node):\n    if not isinstance(node, dict):\n        return False\n    values = []\n    for key in ("action", "signal", "side", "direction"):\n        value = node.get(key)\n        if isinstance(value, str):\n            values.append(value.strip().lower())\n    return any(value in {{"long", "buy", "bull", "enter_long", "open_long"}} for value in values)\n\ndef _zel_hold(node):\n    if not isinstance(node, dict):\n        return node\n    out = dict(node)\n    for key in ("action", "signal"):\n        value = out.get(key)\n        if isinstance(value, str) and value.strip().lower() in {{"long", "buy", "bull", "enter_long", "open_long"}}:\n            out[key] = "hold"\n            out["overlay_blocked"] = True\n            return out\n    return out\n\ndef _zel_adjust_geometry(node, stop_mult, target_mult):\n    if not isinstance(node, dict):\n        return node\n    out = dict(node)\n    entry_key = next((key for key in ("entry", "entry_price", "price") if _zel_float(out.get(key)) is not None), None)\n    sl_key = next((key for key in ("sl", "stop", "stop_loss", "stop_price") if _zel_float(out.get(key)) is not None), None)\n    tp_key = next((key for key in ("tp", "target", "take_profit", "tp_price") if _zel_float(out.get(key)) is not None), None)\n    if entry_key is not None:\n        entry = _zel_float(out.get(entry_key))\n        if sl_key is not None:\n            sl = _zel_float(out.get(sl_key))\n            if sl is not None and sl < entry:\n                out[sl_key] = entry - (entry - sl) * stop_mult\n                out["overlay_stop_distance_mult"] = stop_mult\n        if tp_key is not None:\n            tp = _zel_float(out.get(tp_key))\n            if tp is not None and tp > entry:\n                out[tp_key] = entry + (tp - entry) * target_mult\n                out["overlay_target_distance_mult"] = target_mult\n    for key in ("result", "signal", "setup", "trade", "order"):\n        if isinstance(out.get(key), dict):\n            out[key] = _zel_adjust_geometry(out[key], stop_mult, target_mult)\n    return out\n\ndef _zel_wrap_strategy(fn):\n    params = _ZEL_OVERLAY["parameters"]\n    stop_mult = float(params.get("stop_distance_mult", 1.0))\n    target_mult = float(params.get("target_distance_mult", 1.0))\n    min_conf = params.get("min_confidence")\n    def wrapped(current, state=None, risk_action="hold"):\n        result = fn(current, state, risk_action)\n        if not isinstance(result, dict):\n            return result\n        if min_conf is not None and _zel_is_long(result):\n            confidence = _zel_find_confidence(result)\n            if confidence is not None and 0.0 <= confidence <= 1.0 and confidence < float(min_conf):\n                return _zel_hold(result)\n        if _zel_is_long(result):\n            return _zel_adjust_geometry(result, stop_mult, target_mult)\n        return result\n    wrapped.__name__ = getattr(fn, "__name__", "overlay_wrapped_strategy")\n    return wrapped\n\ndef _restore_structural_premium_registry(source_root, raw_registry):\n    restored = _ZEL_BASE_RESTORE(source_root, raw_registry)\n    out = {{}}\n    for logical_id, owner in restored.items():\n        strategy = getattr(owner, "strategy", None)\n        if not callable(strategy):\n            raise RuntimeError(f"OVERLAY_STRATEGY_NOT_CALLABLE:{{logical_id}}")\n        out[logical_id] = _ZelOverlayOwnerProxy(owner, _zel_wrap_strategy(strategy))\n    return out\n'''


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
    before_sha = hashlib.sha256(text.encode()).hexdigest()
    patched = text.replace(anchor, overlay_source(candidate) + "\n\n" + anchor)
    engine_path.write_text(patched)
    py_compile.compile(str(engine_path), doraise=True)
    after_sha = hashlib.sha256(engine_path.read_bytes()).hexdigest()
    receipt = {
        "schema_version": "zel.structural_premium.overlay_patch_receipt.v1",
        "state": "PASS_STRUCTURAL_PREMIUM_OVERLAY_PATCHED",
        "version": VERSION,
        "candidate": candidate,
        "engine_path": str(engine_path),
        "engine_sha256_before": before_sha,
        "engine_sha256_after": after_sha,
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
        "axis": "RR",
        "parameters": {"stop_distance_mult": 0.9, "target_distance_mult": 1.1, "min_confidence": 0.55},
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = root / "candidate.json"
        c.write_text(json.dumps(candidate))
        e = root / "engine.py"
        e.write_text(
            "import json\n"
            "from types import SimpleNamespace\n"
            "def _restore_structural_premium_registry(source_root, raw_registry):\n"
            "    def strategy(current, state=None, risk_action='hold'):\n"
            "        return {'action':'enter_long','entry':100.0,'sl':99.0,'tp':102.0,'confidence':0.8}\n"
            "    return {'x': SimpleNamespace(strategy=strategy, owner_path='x.py', owner_sha256='0'*64)}\n"
            "if __name__ == \"__main__\":\n    pass\n"
        )
        r = patch_engine(e, c, root / "receipt.json")
        namespace: dict[str, Any] = {"__name__": "overlay_test"}
        exec(compile(e.read_text(), str(e), "exec"), namespace)
        owner = namespace["_restore_structural_premium_registry"](None, {})["x"]
        out = owner.strategy(None, None, "hold")
        assert abs(out["sl"] - 99.1) < 1e-9 and abs(out["tp"] - 102.2) < 1e-9
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
        self_test(); return 0
    if not all((args.engine_v1, args.candidate_json, args.receipt)):
        parser.error("engine-v1, candidate-json and receipt are required")
    row = patch_engine(args.engine_v1.resolve(), args.candidate_json.resolve(), args.receipt.resolve())
    print(json.dumps({"state": row["state"], "candidate_id": row["candidate"]["candidate_id"], "receipt_sha256": row["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
