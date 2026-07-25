from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.strategy25.indicator_contract_repair_adapter_v1 import (
    IndicatorContractRepairError,
    REPAIR_SPECS,
    repair_manifest,
    transformed_source,
)
from backend.strategy25.indicator_contract_repair_loader_v1 import load_repaired_namespace


ROOT = Path(__file__).resolve().parents[1]


class IndicatorContractRepairAdapterV1Test(unittest.TestCase):
    def test_manifest_is_child_only_and_fail_closed(self) -> None:
        rows = repair_manifest()
        self.assertEqual({row["strategy_id"] for row in rows}, set(REPAIR_SPECS))
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertTrue(row["read_only_child"])
            self.assertFalse(row["canonical_mutated"])
            self.assertFalse(row["execution_allowed"])

    def test_all_repaired_sources_compile(self) -> None:
        for strategy_id in REPAIR_SPECS:
            with self.subTest(strategy_id=strategy_id):
                source = transformed_source(ROOT, strategy_id)
                compile(source, f"<test:{strategy_id}>", "exec")

    def test_reference_windows_exclude_signal_bar(self) -> None:
        bnc = transformed_source(ROOT, "break_and_continue")
        self.assertIn("box = df.iloc[-(cfg.box_bars + 1):-1]", bnc)
        self.assertNotIn("box = df.iloc[-cfg.box_bars:]", bnc)

        session = transformed_source(ROOT, "session_bias")
        self.assertIn("recent = df.iloc[-(cfg.range_lookback + 1):-1]", session)
        self.assertNotIn("recent = df.iloc[-cfg.range_lookback:]", session)

        sr = transformed_source(ROOT, "sr_levels")
        self.assertIn("recent = df.iloc[-(cfg.lookback + 1):-1]", sr)
        self.assertNotIn("recent = df.iloc[-cfg.lookback:]", sr)

    def test_fvg_is_three_candle_and_causal(self) -> None:
        source = transformed_source(ROOT, "fvg_revert")
        self.assertIn('df["high"].iloc[i - 2]', source)
        self.assertIn('df["low"].iloc[i - 2]', source)
        self.assertIn("for i in range(start_idx, len(df) - 1):", source)
        self.assertIn('if gap_dir == "up"', source)
        self.assertNotIn("hi_prev = _to_float(df[\"high\"].iloc[i - 1])", source)

    def test_scalp_snap_requires_real_volume(self) -> None:
        source = transformed_source(ROOT, "scalp_snap")
        self.assertIn('required_cols = {"open", "high", "low", "close", "volume"}', source)
        self.assertNotIn('required_cols = {"open", "high", "low", "close"}\n', source)

    def test_session_overlap_has_precedence_and_off_session_is_not_overlap(self) -> None:
        namespace = load_repaired_namespace(ROOT, "session_bias")
        config = namespace["SessionBiasConfig"]()
        resolver = namespace["_session_name_from_ts"]

        overlap_ts = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc).timestamp()
        off_ts = datetime(2024, 1, 2, 23, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(resolver(overlap_ts, "UTC", config), "overlap")
        self.assertEqual(resolver(off_ts, "UTC", config), "off_session")

    def test_source_sha_guard_fails_closed(self) -> None:
        strategy_id = "sr_levels"
        spec = REPAIR_SPECS[strategy_id]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / spec.implementation_path
            target.parent.mkdir(parents=True, exist_ok=True)
            original = (ROOT / spec.implementation_path).read_bytes()
            target.write_bytes(original + b"\n# mutation\n")
            with self.assertRaises(IndicatorContractRepairError):
                transformed_source(root, strategy_id)

    def test_canonical_sources_are_unchanged(self) -> None:
        for strategy_id, spec in REPAIR_SPECS.items():
            with self.subTest(strategy_id=strategy_id):
                actual = hashlib.sha256((ROOT / spec.implementation_path).read_bytes()).hexdigest()
                self.assertEqual(actual, spec.expected_sha256)


if __name__ == "__main__":
    unittest.main()
