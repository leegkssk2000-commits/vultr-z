from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.production_paper_source_adapter.v1"
INPUT_SCHEMA = "zel.production_paper_input.v1"
DEFAULT_OUTPUT = "/home/zel/apps/zel/ledger/production_paper_input_v1.json"
DEFAULT_ALPHA_AUTHORITY = "/home/zel/apps/zel/ledger/production_alpha_authority_v1.json"

MARKET_DATA_OWNER = {
    "path": "backend/engine/market_data_service.py",
    "blob_sha": "17a0397af95fc5f8a6503a7ed337d19d8a5cbec2",
    "symbol": "MarketDataService/BingXPublicAdapter",
}
RISK_OWNER = {
    "path": "backend/engine/risk_engine.py",
    "blob_sha": "4648fdc1c72500795b893f73ae259d2886753ef3",
    "symbol": "AccountState/Position",
}


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (AttributeError, OSError):
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_authority(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise ValueError("ALPHA_AUTHORITY_MUST_BE_JSON_OBJECT")
    return row


def _authority_is_executable(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("alpha_state") or "").upper() == "SURVIVOR_ACTIVE"
        and row.get("research_only") is False
        and row.get("promotion_authority") is True
        and row.get("execution_allowed") is True
        and row.get("runtime_bound") is True
    )


def build_no_validated_alpha_payload(
    *,
    symbol: str = "BTCUSDT",
    authority_state: str = "ALPHA_AUTHORITY_MISSING",
) -> dict[str, Any]:
    """Build a stable PAPER no-order payload without synthetic market/sizing values."""

    return {
        "schema_version": INPUT_SCHEMA,
        "source_adapter_schema_version": SCHEMA,
        "mode": "PAPER",
        "symbol": symbol,
        "strategy_id": "production.no_validated_alpha",
        "alpha_id": "alpha.none",
        "alpha_state": "NONE",
        "signal": "FLAT",
        "risk_state": "HOLD",
        "market_data_ok": False,
        "cost_model_id": "UNBOUND",
        "source_state": "NO_VALIDATED_ALPHA",
        "authority_state": authority_state,
        "source_owners": {
            "market_data": dict(MARKET_DATA_OWNER),
            "risk_gate": dict(RISK_OWNER),
            "risk_sizing_runtime": "UNBOUND_FAIL_CLOSED",
        },
        "exchange_order_submitted": False,
    }


def build_payload(authority: Mapping[str, Any] | None, *, symbol: str = "BTCUSDT") -> dict[str, Any]:
    if authority is None:
        return build_no_validated_alpha_payload(symbol=symbol, authority_state="ALPHA_AUTHORITY_MISSING")

    if not _authority_is_executable(authority):
        return build_no_validated_alpha_payload(symbol=symbol, authority_state="ALPHA_AUTHORITY_NON_EXECUTABLE")

    # Current master has a canonical BingX market-data owner and a risk state
    # contract, but no single executable risk+sizing producer bound to the
    # production spine. An active alpha must therefore stop here instead of
    # borrowing research fields or inventing price/qty/risk values.
    raise RuntimeError("ACTIVE_ALPHA_DATA_RISK_SIZING_BINDING_REQUIRED")


class CanonicalPaperSourceAdapter:
    def __init__(
        self,
        authority_path: str | Path = DEFAULT_ALPHA_AUTHORITY,
        output_path: str | Path = DEFAULT_OUTPUT,
        *,
        symbol: str = "BTCUSDT",
    ) -> None:
        self.authority_path = Path(authority_path)
        self.output_path = Path(output_path)
        self.symbol = symbol

    def build(self) -> dict[str, Any]:
        return build_payload(_read_authority(self.authority_path), symbol=self.symbol)

    def write(self) -> dict[str, Any]:
        payload = self.build()
        _atomic_json_write(self.output_path, payload)
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL fail-closed PAPER source adapter")
    parser.add_argument("--authority", type=Path, default=Path(os.environ.get("ZEL_PRODUCTION_ALPHA_AUTHORITY_PATH", DEFAULT_ALPHA_AUTHORITY)))
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("ZEL_PRODUCTION_PAPER_INPUT_PATH", DEFAULT_OUTPUT)))
    parser.add_argument("--symbol", default=os.environ.get("ZEL_PRODUCTION_IDLE_SYMBOL", "BTCUSDT"))
    args = parser.parse_args(argv)

    payload = CanonicalPaperSourceAdapter(args.authority, args.output, symbol=args.symbol).write()
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
