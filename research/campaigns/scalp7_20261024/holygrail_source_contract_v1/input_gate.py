"""Offline, fail-closed binding for one owner-supplied immutable source snapshot.

This module never calls a collector or an economic evaluator. Hashes prove bytes,
not that owner attestations about authorization or independent data are true.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
import time

HOUR = 3_600_000
MINUTE = 60_000
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
RULE_SHA256 = "bc44ab07cc7e61e45a23b3044a13bff11bfd0a53f5152cadbc239f3a72729eee"
PINS = {
    "backend/research/rebuild/scalp7_fresh_source_v2.py": "08ef678e679aefdd1235aad3a120d88915b8865446ff099b67a34dcbf5c03691",
    "backend/research/rebuild/scalp7_source_data_v2.py": "7cf2507ad4a23827644d7f58a33512ea6c83590305c5630cce6ff1063ae506e5",
    "backend/research/rebuild/economic7_canonical_history_v1.py": "2605da3467fc2442b8c2eaa9755ed7e89780907dbd7d2aef544bf37a64224203",
}


class GateError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise GateError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _forbidden(value):
    text = str(value).lower()
    require("benchmark_web_holygrail_rearm_v9" not in text, "DENIED_SOURCE_PATH")
    require(not any(x in text for x in ("canonical_12m", "canonical_gapday_prefix", "canonical_postgap_20260213")), "CONSUMED_CORPUS_PATH")


def _no_symlinks(path):
    _forbidden(path)
    for part in (path, *path.parents):
        require(not part.is_symlink(), "SYMLINK_REJECTED")
    return path


def _safe(root, relative):
    require(isinstance(relative, str) and relative, "INVALID_BOUND_PATH")
    _forbidden(relative)
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "PATH_OUTSIDE_SNAPSHOT")
    path = _no_symlinks(root / rel)
    require(path.resolve().is_relative_to(root.resolve()), "PATH_OUTSIDE_SNAPSHOT")
    return path


def _bound(root, relative, expected, inventory):
    require(isinstance(expected, str) and len(expected) == 64, "HOLD_MISSING_NEW_INPUT_BINDING")
    path = _safe(root, relative)
    require(path.is_file(), "BOUND_FILE_MISSING")
    raw = path.read_bytes()
    require(digest(raw) == expected, "BOUND_HASH_MISMATCH:" + relative)
    inventory[relative] = expected
    return raw


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def aggregate_hourly(rows, start_ms, end_ms):
    """Exact fixed range; no sort, deduplication, interpolation, or gap skipping."""
    require(start_ms % HOUR == end_ms % HOUR == 0 and end_ms > start_ms, "INVALID_HOUR_RANGE")
    selected = []
    previous = None
    for row in rows:
        ts = row.get("timestamp_ms")
        require(isinstance(ts, (int, float)) and math.isfinite(ts) and ts == int(ts) and ts % MINUTE == 0, "OFF_GRID_TIMESTAMP")
        require(previous is None or ts > previous, "DUPLICATE_OR_OUT_OF_ORDER")
        previous = ts
        if start_ms <= ts < end_ms:
            selected.append(row)
    require(len(selected) == (end_ms - start_ms) // MINUTE, "MISSING_MINUTES")
    out = []
    previous_availability = None
    for index, row in enumerate(selected):
        require(row["timestamp_ms"] == start_ms + index * MINUTE, "MISSING_MINUTES")
        vals = [row.get(k) for k in ("open", "high", "low", "close", "volume")]
        require(all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals), "NONFINITE_SOURCE")
        o, h, low, c, vol = vals
        require(min(o, h, low, c) > 0 and vol >= 0 and h >= max(o, low, c) and low <= min(o, h, c), "INVALID_OHLC")
        received = row.get("received_at_ms")
        require(isinstance(received, (int, float)) and math.isfinite(received) and received == int(received) and received >= row["timestamp_ms"] + MINUTE, "INVALID_RECEIVED_AT")
        if index % 60 != 59:
            continue
        chunk = selected[index - 59:index + 1]
        opened = int(chunk[0]["timestamp_ms"])
        closed = opened + HOUR
        available = int(max(closed, *(r["received_at_ms"] for r in chunk)))
        require(available <= closed + HOUR, "SOURCE_LATENCY_EXCEEDS_ONE_HOUR")
        require(previous_availability is None or available >= previous_availability, "AVAILABILITY_OUT_OF_ORDER")
        previous_availability = available
        out.append({"timestamp_ms": opened, "open_ts_ms": opened, "close_ts_ms": closed,
                    "available_at_ms": available, "available_ts_ms": available,
                    "open": chunk[0]["open"], "high": max(r["high"] for r in chunk),
                    "low": min(r["low"] for r in chunk), "close": chunk[-1]["close"],
                    "volume": sum(r["volume"] for r in chunk)})
    return out


def _load_pinned(repo_root, snapshot):
    root = _no_symlinks(Path(repo_root).absolute())
    for relative, expected in PINS.items():
        require(digest(_safe(root, relative).read_bytes()) == expected, "SOURCE_CODE_PIN_MISMATCH")
        name = relative[:-3].replace("/", ".")
        loaded = sys.modules.get(name)
        require(loaded is None or Path(loaded.__file__).resolve() == (root / relative).resolve(), "WRONG_IMPORTED_SOURCE_CHECKOUT")
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("backend.research.rebuild.scalp7_fresh_source_v2")
        for relative in PINS:
            loaded = sys.modules.get(relative[:-3].replace("/", "."))
            require(loaded is not None and Path(loaded.__file__).resolve() == (root / relative).resolve(), "WRONG_IMPORTED_SOURCE_CHECKOUT")
        return module.load_observed_minutes(snapshot)
    except GateError:
        raise
    except Exception as exc:
        raise GateError("PINNED_SOURCE_REJECTED:" + type(exc).__name__) from exc
    finally:
        sys.path.remove(str(root))


def preflight(manifest_path, repo_root, expected_manifest_sha256=None):
    manifest_path = _no_symlinks(Path(manifest_path).absolute())
    require(manifest_path.is_file(), "HOLD_MISSING_NEW_INPUT_BINDING")
    raw = manifest_path.read_bytes()
    manifest_sha = digest(raw)
    if expected_manifest_sha256 is not None:
        require(manifest_sha == expected_manifest_sha256, "MANIFEST_HASH_MISMATCH")
    try:
        m = json.loads(raw)
        fields = ("rule_spec_path", "rule_spec_sha256", "snapshot_root", "source_identity_sha256", "source_cursor_sha256", "snapshot_authorization_ref", "independent_data_attestation", "input_freeze", "dev_start_ms", "dev_end_ms", "tick_metadata", "tick_sizes")
        require(all(m.get(k) is not None and m.get(k) != "" for k in fields), "HOLD_MISSING_NEW_INPUT_BINDING")
        require(isinstance(m["snapshot_authorization_ref"], str) and m["snapshot_authorization_ref"].strip(), "HOLD_MISSING_NEW_INPUT_BINDING")
        require(m.get("schema") == "zel.holygrail.input.v1" and m.get("symbols") == list(SYMBOLS) and m.get("timeframe_ms") == HOUR and m.get("warmup_bars") == 240, "INPUT_CONTRACT_DRIFT")
        require(m["rule_spec_path"] == "FROZEN_SPEC.json", "RULE_PATH_DRIFT")
        require(m["rule_spec_sha256"] == RULE_SHA256, "FROZEN_RULE_IDENTITY_MISMATCH")
        spec_bytes = _bound(manifest_path.parent, m["rule_spec_path"], m["rule_spec_sha256"], {})
        spec = json.loads(spec_bytes)
        lo, hi, freeze = m["dev_start_ms"], m["dev_end_ms"], spec["frozen_at_ms"]
        require(all(_integer(v) for v in (lo, hi, freeze)) and lo % HOUR == hi % HOUR == 0 and hi > lo >= freeze, "INVALID_OR_PREFREEZE_DEV_WINDOW")
        require(hi - lo <= 31 * 24 * HOUR, "DEV_WINDOW_EXCEEDS_31_DAY_CAP")
        now_ms = int(time.time() * 1000)
        require(hi <= now_ms, "FUTURE_DATA_WINDOW")
        att, seal = m["independent_data_attestation"], m["input_freeze"]
        require(all(isinstance(att.get(k), str) and att[k].strip() for k in ("ref", "asserted_by")), "HOLD_MISSING_NEW_INPUT_BINDING")
        require(isinstance(seal.get("ref"), str) and seal["ref"].strip() and _integer(seal.get("frozen_at_ms")) and freeze <= seal["frozen_at_ms"] <= lo, "INPUT_FREEZE_NOT_PREDECLARED")
        require(_integer(att.get("asserted_at_ms")) and freeze <= att["asserted_at_ms"] <= lo, "ATTESTATION_NOT_PREDECLARED")
        require(m["cost_model"] == {"roundtrip_bps_1x": 20, "roundtrip_bps_2x": 40, "historical_funding": None, "classification": "MODELLED_ONLY_NO_PROMOTION"}, "COST_CONTRACT_DRIFT")
        ticks = m["tick_sizes"]
        require(set(ticks) == set(SYMBOLS) and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0 for v in ticks.values()), "INVALID_TICK_SIZES")
        root = Path(m["snapshot_root"])
        require(root.is_absolute(), "SNAPSHOT_REQUIRES_ABSOLUTE_PATH")
        root = _no_symlinks(root)
        require(root.is_dir(), "HOLD_MISSING_NEW_INPUT_BINDING")
        inventory = {}
        identity_raw = _bound(root, "IDENTITY.json", m["source_identity_sha256"], inventory)
        cursor_raw = _bound(root, "CURSOR.json", m["source_cursor_sha256"], inventory)
        identity, cursor = json.loads(identity_raw), json.loads(cursor_raw)
        require(identity.get("symbols") == list(SYMBOLS) and set(cursor["symbols"]) == set(SYMBOLS), "SOURCE_SYMBOLS_DRIFT")
        require(cursor["identity_sha256"] == m["source_identity_sha256"], "IDENTITY_CURSOR_MISMATCH")
        for symbol in SYMBOLS:
            require(cursor["symbols"][symbol], "EMPTY_SYMBOL_RECEIPTS")
            for record in cursor["symbols"][symbol]:
                receipt = json.loads(_bound(root, record["path"], record["sha256"], inventory))
                require(receipt.get("symbol") == symbol, "RECEIPT_SYMBOL_MISMATCH")
                _bound(root, receipt["body_path"], receipt["body_sha256"], inventory)
                _bound(root, receipt["normalized_path"], receipt["normalized_sha256"], inventory)
        tick = m["tick_metadata"]
        require(_integer(tick.get("effective_from_ms")) and _integer(tick.get("effective_to_ms")) and tick["effective_from_ms"] <= lo < hi <= tick["effective_to_ms"] and isinstance(tick.get("source_ref"), str) and tick["source_ref"].strip(), "TICK_VALIDITY_MISSING")
        tick_body = json.loads(_bound(root, tick["path"], tick["sha256"], inventory))
        require(tick_body.get("tick_sizes") == ticks and tick_body.get("source_ref") == tick["source_ref"], "TICK_SOURCE_MISMATCH")
        _bound(root, tick_body["original_raw_path"], tick_body["original_raw_sha256"], inventory)
        frames = _load_pinned(repo_root, root)
        require(set(frames) == set(SYMBOLS), "LOADED_SYMBOLS_DRIFT")
        bars = {symbol: aggregate_hourly(frames[symbol].to_dict("records"), lo - 240 * HOUR, hi) for symbol in SYMBOLS}
        require(all(bar["available_at_ms"] <= now_ms for series in bars.values() for bar in series), "FUTURE_RECEIPT_TIMESTAMP")
        for relative, expected in list(inventory.items()):
            _bound(root, relative, expected, {})
        require(manifest_path.read_bytes() == raw, "MANIFEST_CHANGED_DURING_READ")
        require(_safe(manifest_path.parent, m["rule_spec_path"]).read_bytes() == spec_bytes, "RULE_CHANGED_DURING_READ")
        input_sha = digest(json.dumps({"manifest_sha256": manifest_sha, "rule_sha256": m["rule_spec_sha256"], "files": inventory}, sort_keys=True, separators=(",", ":")).encode())
        return {"bars_by_symbol": bars, "manifest_sha256": manifest_sha, "input_sha256": input_sha,
                "dev_start_ms": lo, "dev_end_ms": hi, "warmup_bars": 240, "tick_sizes": ticks,
                "limitations": ["MODELLED_20_40BP_COSTS_NOT_ACTUAL", "HISTORICAL_FUNDING_UNKNOWN", "OWNER_ATTESTATIONS_ASSERTED_NOT_CRYPTOGRAPHIC_NOVELTY", "NO_G5_OOS_OR_LIVE_PROMOTION"], "snapshot_file_hashes": inventory}
    except GateError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise GateError("HOLD_MISSING_NEW_INPUT_BINDING:" + type(exc).__name__) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--input-sha256", required=True, help="Expected SHA256 of immutable manifest bytes")
    args = parser.parse_args()
    try:
        result = preflight(args.manifest, args.repo_root, args.input_sha256)
    except GateError as exc:
        print(json.dumps({"state": "HOLD", "reason": str(exc)}))
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != "bars_by_symbol"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
