"""Synthetic loader regression only; never import or invoke the economic runner.

Apply the shipped patch to its byte-pinned fixture in a temporary directory,
compile only run_cached's AST, and replace runner.run with a frame capture.
"""
import ast
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
BEFORE_SHA = "a86934fed27bde13c94cf6bc11cdfca1169b6a024fa0048f2c4b68e4700dfb27"
AFTER_SHA = "dd54d017df362f51e587fa5feaa215bb1bf711430f4e5b7e8cd3bd6fe3efdd57"
PATCH_SHA = "40fd99e17f2565abf33984865ceae4480a9ae83be99ea5539c244cd3fb3c6278"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def cached_function(text, stage):
    tree = ast.parse(text)
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "run_cached"]
    if len(selected) != 1:
        raise AssertionError("one run_cached function required")
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {"S": stage, "json": json, "sha": sha, "io": io}
    exec(compile(module, "guarded_once.py:run_cached-only", "exec"), namespace)
    return namespace["run_cached"]


class ContextOrderRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = (HERE / "guarded_once.before.py").read_bytes()
        cls.patch_bytes = (HERE / "guarded_once.patch").read_bytes()
        if sha(cls.before) != BEFORE_SHA or sha(cls.patch_bytes) != PATCH_SHA:
            raise AssertionError("pinned source or patch bytes changed")
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            (stage / "guarded_once.py").write_bytes(cls.before)
            result = subprocess.run(
                ["patch", "--batch", "--forward", "--fuzz=0", "-p1"],
                input=cls.patch_bytes, cwd=stage, capture_output=True, check=False)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.after = (stage / "guarded_once.py").read_bytes()
        if sha(cls.after) != AFTER_SHA:
            raise AssertionError("patch result differs from pinned loader")
        cls.blobs, cls.records, cls.original, cls.csv_bytes = {}, {}, {}, {}
        n = 17519
        index = np.arange(n)
        for i, symbol in enumerate(SYMBOLS):
            # Non-round decimal values detect accidental float parsing changes.
            close = (index + 0.12345678901234567) / (7.0 + i) + 10.0
            frame = pd.DataFrame({
                "open_ts_ms": 1757894400000 + index * 1800000,
                "close_ts_ms": 1757896200000 + index * 1800000,
                "available_ts_ms": 1757896200000 + index * 1800000,
                "open": close - 0.0123456789012345,
                "high": close + 0.0323456789012345,
                "low": close - 0.0423456789012345,
                "close": close,
                "volume": index / (13.0 + i),
                "segment_id": np.zeros(n, dtype=np.int64),
            })
            raw = frame.to_csv(index=False).encode()
            blob = gzip.compress(raw, mtime=0)
            filename = "INPUT_" + symbol + "_30m.csv.gz"
            cls.blobs[filename] = blob
            cls.csv_bytes[symbol] = raw
            cls.records[symbol] = {"path": filename, "sha256": sha(blob),
                                   "csv_sha256": sha(raw), "rows": n}
            cls.original[symbol] = {"full_csv_sha256": sha(raw)}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        self.base = self.stage / "baseline"
        self.base.mkdir()
        for name, raw in self.blobs.items():
            (self.stage / name).write_bytes(raw)
        self.records_here = copy.deepcopy(self.records)
        self.original_here = copy.deepcopy(self.original)
        self.write_manifest(SYMBOLS)
        self.write_original()

    def write_manifest(self, order, *, sort_keys=False):
        data = {"symbols": {symbol: self.records_here[symbol] for symbol in order}}
        (self.stage / "INPUT_CACHE.json").write_text(json.dumps(data, sort_keys=sort_keys))

    def write_original(self):
        (self.base / "CHRONO_SOURCE_BINDING.json").write_text(json.dumps(self.original_here))

    def capture(self, *, patched=True, symbols=SYMBOLS):
        captured = []
        runner = types.ModuleType("run_handoff")
        runner.BASE = self.base
        runner.previous = types.SimpleNamespace()
        runner.run = lambda: captured.append(runner.previous.full_frames())
        backend = types.ModuleType("backend")
        research = types.ModuleType("backend.research")
        rebuild = types.ModuleType("backend.research.rebuild")
        source = types.ModuleType("backend.research.rebuild.scalp7_source_data_v2")
        source.SYMBOLS = symbols
        backend.research = research
        research.rebuild = rebuild
        rebuild.scalp7_source_data_v2 = source
        modules = {m.__name__: m for m in [runner, backend, research, rebuild, source]}
        function = cached_function((self.after if patched else self.before).decode(), self.stage)
        with patch.dict(sys.modules, modules):
            function()
        self.assertEqual(len(captured), 1)
        return captured[0]

    def test_original_sorted_manifest_order_and_repaired_frozen_order(self):
        self.write_manifest(SYMBOLS, sort_keys=True)
        self.assertEqual(list(self.capture(patched=False)), sorted(SYMBOLS))
        self.assertEqual(list(self.capture()), list(SYMBOLS))

    def test_reversed_and_shuffled_manifests_restore_frozen_order(self):
        for order in [tuple(reversed(SYMBOLS)), SYMBOLS[2:] + SYMBOLS[:2]]:
            with self.subTest(order=order):
                self.write_manifest(order)
                self.assertEqual(list(self.capture()), list(SYMBOLS))

    def test_frozen_order_preserves_every_csv_byte_after_round_trip(self):
        self.write_manifest(tuple(reversed(SYMBOLS)))
        frames = self.capture()
        for symbol, frame in frames.items():
            self.assertEqual(len(frame), 17519)
            self.assertEqual(frame.to_csv(index=False).encode(), self.csv_bytes[symbol])

    def test_missing_symbol_rejected(self):
        self.write_manifest(SYMBOLS[:-1])
        with self.assertRaisesRegex(ValueError, "INPUT_CACHE_SYMBOL_SET_MISMATCH"):
            self.capture()

    def test_extra_symbol_rejected(self):
        self.records_here["UNEXPECTED-USDT"] = copy.deepcopy(self.records_here[SYMBOLS[0]])
        self.write_manifest(SYMBOLS + ("UNEXPECTED-USDT",))
        with self.assertRaisesRegex(ValueError, "INPUT_CACHE_SYMBOL_SET_MISMATCH"):
            self.capture()

    def test_duplicate_json_symbol_rejected_instead_of_silently_overwritten(self):
        pairs = [(symbol, self.records_here[symbol]) for symbol in SYMBOLS]
        pairs.append((SYMBOLS[0], self.records_here[SYMBOLS[0]]))
        raw = '{"symbols":{' + ','.join(json.dumps(k) + ':' + json.dumps(v)
                                         for k, v in pairs) + '}}'
        (self.stage / "INPUT_CACHE.json").write_text(raw)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CACHE_KEY:BTC-USDT"):
            self.capture()

    def test_duplicate_frozen_source_symbol_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SOURCE_SYMBOL"):
            self.capture(symbols=SYMBOLS + (SYMBOLS[0],))

    def test_original_binding_missing_or_extra_symbol_rejected(self):
        for kind in ["missing", "extra"]:
            with self.subTest(kind=kind):
                self.original_here = copy.deepcopy(self.original)
                if kind == "missing":
                    del self.original_here[SYMBOLS[-1]]
                else:
                    self.original_here["UNEXPECTED-USDT"] = {"full_csv_sha256": "0" * 64}
                self.write_original()
                with self.assertRaisesRegex(ValueError, "ORIGINAL_SYMBOL_SET_MISMATCH"):
                    self.capture()

    def test_corrupt_gzip_bytes_rejected_before_parse(self):
        path = self.stage / self.records_here[SYMBOLS[0]]["path"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "INPUT_CACHE_CHANGED"):
            self.capture()

    def test_manifest_csv_hash_drift_rejected(self):
        self.records_here[SYMBOLS[0]]["csv_sha256"] = "0" * 64
        self.write_manifest(SYMBOLS)
        with self.assertRaisesRegex(ValueError, "ORIGINAL_PRICE_PARITY_FAILED"):
            self.capture()

    def test_original_csv_hash_drift_rejected(self):
        self.original_here[SYMBOLS[0]]["full_csv_sha256"] = "0" * 64
        self.write_original()
        with self.assertRaisesRegex(ValueError, "ORIGINAL_PRICE_PARITY_FAILED"):
            self.capture()

    def test_wrong_row_count_rejected_even_if_all_hashes_match(self):
        symbol = SYMBOLS[0]
        raw = b"\n".join(self.csv_bytes[symbol].split(b"\n")[:-2]) + b"\n"
        blob = gzip.compress(raw, mtime=0)
        record = self.records_here[symbol]
        (self.stage / record["path"]).write_bytes(blob)
        record["sha256"] = sha(blob)
        record["csv_sha256"] = sha(raw)
        record["rows"] = 17518
        self.original_here[symbol]["full_csv_sha256"] = sha(raw)
        self.write_manifest(SYMBOLS)
        self.write_original()
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_FULL_PREFIX"):
            self.capture()

    def test_only_run_cached_ast_changes_and_all_prior_checks_remain(self):
        def outside_cached(raw):
            tree = ast.parse(raw)
            tree.body = [n for n in tree.body if not
                         (isinstance(n, ast.FunctionDef) and n.name == "run_cached")]
            return ast.dump(tree, include_attributes=False)
        self.assertEqual(outside_cached(self.before), outside_cached(self.after))
        for marker in [b"INPUT_CACHE_CHANGED", b"ORIGINAL_PRICE_PARITY_FAILED",
                       b"INCOMPLETE_FULL_PREFIX", b"float_precision='round_trip'",
                       b"runner.run()"]:
            self.assertEqual(self.before.count(marker), self.after.count(marker))
        self.assertNotIn(b"168044bf", self.patch_bytes)
        self.assertNotIn(b"CONTEXT_FIT_CHANGED", self.patch_bytes)
        self.assertEqual(self.patch_bytes.count(b"--- a/"), 1)
        self.assertTrue(self.patch_bytes.startswith(b"--- a/guarded_once.py\n+++ b/guarded_once.py\n"))


if __name__ == "__main__":
    unittest.main()
