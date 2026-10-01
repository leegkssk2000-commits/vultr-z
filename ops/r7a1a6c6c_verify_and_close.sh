#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
C6B_SHA=6d3782e530c09dae0a7327b76dbd1c762cf2fd1b
C6B_BRANCH=r7a1a6-deployment-parity-command-smoke-v1
C6B_PATH=tools/bootstrap_r7a1a6c6b_writer_count_contract_correction.sh
TEMPLATE="$ROOT/runtime/exact25_edge_v1/display_adapter/templates/telegram_legacy_schema_template.json"
OUT="$ROOT/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"
GUARD=/usr/local/bin/zel_q4r3_exact25_telegram_contract_lock.py
C6B_STATUS="$ROOT/runtime/exact25_edge_v1/r7a1a6c6b_writer_count_contract_correction/status_latest.json"
RECEIPT_DIR="$ROOT/runtime/exact25_edge_v1/r7a1a6c6c_telegram_contract_lock"
RECEIPT="$RECEIPT_DIR/verify_latest.json"

mkdir -p "$RECEIPT_DIR"

[[ -x "$GUARD" ]] || { echo "BLOCKER=GUARD_MISSING_OR_NOT_EXECUTABLE:$GUARD"; exit 2; }
"$GUARD" check-template "$TEMPLATE"
"$GUARD" verify-output "$OUT"

cd "$ROOT"
git fetch origin "$C6B_BRANCH"
git cat-file -e "$C6B_SHA^{commit}"
git show "$C6B_SHA:$C6B_PATH" > /tmp/r7a1a6c6b_pinned_bootstrap.sh
bash -n /tmp/r7a1a6c6b_pinned_bootstrap.sh

set +e
bash /tmp/r7a1a6c6b_pinned_bootstrap.sh "$ROOT" "$C6B_SHA" 180
C6B_RC=$?
set -e

"$GUARD" check-template "$TEMPLATE"
"$GUARD" verify-output "$OUT"

python3 - "$C6B_STATUS" "$RECEIPT" "$C6B_RC" "$TEMPLATE" "$OUT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

status_path, receipt_path, rc_raw, template_path, output_path = sys.argv[1:]
rc = int(rc_raw)
expected = {
    "read_only": True,
    "real_order_enabled": False,
    "live_execution_allowed": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}

def load(path):
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

status = load(status_path)
template = load(template_path)
output = load(output_path)
status_pass = isinstance(status, dict) and status.get("state") == "PASS" and status.get("blocker_count") == 0
contract_pass = all(isinstance(x, dict) and all(x.get(k) == v for k, v in expected.items()) for x in (template, output))
ok = rc == 0 and status_pass and contract_pass
receipt = {
    "result": "PASS_R7A1A6C6C_CLOSED" if ok else "HOLD_R7A1A6C6C_VERIFY_FAILED",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "c6b_rc": rc,
    "c6b_status_pass": status_pass,
    "telegram_contract_pass": contract_pass,
    "expected": expected,
    "c6b_status": status,
    "template_contract": {k: template.get(k) if isinstance(template, dict) else None for k in expected},
    "output_contract": {k: output.get(k) if isinstance(output, dict) else None for k in expected},
    "next_stage": "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE" if ok else "R7.A1A6C6C_DIAGNOSE",
}
p = Path(receipt_path)
p.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if ok else 2)
PY

echo "RESULT=R7A1A6C6C_VERIFY_AND_CLOSE_COMPLETE"
echo "EVIDENCE=$RECEIPT"
