from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException

from backend.api.alimi import router as alimi_router
from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger, run_cycle

DEFAULT_LEDGER = "/home/zel/apps/zel/ledger/production_events_v1.sqlite"
DEFAULT_SNAPSHOT = "/home/zel/apps/zel/ledger/production_snapshot_v1.json"


def ledger_path() -> Path:
    return Path(os.environ.get("ZEL_PRODUCTION_LEDGER_PATH", DEFAULT_LEDGER))


def snapshot_path() -> Path:
    return Path(os.environ.get("ZEL_PRODUCTION_SNAPSHOT_PATH", DEFAULT_SNAPSHOT))


def _atomic_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
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


def _read_snapshot() -> Dict[str, Any]:
    path = snapshot_path()
    if not path.exists():
        return {
            "ok": True,
            "state": "NO_PRODUCTION_SNAPSHOT",
            "snapshot": None,
            "exchange_order_submitted": False,
        }
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"PRODUCTION_SNAPSHOT_INVALID:{type(exc).__name__}") from exc
    if not isinstance(row, dict) or "snapshot_sha256" not in row:
        raise HTTPException(status_code=503, detail="PRODUCTION_SNAPSHOT_CONTRACT_INVALID")
    return {"ok": True, "state": "READY", "snapshot": row, "exchange_order_submitted": False}


def create_app() -> FastAPI:
    app = FastAPI(title="ZEL Production Runtime", version="1.0.0")
    app.include_router(alimi_router)

    @app.get("/api/production/health", include_in_schema=False)
    def production_health() -> Dict[str, Any]:
        ledger = ProductionEventLedger(ledger_path())
        snap = _read_snapshot()
        return {
            "ok": True,
            "service": "zel-production-runtime-v1",
            "goal": "COMPLETE_AUTONOMOUS_TRADING_PROGRAM",
            "ledger_event_count": ledger.count(),
            "snapshot_state": snap["state"],
            "live_execution": "BLOCKED",
            "exchange_order_submission": False,
            "no_validated_alpha_behavior": "HOLD_NO_ORDER",
            "ts": time.time(),
        }

    @app.post("/api/production/cycle", include_in_schema=False)
    def production_cycle(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        try:
            ledger = ProductionEventLedger(ledger_path())
            result = run_cycle(payload, ledger)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        canonical = result["snapshot"]["canonical"]
        _atomic_json_write(snapshot_path(), canonical)
        return {
            "ok": True,
            "decision": result["decision"],
            "fill": result["fill"],
            "snapshot": canonical,
            "receipt_sha256": result["receipt_sha256"],
            "exchange_order_submitted": False,
        }

    @app.get("/api/production/snapshot", include_in_schema=False)
    def production_snapshot() -> Dict[str, Any]:
        return _read_snapshot()

    @app.get("/api/alimi/production", include_in_schema=False)
    @app.get("/api/v1/alimi/production", include_in_schema=False)
    def alimi_production_snapshot() -> Dict[str, Any]:
        # ALIMI consumes exactly the canonical persisted production snapshot.
        row = _read_snapshot()
        return {
            "ok": row["ok"],
            "state": row["state"],
            "snapshot": row["snapshot"],
            "snapshot_sha256": None if row["snapshot"] is None else row["snapshot"]["snapshot_sha256"],
            "authority": "read_only",
            "order_mutation": "blocked",
            "exchange_order_submitted": False,
        }

    return app


app = create_app()
