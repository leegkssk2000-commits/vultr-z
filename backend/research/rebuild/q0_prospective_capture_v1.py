"""Observe the existing Clean Runner requests without changing its result.

The original source adapter and binding implementation remain sealed.  This
wrapper copies the already received JSON rows for a separate research consumer;
it does not perform a second request or add Q0 to the operational strategy set.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from . import g5_clean_runner_binding_fix_v1 as binding
from . import g5_clean_runner_v1 as base

SCHEMA = "zel.q0.prospective.source_batch.v1"
SOURCE_OWNER = "G5_CLEAN_RUNNER_OWNER_V1"
# The last canonical historical bar CLOSE, not its open.  The next bar opens
# at this timestamp.  Its original values must come from this same source run.
CANONICAL_SEED_END_MS = 1788609600000  # 2026-09-05 12:00 UTC
BATCH_NAME = "q0_prospective_source_batch_v1.json"


class Capture:
    """Research-only observations, with failure isolated from source operation."""

    def __init__(self, environ: Mapping[str, str] | None = None):
        env = os.environ if environ is None else environ
        self.identity = {
            "source_owner": env.get("G5_CLEAN_RUNNER_OWNER_ID", ""),
            "run_id": env.get("GITHUB_RUN_ID", ""),
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
            "source_commit": env.get("GITHUB_SHA", ""),
        }
        self.records: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.scheduler_fire_ts: int | None = None
        if self.identity["source_owner"] != SOURCE_OWNER:
            self.error("SOURCE_OWNER_UNBOUND")
        if not all(self.identity[name] for name in ("run_id", "run_attempt", "source_commit")):
            self.error("SOURCE_RUN_UNBOUND")

    def error(self, code: str, **context: Any) -> None:
        self.errors.append({"code": code, **context})

    def fetched(self, source: Mapping[str, Any], scheduler_fire_ts: int,
                pages: list[dict[str, Any]], decoder: Any) -> None:
        symbol = str(source["symbol"])
        fire = int(scheduler_fire_ts)
        latest_complete_close = (fire // base.INTERVAL_MS) * base.INTERVAL_MS
        if self.scheduler_fire_ts not in (None, fire):
            self.error("SCHEDULER_FIRE_CONFLICT", symbol=symbol)
        self.scheduler_fire_ts = fire
        originals: dict[tuple[int, str], dict[str, Any]] = {}
        for page_index, page in enumerate(pages):
            value = page["value"]
            raw_rows = value.get("data", []) if isinstance(value, dict) else value
            if not isinstance(raw_rows, list):
                self.error("SOURCE_RAW_ROWS_NOT_LIST", symbol=symbol, page_index=page_index)
                continue
            for raw_index, raw in enumerate(raw_rows):
                decoded = decoder({"data": [raw]})
                # The sealed decoder deliberately skips malformed rows.  A
                # research capture must disclose this instead of claiming full
                # raw/normalized parity for a silently incomplete response.
                if len(decoded) != 1:
                    self.error("SOURCE_RAW_ROW_DECODE_SKIPPED", symbol=symbol,
                               page_index=page_index, raw_index=raw_index)
                    continue
                row = decoded[0]
                close = int(row["bar_close_ts"])
                if close <= CANONICAL_SEED_END_MS or close > fire:
                    continue  # Never persist forming prices or replace seed.
                has_volume = (
                    any(raw.get(name) not in (None, "") for name in ("volume", "vol"))
                    if isinstance(raw, Mapping)
                    else isinstance(raw, (list, tuple)) and len(raw) > 5 and raw[5] not in (None, "")
                )
                if not has_volume:
                    self.error("SOURCE_RAW_VOLUME_MISSING", symbol=symbol,
                               page_index=page_index, raw_index=raw_index)
                    continue
                if close > int(page["received_ms"]):
                    self.error("SOURCE_RECEIVED_BEFORE_CLOSE", symbol=symbol,
                               bar_close_ts=close, page_index=page_index)
                    continue
                key = (int(row["bar_open_ts"]), base.sha_json(row))
                prior = originals.get(key)
                observed = {
                    "raw": copy.deepcopy(raw),
                    "raw_row_sha256": base.sha_json(raw),
                    "observed_at_ms": int(page["received_ms"]),
                    "source_received_ts": int(page["received_ms"]),
                    "source_request_params": dict(page["params"]),
                    "page_index": page_index,
                }
                if prior is None or observed["observed_at_ms"] < prior["observed_at_ms"]:
                    originals[key] = observed
        for row in source["closed_rows"]:
            close = int(row["bar_close_ts"])
            if close <= CANONICAL_SEED_END_MS:
                continue
            if close > fire:
                self.error("SOURCE_CLOSED_ROW_IS_FUTURE", symbol=symbol, bar_close_ts=close)
                continue
            key = (int(row["bar_open_ts"]), base.sha_json(row))
            original = originals.get(key)
            if original is None:
                self.error("SOURCE_RAW_NORMALIZED_PARITY_MISSING", symbol=symbol,
                           bar_open_ts=key[0])
                continue
            self.records.append({
                **self.identity, **original,
                "symbol": symbol, "bar": copy.deepcopy(row),
                "bar_open_ts": int(row["bar_open_ts"]), "bar_close_ts": close,
                "source_bar_sha256": key[1],
                "source_id": source["source_id"], "stream_id": source["stream_id"],
                "scheduler_fire_ts": fire,
                # Historical rows arriving together after downtime must be
                # disclosed even if no earlier invocation recorded the gap.
                # Archive dedup keeps the FIRST accepted record and does not
                # relabel a normally observed bar on a later recapture.
                "backfill": close < latest_complete_close,
            })

    def packet(self, original_exit_code: int) -> dict[str, Any]:
        value = {
            "schema_version": SCHEMA, **self.identity,
            "scope": "Q0_RESEARCH_SOURCE_CAPTURE_ONLY",
            "formal_credit": 0, "execution": "NONE", "order": "BLOCKED", "live": "BLOCKED",
            "additional_source_requests": 0, "paid_ai_calls": 0,
            "canonical_seed_end_ms": CANONICAL_SEED_END_MS,
            "scheduler_fire_ts": self.scheduler_fire_ts,
            "generated_at_ms": base.now_ms(),
            "original_shadow_exit_code": original_exit_code,
            "records": sorted(self.records, key=lambda r: (r["bar_close_ts"], r["symbol"])),
            "errors": list(self.errors),
            "raw_representation": "ORIGINAL_PARSED_JSON_ROW_NOT_HTTP_RESPONSE_BYTES",
            "backfill_rule": "BAR_CLOSE_BEFORE_FLOOR_SCHEDULER_FIRE_4H",
        }
        value["receipt_sha256"] = base.sha_json(value)
        return value


def recording_adapter(original: type, capture: Capture) -> type:
    """Build a scoped subclass of the exact adapter used by the original run."""
    class RecordingAdapter(original):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._q0_pages: list[dict[str, Any]] = []

        def _request(self, params: Mapping[str, Any]) -> tuple[Any, int]:
            answer = super()._request(params)
            try:
                self._q0_pages.append({
                    "params": dict(params), "value": copy.deepcopy(answer[0]),
                    "received_ms": int(answer[1]),
                })
            except Exception as error:
                capture.error("SOURCE_CAPTURE_REQUEST_COPY_FAILED", error_type=type(error).__name__)
            return answer  # Same object, request count, and timestamp.

        def fetch(self, symbol: str, scheduler_fire_ts: int) -> dict[str, Any]:
            self._q0_pages = []
            source = super().fetch(symbol, scheduler_fire_ts)
            try:
                capture.fetched(source, scheduler_fire_ts, self._q0_pages, original._decode)
            except Exception as error:
                capture.error("SOURCE_CAPTURE_NORMALIZATION_FAILED", symbol=symbol,
                              error_type=type(error).__name__)
            return source  # Operational callers see the exact original object.

    return RecordingAdapter


def write_packet(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    if "--shadow" not in sys.argv[1:]:
        return binding.main()
    capture = Capture()
    original = base.BingxSourceAdapter
    base.BingxSourceAdapter = recording_adapter(original, capture)
    try:
        result = binding.main()  # Exactly the original CLI, once.
    finally:
        base.BingxSourceAdapter = original
    if result == 0:
        try:
            path = binding._artifact_dir_from_argv(sys.argv[1:]) / BATCH_NAME
            write_packet(path, capture.packet(result))
        except Exception as error:
            # Do not discard successful operational persistence for a research
            # failure.  The later consumer treats a missing batch as failure.
            print(json.dumps({"scope": "Q0_RESEARCH_SOURCE_CAPTURE_ONLY",
                              "error": "SOURCE_CAPTURE_WRITE_FAILED",
                              "error_type": type(error).__name__}), file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
