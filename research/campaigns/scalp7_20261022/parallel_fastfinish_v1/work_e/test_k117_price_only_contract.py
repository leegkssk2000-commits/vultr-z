"""Fail closed no-order price-only source eligibility. Not a formal G5 approval."""

import hashlib
import json
import unittest

import importlib

k = importlib.import_module("k117_adapter")


def source_guard():
    c = json.loads(k.PRICE_ONLY_CONTRACT.read_text())
    return {
        "volume_units": "UNKNOWN",
        "price_only_contract_sha256": hashlib.sha256(
            k.PRICE_ONLY_CONTRACT.read_bytes()
        ).hexdigest(),
        "source_schema": c["source_schema"],
        "identity_sha256": c["source_identity_sha256"],
        "native_price_only_six_context_verified": True,
        "no_trade_volume_used": True,
    }


class PriceOnlyNoOrderContract(unittest.TestCase):
    def test_legacy_unknown_volume_still_fails(self):
        with self.assertRaisesRegex(ValueError, "VOLUME_UNIT_UNKNOWN"):
            k.native_price_only_source_guard({"volume_units": "UNKNOWN"})

    def test_exact_price_native_source_passes(self):
        k.native_price_only_source_guard(source_guard())

    def test_tampered_contract_digest_fails(self):
        s = source_guard()
        s["price_only_contract_sha256"] = "a" * 64
        with self.assertRaisesRegex(
            ValueError, "PRICE_ONLY_SOURCE_CONTRACT_NOT_VERIFIED"
        ):
            k.native_price_only_source_guard(s)

    def test_mismatched_source_identity_fails(self):
        s = source_guard()
        s["identity_sha256"] = "b" * 64
        with self.assertRaisesRegex(
            ValueError, "PRICE_ONLY_SOURCE_CONTRACT_NOT_VERIFIED"
        ):
            k.native_price_only_source_guard(s)

    def test_six_context_missing_fails(self):
        s = source_guard()
        s["native_price_only_six_context_verified"] = False
        with self.assertRaisesRegex(
            ValueError, "PRICE_ONLY_SOURCE_CONTRACT_NOT_VERIFIED"
        ):
            k.native_price_only_source_guard(s)

    def test_volume_not_falsified(self):
        s = source_guard()
        s["volume_units"] = "CONTRACT_UNIT_GUESSED"
        with self.assertRaisesRegex(ValueError, "VOLUME_UNIT_UNKNOWN"):
            k.native_price_only_source_guard(s)

    def test_original_verified_units_remain_supported(self):
        k.native_price_only_source_guard({"volume_units": "BASE_ASSET"})
        k.native_price_only_source_guard({"volume_units": "FIXED_CONTRACT"})

    def test_declared_no_volume_usage_required(self):
        s = source_guard()
        s["no_trade_volume_used"] = False
        with self.assertRaisesRegex(
            ValueError, "PRICE_ONLY_SOURCE_CONTRACT_NOT_VERIFIED"
        ):
            k.native_price_only_source_guard(s)

    def test_not_four_context_but_six_with_optional_trading_subset(self):
        c = json.loads(k.PRICE_ONLY_CONTRACT.read_text())
        self.assertEqual(len(c["required_context_symbols"]), 6)
        self.assertEqual(
            c["orderless_action_symbols"],
            ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT"],
        )
        self.assertEqual(
            c["conditional_optional_only_for_signal"], ["DOGE-USDT", "LINK-USDT"]
        )
        self.assertFalse(c["formal_fresh_credit"])

    def test_no_formal_shadow_unlock(self):
        self.assertEqual(k.FORMAL_GATE, "ISSUE1414_PREAUTO_CONTRACT_NOT_VERIFIED")
        with self.assertRaisesRegex(ValueError, "SHADOW_READY_HOLD"):
            k.Adapter(enabled=True, fixture=False, development=False)


if __name__ == "__main__":
    unittest.main()
