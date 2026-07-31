#!/usr/bin/env bash
set -Eeuo pipefail

COLLECTOR_PATH="${1:?collector path required}"
RESULT_PATH="${2:?result path required}"
SOURCE_SHA="${3:-unknown}"

ROOT="/home/z/z"
PRODUCER="${ROOT}/tools/q4r3_exact25_dedicated_shadow_producer.py"
EXPECTED_PRODUCER_BLOB="42cb8d5c92ace00a11531b46548efdc9f872c9b7"
CANONICAL_PRODUCER_UNIT="q4r3-exact25-shadow-producer.service"
CANONICAL_WRITER_UNIT="q4r3-exact25-persistent-single-event-writer.service"
FORMAL_LEDGER="${ROOT}/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"

A_UNIT_NAME="q4r3-exact25-forward-expansion-v1.service"
A_UNIT_PATH="/etc/systemd/system/${A_UNIT_NAME}"
A_ROOT="${ROOT}/runtime/exact25_edge_v1/forward_expansion_v1"
A_SYMBOLS="DOGEUSDT,ADAUSDT,AVAXUSDT,SUIUSDT,LTCUSDT"

B_ROOT="${ROOT}/data/zel_historical_oos_v1"
B_STATUS="${B_ROOT}/workflow_status_latest.json"

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo -n)
fi

tmp_dir="$(mktemp -d /tmp/zel-data-ab-v1.XXXXXX)"
unit_backup="${tmp_dir}/unit.backup"
unit_was_present=0
unit_was_active=0
install_started=0

cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

rollback_a() {
  if [[ "${install_started}" -ne 1 ]]; then
    return
  fi
  "${SUDO[@]}" systemctl stop "${A_UNIT_NAME}" >/dev/null 2>&1 || true
  if [[ "${unit_was_present}" -eq 1 ]]; then
    "${SUDO[@]}" install -m 0644 "${unit_backup}" "${A_UNIT_PATH}"
  else
    "${SUDO[@]}" rm -f "${A_UNIT_PATH}"
  fi
  "${SUDO[@]}" systemctl daemon-reload >/dev/null 2>&1 || true
  if [[ "${unit_was_active}" -eq 1 ]]; then
    "${SUDO[@]}" systemctl start "${A_UNIT_NAME}" >/dev/null 2>&1 || true
  fi
}

fail() {
  local reason="$1"
  rollback_a
  python3 - "${RESULT_PATH}" "${reason}" "${SOURCE_SHA}" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
out,reason,source_sha=sys.argv[1:4]
payload={
    "schema_version":"zel.data_ab_expansion.result.v1",
    "state":"HOLD",
    "verdict":"DATA_AB_EXPANSION_FAILED",
    "reason":reason,
    "source_sha":source_sha,
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "action":"hold",
    "execution_authority":"NONE",
    "order_authority":"BLOCKED",
    "paper_enabled":False,
    "live_enabled":False,
}
Path(out).parent.mkdir(parents=True,exist_ok=True)
Path(out).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY
  exit 1
}

test -d "${ROOT}" || fail "ROOT_MISSING"
test -x "${ROOT}/.venv/bin/python" || fail "VENV_PYTHON_MISSING"
test -f "${PRODUCER}" || fail "PRODUCER_MISSING"
test -f "${COLLECTOR_PATH}" || fail "HISTORICAL_COLLECTOR_MISSING"

actual_blob="$(git -C "${ROOT}" hash-object "${PRODUCER}" 2>/dev/null || true)"
[[ "${actual_blob}" == "${EXPECTED_PRODUCER_BLOB}" ]] || fail "PRODUCER_BLOB_MISMATCH:${actual_blob}"

systemctl is-active --quiet "${CANONICAL_PRODUCER_UNIT}" || fail "CANONICAL_PRODUCER_NOT_ACTIVE"
systemctl is-active --quiet "${CANONICAL_WRITER_UNIT}" || fail "CANONICAL_WRITER_NOT_ACTIVE"

producer_pid_before="$(systemctl show -p MainPID --value "${CANONICAL_PRODUCER_UNIT}")"
writer_pid_before="$(systemctl show -p MainPID --value "${CANONICAL_WRITER_UNIT}")"
[[ "${producer_pid_before}" =~ ^[1-9][0-9]*$ ]] || fail "CANONICAL_PRODUCER_PID_INVALID"
[[ "${writer_pid_before}" =~ ^[1-9][0-9]*$ ]] || fail "CANONICAL_WRITER_PID_INVALID"

if [[ -f "${FORMAL_LEDGER}" ]]; then
  formal_rows_before="$(wc -l < "${FORMAL_LEDGER}")"
else
  formal_rows_before=0
fi
if [[ "${formal_rows_before}" -gt 0 ]]; then
  formal_prefix_sha_before="$(head -n "${formal_rows_before}" "${FORMAL_LEDGER}" | sha256sum | awk '{print $1}')"
else
  formal_prefix_sha_before="$(printf '' | sha256sum | awk '{print $1}')"
fi

Q4R3_SHADOW_ONLY=1 \
Q4R3_PAPER_ENABLED=0 \
Q4R3_LIVE_ENABLED=0 \
Q4R3_ORDER_ENABLED=0 \
Q4R3_HISTORICAL_BACKFILL_ALLOWED=0 \
Q4R3_EPOCH_ID=EXACT25_EDGE_V1 \
Q4R3_PRODUCER_STAGE=FIRST_FORWARD_CANARY \
"${ROOT}/.venv/bin/python" - "${A_SYMBOLS}" <<'PY'
import sys
import ccxt
tokens=sys.argv[1].split(",")
exchange=ccxt.bingx({
    "enableRateLimit":True,
    "timeout":20000,
    "options":{"defaultType":"swap"},
})
if getattr(exchange,"apiKey",None) or getattr(exchange,"secret",None):
    raise SystemExit("PRIVATE_CREDENTIALS_PRESENT")
markets=exchange.load_markets()
missing=[]
resolved={}
for token in tokens:
    compact=token.upper().replace("/","").replace(":","")
    base=compact[:-4]
    candidates=(token,f"{base}/USDT:USDT",f"{base}/USDT")
    found=None
    for candidate in candidates:
        if candidate in markets:
            found=candidate
            break
    if found is None:
        for symbol,market in markets.items():
            market_id=str(market.get("id") or "").upper().replace("-","").replace("_","")
            if market_id==compact and str(market.get("quote") or "").upper()=="USDT":
                found=str(symbol)
                break
    if found is None:
        missing.append(token)
    else:
        resolved[token]=found
if missing:
    raise SystemExit("MISSING_MARKETS:"+",".join(missing))
print("RESOLVED="+",".join(f"{k}:{v}" for k,v in sorted(resolved.items())))
PY

mkdir -p "${A_ROOT}"

if [[ -f "${A_UNIT_PATH}" ]]; then
  unit_was_present=1
  cp -a "${A_UNIT_PATH}" "${unit_backup}"
  grep -q "ZEL_FORWARD_EXPANSION_V1" "${A_UNIT_PATH}" || fail "FOREIGN_A_UNIT_PRESENT"
fi
if systemctl is-active --quiet "${A_UNIT_NAME}"; then
  unit_was_active=1
fi

cat > "${tmp_dir}/${A_UNIT_NAME}" <<EOF
[Unit]
Description=ZEL_FORWARD_EXPANSION_V1 Exact25 Public Forward Shadow Expansion
After=network-online.target ${CANONICAL_PRODUCER_UNIT}
Wants=network-online.target
Requires=${CANONICAL_PRODUCER_UNIT}

[Service]
Type=simple
WorkingDirectory=${ROOT}
Environment=Q4R3_SHADOW_ONLY=1
Environment=Q4R3_PAPER_ENABLED=0
Environment=Q4R3_LIVE_ENABLED=0
Environment=Q4R3_ORDER_ENABLED=0
Environment=Q4R3_HISTORICAL_BACKFILL_ALLOWED=0
Environment=Q4R3_EPOCH_ID=EXACT25_EDGE_V1
Environment=Q4R3_PRODUCER_STAGE=FIRST_FORWARD_CANARY
Environment=ZEL_FORWARD_EXPANSION_LANE=V1
ExecStart=${ROOT}/.venv/bin/python ${PRODUCER} --root ${ROOT} --symbols ${A_SYMBOLS} --timeframe 1m --candle-limit 420 --poll-sec 15 --max-hold-min 120 --risk-unit-usdt 1.0 --fee-rate 0.0005 --slippage-bps 1.0 --state ${A_ROOT}/state.json --status ${A_ROOT}/status_latest.json --open-latest ${A_ROOT}/open_positions_latest.json --close-latest ${A_ROOT}/close_latest.json --ledger ${A_ROOT}/ledger.jsonl
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${A_ROOT}

[Install]
WantedBy=multi-user.target
EOF

install_started=1
"${SUDO[@]}" install -m 0644 "${tmp_dir}/${A_UNIT_NAME}" "${A_UNIT_PATH}"
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable --now "${A_UNIT_NAME}"

a_ready=0
for _ in $(seq 1 30); do
  if systemctl is-active --quiet "${A_UNIT_NAME}" && [[ -s "${A_ROOT}/status_latest.json" ]]; then
    if "${ROOT}/.venv/bin/python" - "${A_ROOT}/status_latest.json" "${A_SYMBOLS}" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
expected=sys.argv[2].split(",")
d=json.loads(p.read_text())
assert d["state"]=="RUNNING",d
assert d["strategy_count"]==25,d
assert d["symbols"]==expected,d
assert d["processed_symbol_count"]==len(expected),d
assert d["private_credentials_used"] is False,d
assert d["paper_enabled"] is False,d
assert d["live_enabled"] is False,d
assert d["order_enabled"] is False,d
assert d["historical_backfill_allowed"] is False,d
assert d["measurement_writer_enabled"] is False,d
assert d["feature_filter_enabled"] is False,d
assert d["write_scope"]=="DEDICATED_SHADOW_CLOSE_SURFACE_ONLY",d
assert not d.get("cycle_errors"),d
PY
    then
      a_ready=1
      break
    fi
  fi
  sleep 5
done
[[ "${a_ready}" -eq 1 ]] || fail "A_EXPANSION_SERVICE_NOT_READY"

mkdir -p "${B_ROOT}"
"${ROOT}/.venv/bin/python" "${COLLECTOR_PATH}" \
  --data-root "${B_ROOT}" \
  --status-out "${B_STATUS}" || fail "B_HISTORICAL_COLLECTION_FAILED"

"${ROOT}/.venv/bin/python" - "${B_ROOT}/manifest.json" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["state"]=="PASS_HISTORICAL_OOS_DATA_READY",d
assert d["total_market_rows"]==302400,d
assert d["window_count"]==6,d
assert d["forward_overlap_count"]==0,d
assert d["forward_ledger_mutated"] is False,d
assert d["formal_ledger_mutated"] is False,d
assert d["historical_data_is_promotion_authority"] is False,d
assert d["promotion_authority"] is False,d
assert d["execution_authority"]=="NONE",d
assert d["order_authority"]=="BLOCKED",d
PY

producer_pid_after="$(systemctl show -p MainPID --value "${CANONICAL_PRODUCER_UNIT}")"
writer_pid_after="$(systemctl show -p MainPID --value "${CANONICAL_WRITER_UNIT}")"
[[ "${producer_pid_after}" == "${producer_pid_before}" ]] || fail "CANONICAL_PRODUCER_PID_CHANGED"
[[ "${writer_pid_after}" == "${writer_pid_before}" ]] || fail "CANONICAL_WRITER_PID_CHANGED"

if [[ -f "${FORMAL_LEDGER}" ]]; then
  formal_rows_after="$(wc -l < "${FORMAL_LEDGER}")"
else
  formal_rows_after=0
fi
[[ "${formal_rows_after}" -ge "${formal_rows_before}" ]] || fail "FORMAL_LEDGER_TRUNCATED"
if [[ "${formal_rows_before}" -gt 0 ]]; then
  formal_prefix_sha_after="$(head -n "${formal_rows_before}" "${FORMAL_LEDGER}" | sha256sum | awk '{print $1}')"
else
  formal_prefix_sha_after="$(printf '' | sha256sum | awk '{print $1}')"
fi
[[ "${formal_prefix_sha_after}" == "${formal_prefix_sha_before}" ]] || fail "FORMAL_LEDGER_PREFIX_CHANGED"

export RESULT_PATH SOURCE_SHA A_ROOT A_SYMBOLS B_ROOT B_STATUS
export producer_pid_before producer_pid_after writer_pid_before writer_pid_after
export formal_rows_before formal_rows_after formal_prefix_sha_before formal_prefix_sha_after
export EXPECTED_PRODUCER_BLOB actual_blob A_UNIT_NAME
"${ROOT}/.venv/bin/python" - <<'PY'
import json,os
from datetime import datetime,timezone
from pathlib import Path

a=json.loads((Path(os.environ["A_ROOT"])/"status_latest.json").read_text())
b=json.loads((Path(os.environ["B_ROOT"])/"manifest.json").read_text())
payload={
    "schema_version":"zel.data_ab_expansion.result.v1",
    "state":"PASS",
    "verdict":"DATA_A_FORWARD_EXPANSION_AND_B_HISTORICAL_OOS_READY",
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "source_sha":os.environ["SOURCE_SHA"],
    "producer_blob_expected":os.environ["EXPECTED_PRODUCER_BLOB"],
    "producer_blob_actual":os.environ["actual_blob"],
    "canonical":{
        "producer_unit":"q4r3-exact25-shadow-producer.service",
        "writer_unit":"q4r3-exact25-persistent-single-event-writer.service",
        "producer_pid_before":int(os.environ["producer_pid_before"]),
        "producer_pid_after":int(os.environ["producer_pid_after"]),
        "writer_pid_before":int(os.environ["writer_pid_before"]),
        "writer_pid_after":int(os.environ["writer_pid_after"]),
        "formal_rows_before":int(os.environ["formal_rows_before"]),
        "formal_rows_after":int(os.environ["formal_rows_after"]),
        "formal_prefix_sha_before":os.environ["formal_prefix_sha_before"],
        "formal_prefix_sha_after":os.environ["formal_prefix_sha_after"],
        "formal_prefix_unchanged":True,
    },
    "data_a":{
        "lane":"FORWARD_SHADOW_EXPANSION_V1",
        "unit":os.environ["A_UNIT_NAME"],
        "service_active":True,
        "symbols":a["symbols"],
        "symbol_count":len(a["symbols"]),
        "strategy_count":a["strategy_count"],
        "parallel_strategy_symbol_lanes":len(a["symbols"])*a["strategy_count"],
        "timeframe":a["timeframe"],
        "processed_symbol_count":a["processed_symbol_count"],
        "cycle_count":a["cycle_count"],
        "signal_count":a["signal_count"],
        "open_event_count":a["open_event_count"],
        "close_event_count":a["close_event_count"],
        "open_position_count":a["open_position_count"],
        "duplicate_close_count":a["duplicate_close_count"],
        "cycle_errors":a["cycle_errors"],
        "measurement_writer_enabled":False,
        "formal_ledger_join_enabled":False,
        "private_credentials_used":False,
        "historical_backfill_allowed":False,
    },
    "data_b":{
        "lane":"HISTORICAL_VALIDATION_OOS_V1",
        "state":b["state"],
        "symbols":b["symbols"],
        "symbol_count":len(b["symbols"]),
        "window_count":b["window_count"],
        "total_market_rows":b["total_market_rows"],
        "forward_overlap_count":b["forward_overlap_count"],
        "final_holdout_accessed":b["final_holdout_accessed"],
        "promotion_authority":b["promotion_authority"],
        "manifest_path":str(Path(os.environ["B_ROOT"])/"manifest.json"),
    },
    "paper_enabled":False,
    "live_enabled":False,
    "execution_authority":"NONE",
    "order_authority":"BLOCKED",
    "action":"hold",
    "rollback_available":True,
}
out=Path(os.environ["RESULT_PATH"])
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY

install_started=0
cat "${RESULT_PATH}"
