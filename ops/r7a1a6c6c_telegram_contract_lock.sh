#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
UNIT=zel-q4r3-exact25-display-adapter.service
PATH_UNIT=zel-q4r3-exact25-display-adapter.path
TEMPLATE="$ROOT/runtime/exact25_edge_v1/display_adapter/templates/telegram_legacy_schema_template.json"
OUT="$ROOT/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"
GUARD=/usr/local/bin/zel_q4r3_exact25_telegram_contract_lock.py
DROPIN_DIR="/etc/systemd/system/${UNIT}.d"
DROPIN="$DROPIN_DIR/60-r7a1a6c6c-telegram-contract-lock.conf"
STATUS_DIR="$ROOT/runtime/exact25_edge_v1/r7a1a6c6c_telegram_contract_lock"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BK="$STATUS_DIR/backups/$TS"
RECEIPT="$STATUS_DIR/status_latest.json"
COMMITTED=0
PATH_WAS_ACTIVE=0

mkdir -p "$BK" "$STATUS_DIR"

[[ -f "$TEMPLATE" ]] || { echo "BLOCKER=TEMPLATE_MISSING:$TEMPLATE"; exit 2; }
[[ -f "/etc/systemd/system/$UNIT" ]] || { echo "BLOCKER=UNIT_MISSING:$UNIT"; exit 2; }

backup_one() {
  local f="$1" rel
  rel="${f#/}"
  if [[ -e "$f" ]]; then
    mkdir -p "$BK/$(dirname "$rel")"
    cp -a "$f" "$BK/$rel"
    printf '1\t%s\n' "$f" >> "$BK/manifest.tsv"
  else
    printf '0\t%s\n' "$f" >> "$BK/manifest.tsv"
  fi
}

backup_one "$TEMPLATE"
backup_one "$OUT"
backup_one "$GUARD"
backup_one "$DROPIN"

if systemctl is-active --quiet "$PATH_UNIT"; then
  PATH_WAS_ACTIVE=1
  systemctl stop "$PATH_UNIT"
fi

restore_all() {
  set +e
  while IFS=$'\t' read -r existed f; do
    [[ -n "${f:-}" ]] || continue
    local_rel="${f#/}"
    if [[ "$existed" == "1" ]]; then
      mkdir -p "$(dirname "$f")"
      cp -a "$BK/$local_rel" "$f"
    else
      rm -f "$f"
    fi
  done < "$BK/manifest.tsv"
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed "$UNIT" >/dev/null 2>&1 || true
  systemctl start "$UNIT" >/dev/null 2>&1 || true
  if [[ "$PATH_WAS_ACTIVE" -eq 1 ]]; then
    systemctl start "$PATH_UNIT" >/dev/null 2>&1 || true
  fi
  echo "ROLLBACK=COMPLETE backup=$BK"
}

on_err() {
  local rc=$?
  trap - ERR
  if [[ "$COMMITTED" -eq 0 ]]; then
    restore_all
  fi
  echo "RESULT=FAIL_R7A1A6C6C rc=$rc"
  exit "$rc"
}
trap on_err ERR

python3 - "$TEMPLATE" <<'PY'
import json, os, sys, tempfile
from pathlib import Path

p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit("template root must be object")
expected = {
    "read_only": True,
    "real_order_enabled": False,
    "live_execution_allowed": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}
data.update(expected)
fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, p.stat().st_mode & 0o777)
    os.replace(tmp, p)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)
print("TEMPLATE_CONTRACT=INSTALLED")
PY

cat > "$GUARD" <<'PY'
#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from pathlib import Path

EXPECTED = {
    "read_only": True,
    "real_order_enabled": False,
    "live_execution_allowed": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}

def load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("root_not_object")
    return data

def validate(path: Path, data: dict):
    missing = [k for k in EXPECTED if k not in data]
    mismatch = {k: {"actual": data.get(k), "expected": v}
                for k, v in EXPECTED.items() if k in data and data.get(k) != v}
    if missing or mismatch:
        print(json.dumps({
            "ok": False,
            "path": str(path),
            "missing": missing,
            "mismatch": mismatch,
        }, ensure_ascii=False, sort_keys=True))
        return 42
    print(json.dumps({
        "ok": True,
        "path": str(path),
        "contract": EXPECTED,
    }, ensure_ascii=False, sort_keys=True))
    return 0

def atomic_write(path: Path, data: dict):
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

if len(sys.argv) != 3 or sys.argv[1] not in {"check-template", "normalize-output", "verify-output"}:
    print("usage: guard.py check-template|normalize-output|verify-output PATH", file=sys.stderr)
    raise SystemExit(64)

mode = sys.argv[1]
path = Path(sys.argv[2])
if not path.is_file():
    print(json.dumps({"ok": False, "path": str(path), "error": "missing"}))
    raise SystemExit(43)

data = load(path)
if mode == "normalize-output":
    data.update(EXPECTED)
    atomic_write(path, data)
    data = load(path)
raise SystemExit(validate(path, data))
PY
chmod 0755 "$GUARD"

"$GUARD" check-template "$TEMPLATE"
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN" <<EOF
[Service]
ExecStartPre=/usr/bin/python3 $GUARD check-template $TEMPLATE
ExecStartPost=/usr/bin/python3 $GUARD normalize-output $OUT
EOF

systemctl daemon-reload
systemctl reset-failed "$UNIT" || true
systemctl start "$UNIT"
"$GUARD" verify-output "$OUT"
if [[ "$PATH_WAS_ACTIVE" -eq 1 ]]; then
  systemctl start "$PATH_UNIT"
fi
COMMITTED=1

run_exact_marker() {
  local marker="$1" label="$2" candidate="" rc=127
  mapfile -t found < <(
    grep -RIl --binary-files=without-match \
      --include='*.sh' --include='*.py' "$marker" \
      /home/z/z/tools /usr/local/bin /tmp 2>/dev/null \
      | grep -Ev '/backups?/|/runtime/' \
      | grep -vF -- "$0" \
      | sort -u
  )
  if [[ "${#found[@]}" -eq 1 ]]; then
    candidate="${found[0]}"
  elif [[ "${#found[@]}" -gt 1 ]]; then
    candidate="$(ls -1t "${found[@]}" 2>/dev/null | head -n1)"
  fi
  if [[ -z "$candidate" ]]; then
    echo "${label}_RERUN=NOT_FOUND"
    return 127
  fi
  echo "${label}_RERUN_FILE=$candidate"
  set +e
  case "$candidate" in
    *.sh) bash "$candidate" ; rc=$? ;;
    *.py) python3 "$candidate" ; rc=$? ;;
    *) rc=126 ;;
  esac
  set -e
  echo "${label}_RERUN_RC=$rc"
  return "$rc"
}

set +e
run_exact_marker 'R7A1A6C6B_BOOTSTRAP_COMPLETE' C6B_BOOTSTRAP
BOOT_RC=$?
set -e

python3 - "$TEMPLATE" "$OUT" "$GUARD" "$DROPIN" "$RECEIPT" "$BK" "$UNIT" "$PATH_UNIT" "$PATH_WAS_ACTIVE" "$BOOT_RC" <<'PY'
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

template, out, guard, dropin, receipt, backup, unit, path_unit, path_was_active, boot_rc = sys.argv[1:]

def sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

def load(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_read_error": str(e)}

def props():
    cp = subprocess.run(
        ["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "Result"],
        text=True, capture_output=True,
    )
    return dict(line.split("=", 1) for line in cp.stdout.splitlines() if "=" in line)

c6_status = "/home/z/z/runtime/exact25_edge_v1/r7a1a6c6_exact_semantic_stability/status_latest.json"
c6b_status = "/home/z/z/runtime/exact25_edge_v1/r7a1a6c6b_writer_count_contract_correction/status_latest.json"
expected = {
    "read_only": True,
    "real_order_enabled": False,
    "live_execution_allowed": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}
out_data = load(out) or {}
ok = all(out_data.get(k) == v for k, v in expected.items())
data = {
    "result": "PASS_R7A1A6C6C_TELEGRAM_CONTRACT_LOCK" if ok else "FAIL_R7A1A6C6C_OUTPUT_CONTRACT",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "read_only": True,
    "no_telegram_command_sent": True,
    "no_new_timer": True,
    "no_new_service": True,
    "same_unit_postcondition": True,
    "template": template,
    "output": out,
    "unit": unit,
    "backup": backup,
    "expected": expected,
    "output_contract": {k: out_data.get(k) for k in expected},
    "sha256": {
        "template": sha(template),
        "output": sha(out),
        "guard": sha(guard),
        "dropin": sha(dropin),
    },
    "systemd": props(),
    "bootstrap_rerun_rc": int(boot_rc),
    "path_unit": path_unit,
    "path_was_active": bool(int(path_was_active)),
    "c6_status": load(c6_status),
    "c6b_status": load(c6b_status),
}
p = Path(receipt)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if ok else 2)
PY

echo "RESULT=R7A1A6C6C_COMPLETE BOOT_RC=$BOOT_RC"
echo "EVIDENCE=$RECEIPT"
