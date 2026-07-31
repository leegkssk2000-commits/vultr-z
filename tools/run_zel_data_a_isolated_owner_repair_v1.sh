#!/usr/bin/env bash
set -Eeuo pipefail

RESULT_PATH="${1:?result path required}"
SOURCE_SHA="${2:-unknown}"

ROOT="/home/z/z"
PYTHON="${ROOT}/.venv/bin/python"
CANONICAL_PRODUCER_UNIT="q4r3-exact25-shadow-producer.service"
CANONICAL_WRITER_UNIT="q4r3-exact25-persistent-single-event-writer.service"
FORMAL_LEDGER="${ROOT}/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
MANIFEST="${ROOT}/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
BINDING="${ROOT}/backend/config/q4r3_exact25_shadow_binding_v1.json"
PRODUCER="${ROOT}/tools/q4r3_exact25_dedicated_shadow_producer.py"
EXPECTED_PRODUCER_BLOB="42cb8d5c92ace00a11531b46548efdc9f872c9b7"
RECOVERY_COMMIT="a45d875964abc6b4e6e55425ce4ae3a4931c7e53"
RECOVERY_PATH="backend/strategies/vwap_revert.py"
EXPECTED_VWAP_SHA="52d2a4454311a604edcb9d74596dc65d092c84267e5fc439b794becd5432e338"

UNIT="q4r3-exact25-forward-expansion-v1.service"
UNIT_PATH="/etc/systemd/system/${UNIT}"
SOURCE_BASE="/opt/zel/forward-expansion-v1"
ACTIVE_SOURCE="${SOURCE_BASE}/source"
A_ROOT="${ROOT}/runtime/exact25_edge_v1/forward_expansion_v1"
A_SYMBOLS="DOGEUSDT,ADAUSDT,AVAXUSDT,SUIUSDT,LTCUSDT"

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo -n)
fi

tmp="$(mktemp -d /tmp/zel-data-a-repair-v1.XXXXXX)"
staging="${SOURCE_BASE}/source.staging.$(date -u +%Y%m%dT%H%M%SZ).$$"
source_backup=""
unit_backup="${tmp}/unit.backup"
unit_existed=0
unit_was_active=0
source_swapped=0
unit_changed=0

cleanup() {
  rm -rf "${tmp}"
  if [[ -d "${staging}" ]]; then
    "${SUDO[@]}" rm -rf "${staging}" || true
  fi
}
trap cleanup EXIT

write_hold() {
  local reason="$1"
  "${PYTHON}" - "${RESULT_PATH}" "${reason}" "${SOURCE_SHA}" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
out,reason,source_sha=sys.argv[1:4]
payload={
  "schema_version":"zel.data_a.isolated_owner_repair.result.v1",
  "state":"HOLD",
  "verdict":"DATA_A_ISOLATED_OWNER_REPAIR_FAILED",
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
}

rollback() {
  "${SUDO[@]}" systemctl stop "${UNIT}" >/dev/null 2>&1 || true
  if [[ "${unit_changed}" -eq 1 ]]; then
    if [[ "${unit_existed}" -eq 1 ]]; then
      "${SUDO[@]}" install -m 0644 "${unit_backup}" "${UNIT_PATH}" || true
    else
      "${SUDO[@]}" rm -f "${UNIT_PATH}" || true
    fi
    "${SUDO[@]}" systemctl daemon-reload >/dev/null 2>&1 || true
  fi
  if [[ "${source_swapped}" -eq 1 ]]; then
    "${SUDO[@]}" rm -rf "${ACTIVE_SOURCE}" || true
    if [[ -n "${source_backup}" && -d "${source_backup}" ]]; then
      "${SUDO[@]}" mv "${source_backup}" "${ACTIVE_SOURCE}" || true
    fi
  fi
  if [[ "${unit_was_active}" -eq 1 ]]; then
    "${SUDO[@]}" systemctl start "${UNIT}" >/dev/null 2>&1 || true
  fi
}

fail() {
  local reason="$1"
  rollback
  write_hold "${reason}"
  exit 1
}

test -d "${ROOT}" || { echo ROOT_MISSING >&2; exit 1; }
test -x "${PYTHON}" || { echo PYTHON_MISSING >&2; exit 1; }
test -f "${MANIFEST}" || { echo MANIFEST_MISSING >&2; exit 1; }
test -f "${BINDING}" || { echo BINDING_MISSING >&2; exit 1; }
test -f "${PRODUCER}" || { echo PRODUCER_MISSING >&2; exit 1; }

actual_producer_blob="$(git -C "${ROOT}" hash-object "${PRODUCER}" 2>/dev/null || true)"
[[ "${actual_producer_blob}" == "${EXPECTED_PRODUCER_BLOB}" ]] || fail "PRODUCER_BLOB_MISMATCH:${actual_producer_blob}"
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

"${PYTHON}" - "${MANIFEST}" "${ROOT}" "${RECOVERY_PATH}" "${EXPECTED_VWAP_SHA}" <<'PY'
import hashlib,json,sys
from pathlib import Path
manifest_path,root,recovery_path,expected_recovery=sys.argv[1:5]
root=Path(root)
d=json.loads(Path(manifest_path).read_text())
entries=d.get("strategies") or []
assert len(entries)==25, len(entries)
mismatch=[]
for row in entries:
    path=root/row["owner_path"]
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=row["owner_sha256"]:
        mismatch.append((row["strategy_id"],row["owner_path"],row["owner_sha256"],actual))
assert len(mismatch)==1,mismatch
sid,path,expected,actual=mismatch[0]
assert sid=="vwap_revert",mismatch
assert path==recovery_path,mismatch
assert expected==expected_recovery,mismatch
print(json.dumps({"mismatch":mismatch}))
PY

git -C "${ROOT}" cat-file -e "${RECOVERY_COMMIT}^{commit}" || fail "RECOVERY_COMMIT_MISSING"
git -C "${ROOT}" show "${RECOVERY_COMMIT}:${RECOVERY_PATH}" > "${tmp}/vwap_revert.py" || fail "RECOVERY_SOURCE_READ_FAILED"
recovery_sha="$(sha256sum "${tmp}/vwap_revert.py" | awk '{print $1}')"
[[ "${recovery_sha}" == "${EXPECTED_VWAP_SHA}" ]] || fail "RECOVERY_SOURCE_SHA_MISMATCH:${recovery_sha}"

if [[ -f "${UNIT_PATH}" ]]; then
  unit_existed=1
  cp -a "${UNIT_PATH}" "${unit_backup}"
  grep -q "ZEL_FORWARD_EXPANSION_V1" "${UNIT_PATH}" || fail "FOREIGN_A_UNIT_PRESENT"
fi
if systemctl is-active --quiet "${UNIT}"; then
  unit_was_active=1
fi
"${SUDO[@]}" systemctl stop "${UNIT}" >/dev/null 2>&1 || true

"${SUDO[@]}" mkdir -p "${SOURCE_BASE}" "${A_ROOT}"
"${SUDO[@]}" rm -rf "${staging}"
"${SUDO[@]}" mkdir -p "${staging}"
"${SUDO[@]}" cp -a "${ROOT}/backend" "${staging}/backend"
"${SUDO[@]}" mkdir -p "${staging}/tools"
"${SUDO[@]}" cp -a "${PRODUCER}" "${staging}/tools/q4r3_exact25_dedicated_shadow_producer.py"
"${SUDO[@]}" install -m 0644 "${tmp}/vwap_revert.py" "${staging}/${RECOVERY_PATH}"
"${SUDO[@]}" find "${staging}" -type d -name __pycache__ -prune -exec rm -rf {} + || true

isolated_vwap_sha="$(sha256sum "${staging}/${RECOVERY_PATH}" | awk '{print $1}')"
[[ "${isolated_vwap_sha}" == "${EXPECTED_VWAP_SHA}" ]] || fail "ISOLATED_VWAP_SHA_MISMATCH"
isolated_producer_blob="$(git -C "${ROOT}" hash-object "${staging}/tools/q4r3_exact25_dedicated_shadow_producer.py" 2>/dev/null || true)"
[[ "${isolated_producer_blob}" == "${EXPECTED_PRODUCER_BLOB}" ]] || fail "ISOLATED_PRODUCER_BLOB_MISMATCH:${isolated_producer_blob}"

Q4R3_SHADOW_ONLY=1 \
Q4R3_PAPER_ENABLED=0 \
Q4R3_LIVE_ENABLED=0 \
Q4R3_ORDER_ENABLED=0 \
Q4R3_HISTORICAL_BACKFILL_ALLOWED=0 \
Q4R3_EPOCH_ID=EXACT25_EDGE_V1 \
Q4R3_PRODUCER_STAGE=FIRST_FORWARD_CANARY \
"${PYTHON}" "${staging}/tools/q4r3_exact25_dedicated_shadow_producer.py" \
  --root "${staging}" \
  --symbols DOGEUSDT \
  --timeframe 1m \
  --candle-limit 420 \
  --probe-only \
  --probe-output "${tmp}/probe.json" || fail "ISOLATED_PROBE_FAILED"

"${PYTHON}" - "${tmp}/probe.json" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"]=="PASS",d
assert d["strategy_count"]==25,d
assert d["pass_count"]==25,d
assert d["failure_count"]==0,d
assert d["private_credentials_used"] is False,d
assert d["paper_enabled"] is False,d
assert d["live_enabled"] is False,d
assert d["order_enabled"] is False,d
PY

if [[ -d "${ACTIVE_SOURCE}" ]]; then
  source_backup="${SOURCE_BASE}/source.rollback.$(date -u +%Y%m%dT%H%M%SZ).$$"
  "${SUDO[@]}" mv "${ACTIVE_SOURCE}" "${source_backup}"
fi
"${SUDO[@]}" mv "${staging}" "${ACTIVE_SOURCE}"
source_swapped=1

cat > "${tmp}/${UNIT}" <<EOF_UNIT
[Unit]
Description=ZEL_FORWARD_EXPANSION_V1 Exact25 Isolated Owner-Pinned Public Shadow
After=network-online.target ${CANONICAL_PRODUCER_UNIT}
Wants=network-online.target
Requires=${CANONICAL_PRODUCER_UNIT}

[Service]
Type=simple
WorkingDirectory=${ACTIVE_SOURCE}
Environment=Q4R3_SHADOW_ONLY=1
Environment=Q4R3_PAPER_ENABLED=0
Environment=Q4R3_LIVE_ENABLED=0
Environment=Q4R3_ORDER_ENABLED=0
Environment=Q4R3_HISTORICAL_BACKFILL_ALLOWED=0
Environment=Q4R3_EPOCH_ID=EXACT25_EDGE_V1
Environment=Q4R3_PRODUCER_STAGE=FIRST_FORWARD_CANARY
Environment=ZEL_FORWARD_EXPANSION_LANE=V1
ExecStart=${PYTHON} ${ACTIVE_SOURCE}/tools/q4r3_exact25_dedicated_shadow_producer.py --root ${ACTIVE_SOURCE} --symbols ${A_SYMBOLS} --timeframe 1m --candle-limit 420 --poll-sec 15 --max-hold-min 120 --risk-unit-usdt 1.0 --fee-rate 0.0005 --slippage-bps 1.0 --state ${A_ROOT}/state.json --status ${A_ROOT}/status_latest.json --open-latest ${A_ROOT}/open_positions_latest.json --close-latest ${A_ROOT}/close_latest.json --ledger ${A_ROOT}/ledger.jsonl
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5
TimeoutStopSec=30
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadOnlyPaths=${ACTIVE_SOURCE}
ReadWritePaths=${A_ROOT}

[Install]
WantedBy=multi-user.target
EOF_UNIT

"${SUDO[@]}" install -m 0644 "${tmp}/${UNIT}" "${UNIT_PATH}"
unit_changed=1
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl reset-failed "${UNIT}" >/dev/null 2>&1 || true
"${SUDO[@]}" systemctl enable --now "${UNIT}"

a_ready=0
for _ in $(seq 1 90); do
  if systemctl is-active --quiet "${UNIT}" && [[ -s "${A_ROOT}/status_latest.json" ]]; then
    if "${PYTHON}" - "${A_ROOT}/status_latest.json" "${A_SYMBOLS}" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
expected=sys.argv[2].split(",")
assert d["state"]=="RUNNING",d
assert d["strategy_count"]==25,d
assert d["symbols"]==expected,d
assert d["processed_symbol_count"]==5,d
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
[[ "${a_ready}" -eq 1 ]] || fail "ISOLATED_A_SERVICE_NOT_READY"

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

export RESULT_PATH SOURCE_SHA A_ROOT A_SYMBOLS UNIT ACTIVE_SOURCE source_backup
export producer_pid_before producer_pid_after writer_pid_before writer_pid_after
export formal_rows_before formal_rows_after formal_prefix_sha_before formal_prefix_sha_after
export EXPECTED_PRODUCER_BLOB actual_producer_blob RECOVERY_COMMIT EXPECTED_VWAP_SHA isolated_vwap_sha
"${PYTHON}" - <<'PY'
import json,os
from datetime import datetime,timezone
from pathlib import Path
status=json.loads((Path(os.environ["A_ROOT"])/"status_latest.json").read_text())
payload={
  "schema_version":"zel.data_a.isolated_owner_repair.result.v1",
  "state":"PASS",
  "verdict":"DATA_A_FORWARD_EXPANSION_ISOLATED_OWNER_PINNED_READY",
  "generated_at":datetime.now(timezone.utc).isoformat(),
  "source_sha":os.environ["SOURCE_SHA"],
  "producer_blob_expected":os.environ["EXPECTED_PRODUCER_BLOB"],
  "producer_blob_actual":os.environ["actual_producer_blob"],
  "owner_recovery":{
    "strategy_id":"vwap_revert",
    "recovery_commit":os.environ["RECOVERY_COMMIT"],
    "expected_sha256":os.environ["EXPECTED_VWAP_SHA"],
    "isolated_sha256":os.environ["isolated_vwap_sha"],
    "canonical_working_tree_mutated":False,
    "manifest_mutated":False,
  },
  "canonical":{
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
    "unit":os.environ["UNIT"],
    "isolated_source_root":os.environ["ACTIVE_SOURCE"],
    "service_active":True,
    "symbols":status["symbols"],
    "symbol_count":len(status["symbols"]),
    "strategy_count":status["strategy_count"],
    "parallel_strategy_symbol_lanes":len(status["symbols"])*status["strategy_count"],
    "timeframe":status["timeframe"],
    "processed_symbol_count":status["processed_symbol_count"],
    "cycle_count":status["cycle_count"],
    "signal_count":status["signal_count"],
    "open_event_count":status["open_event_count"],
    "close_event_count":status["close_event_count"],
    "open_position_count":status["open_position_count"],
    "duplicate_close_count":status["duplicate_close_count"],
    "cycle_errors":status["cycle_errors"],
    "measurement_writer_enabled":False,
    "formal_ledger_join_enabled":False,
    "private_credentials_used":False,
    "historical_backfill_allowed":False,
  },
  "paper_enabled":False,
  "live_enabled":False,
  "execution_authority":"NONE",
  "order_authority":"BLOCKED",
  "action":"hold",
  "rollback_available":True,
  "rollback_source":os.environ.get("source_backup") or None,
}
out=Path(os.environ["RESULT_PATH"])
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY

source_swapped=0
unit_changed=0
cat "${RESULT_PATH}"
