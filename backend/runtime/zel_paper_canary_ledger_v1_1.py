from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from backend.contracts.zel_paper_canary_v1 import canonical_json, canonical_sha, normalize_day
from backend.runtime.zel_paper_canary_ledger_v1 import GENESIS_SHA, PaperCanaryLedger, _fail


class PaperCanaryLedgerV1_1(PaperCanaryLedger):
    def append_day(self, value: dict[str, Any], *, now_ms: int) -> dict[str, Any]:
        day = normalize_day(value, now_ms=now_ms)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT day_json FROM paper_days WHERE canary_id=? AND berlin_date=?",
                (day["canary_id"], day["berlin_date"]),
            ).fetchone()
            if prior is not None:
                existing = json.loads(prior["day_json"])
                if existing["day"]["day_payload_sha256"] != day["day_payload_sha256"]:
                    _fail("DAY_IDEMPOTENCY_CONFLICT", day["berlin_date"])
                connection.commit()
                existing["replayed"] = True
                return existing
            tail = connection.execute(
                "SELECT berlin_date,sequence_no,day_sha256 FROM paper_days WHERE canary_id=? ORDER BY sequence_no DESC LIMIT 1",
                (day["canary_id"],),
            ).fetchone()
            if tail is None:
                sequence = 0
                previous = GENESIS_SHA
            else:
                expected_date = date.fromisoformat(tail["berlin_date"]) + timedelta(days=1)
                if day["berlin_date"] != expected_date.isoformat():
                    _fail("PAPER_DAY_NOT_CONSECUTIVE", f"{tail['berlin_date']}->{day['berlin_date']}")
                sequence = int(tail["sequence_no"]) + 1
                previous = tail["day_sha256"]
            envelope = {
                "schema_version": "zel.paper_canary.ledger.v1.1",
                "sequence_no": sequence,
                "previous_day_sha256": previous,
                "day": day,
            }
            day_sha = canonical_sha(envelope)
            envelope["day_sha256"] = day_sha
            connection.execute(
                "INSERT INTO paper_days(canary_id,berlin_date,sequence_no,previous_day_sha256,day_sha256,day_json) VALUES(?,?,?,?,?,?)",
                (day["canary_id"], day["berlin_date"], sequence, previous, day_sha, canonical_json(envelope)),
            )
            connection.commit()
            envelope["replayed"] = False
            return envelope
