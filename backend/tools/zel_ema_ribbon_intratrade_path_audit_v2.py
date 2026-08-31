from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

VERSION = "ZEL_EMA_RIBBON_INTRATRADE_PATH_AUDIT_V2"
SCHEMA = "zel.ema_ribbon_intratrade_path_audit.receipt.v2"
EXPECTED_TERMINAL_TRADES_SHA256 = "62a7d51a02b75ebfee5765d81d955d583d442c995604bb9d4a8a5e7e7a4e2fe3"
EXPECTED_ENGINE_SHA256 = "14fc2600f3ca0dae4bf17e9768461661cf07ef7f1aa5934c317baac95b52fc50"
EXPECTED_TRADES = 424


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-tool",
        type=Path,
        default=Path(__file__).with_name("zel_ema_ribbon_intratrade_path_audit_v1.py"),
    )
    parser.add_argument(
        "--terminal-root",
        type=Path,
        default=Path("/var/lib/zel-research/data-b-1m-v2"),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/opt/zel/historical-oos-v1"),
    )
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    terminal_path = args.terminal_root / "trades.jsonl.gz"
    terminal_sha = file_sha(terminal_path)
    engine_sha = file_sha(args.engine)
    if terminal_sha != EXPECTED_TERMINAL_TRADES_SHA256:
        raise RuntimeError(
            f"TERMINAL_LEDGER_SHA_MISMATCH:{terminal_sha}:{EXPECTED_TERMINAL_TRADES_SHA256}"
        )
    if engine_sha != EXPECTED_ENGINE_SHA256:
        raise RuntimeError(f"ENGINE_SHA_MISMATCH:{engine_sha}:{EXPECTED_ENGINE_SHA256}")

    base = load_module(args.base_tool.resolve(), "zel_ema_intratrade_audit_v1_patched")
    original_path_excursions = base.path_excursions

    def post_entry_path_excursions(side: str, entry_price: float, path_frame: Any):
        # The replay opens at the entry candle close. Excursions therefore begin
        # on the following candle; the entry price itself remains the 0R anchor.
        post_entry = path_frame.iloc[1:].copy()
        if post_entry.empty:
            return None, None
        return original_path_excursions(side, entry_price, post_entry)

    base.path_excursions = post_entry_path_excursions

    old_argv = sys.argv[:]
    buffer = io.StringIO()
    try:
        sys.argv = [
            str(args.base_tool),
            "--terminal-root",
            str(args.terminal_root),
            "--data-root",
            str(args.data_root),
            "--engine",
            str(args.engine),
            "--stdout",
        ]
        with contextlib.redirect_stdout(buffer):
            rc = int(base.main())
    finally:
        sys.argv = old_argv
    if rc != 0:
        raise RuntimeError(f"BASE_AUDIT_FAILED:{rc}")

    receipt = json.loads(buffer.getvalue())
    path = receipt.get("path_audit") or {}
    checks = list(receipt.get("checks") or [])
    checks.extend(
        [
            {
                "name": "terminal_ledger_sha_match",
                "passed": terminal_sha == EXPECTED_TERMINAL_TRADES_SHA256,
                "actual": terminal_sha,
                "expected": EXPECTED_TERMINAL_TRADES_SHA256,
            },
            {
                "name": "engine_sha_match",
                "passed": engine_sha == EXPECTED_ENGINE_SHA256,
                "actual": engine_sha,
                "expected": EXPECTED_ENGINE_SHA256,
            },
            {
                "name": "post_entry_mfe_compare_complete",
                "passed": int(path.get("mfe_compare_count") or 0) == EXPECTED_TRADES,
                "actual": int(path.get("mfe_compare_count") or 0),
                "expected": EXPECTED_TRADES,
            },
            {
                "name": "post_entry_mae_compare_complete",
                "passed": int(path.get("mae_compare_count") or 0) == EXPECTED_TRADES,
                "actual": int(path.get("mae_compare_count") or 0),
                "expected": EXPECTED_TRADES,
            },
            {
                "name": "entry_candle_excluded",
                "passed": True,
                "actual": "entry_index+1",
                "expected": "entry_index+1",
            },
        ]
    )

    blockers = [str(row.get("name")) for row in checks if row.get("passed") is not True]
    replay_ready = not blockers
    path["entry_candle_excluded"] = True
    path["effective_path_start"] = "entry_index+1"
    path["effective_path_end"] = "exit_index_inclusive"
    path["entry_price_anchor_R"] = 0.0
    path["effective_minimum_path_bars"] = (
        max(int(path.get("minimum_path_bars") or 0) - 1, 0)
        if path.get("minimum_path_bars") is not None
        else None
    )

    receipt.update(
        {
            "schema_version": SCHEMA,
            "version": VERSION,
            "state": (
                "PASS_EMA_RIBBON_POST_ENTRY_PATH_READY"
                if replay_ready
                else "HOLD_EMA_RIBBON_POST_ENTRY_PATH_INCOMPLETE"
            ),
            "checks": checks,
            "blockers": blockers,
            "intratrade_replay_ready": replay_ready,
            "path_audit": path,
            "terminal_lineage": {
                "terminal_trades_path": str(terminal_path),
                "terminal_trades_sha256": terminal_sha,
                "expected_terminal_trades_sha256": EXPECTED_TERMINAL_TRADES_SHA256,
                "terminal_trades_sha_match": terminal_sha
                == EXPECTED_TERMINAL_TRADES_SHA256,
                "engine_path": str(args.engine),
                "engine_sha256": engine_sha,
                "expected_engine_sha256": EXPECTED_ENGINE_SHA256,
                "engine_sha_match": engine_sha == EXPECTED_ENGINE_SHA256,
            },
            "path_contract": {
                "entry_fill_timing": "entry_candle_close",
                "entry_anchor": "ledger_entry_price",
                "excursion_start": "next_candle",
                "excursion_end": "exit_candle_inclusive",
                "price_mode": "high_low",
                "risk_mode": "stop_distance:entry_minus_stop:stop_price",
                "same_bar_new_stop_execution_allowed": False,
            },
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
            "next": (
                "RUN_EMA_PATH_SEMANTICS_RECONCILIATION_AND_TRAILING_TOURNAMENT"
                if replay_ready
                else "RESOLVE_SINGLE_POST_ENTRY_PATH_BLOCKER"
            ),
        }
    )
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(
        receipt,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
