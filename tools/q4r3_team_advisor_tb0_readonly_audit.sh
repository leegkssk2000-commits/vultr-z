#!/usr/bin/env bash
set -u
set -o pipefail
export LC_ALL=C

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/tmp/ZEL_TB0_FULL_READONLY_AUDIT_V2_${TS}.txt"
MATCHES="/tmp/ZEL_TB0_MATCHED_FILES_V2_${TS}.txt"

: > "$OUT"
: > "$MATCHES"
exec > >(tee "$OUT") 2>&1

section() {
  printf '\n\n======================================================================\n%s\n======================================================================\n' "$1"
}

redact() {
  sed -E \
    -e 's/((api[_-]?key|secret|token|password|passwd|authorization|bearer|telegram[_-]?bot[_-]?token)[[:space:]]*[=:][[:space:]]*)[^[:space:]";,]+/\1[REDACTED]/Ig' \
    -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._~+\/=-]+/\1[REDACTED]/Ig' \
    -e 's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[REDACTED]@#g'
}

show_json() {
  local f="$1"
  echo "===== JSON: $f ====="
  if [ -f "$f" ]; then
    stat -c 'path=%n | size=%s | mtime=%y | mode=%a | owner=%U:%G' "$f" 2>/dev/null || true
    sha256sum "$f" 2>/dev/null || true
    python3 - "$f" <<'PY'
import json, re, sys
p=sys.argv[1]
secret=re.compile(r"(api[_-]?key|secret|token|password|passwd|authorization|bearer)",re.I)
def clean(v):
    if isinstance(v,dict):
        return {k:("[REDACTED]" if secret.search(str(k)) else clean(x)) for k,x in v.items()}
    if isinstance(v,list):
        return [clean(x) for x in v]
    return v
try:
    with open(p,"r",encoding="utf-8") as fh:
        obj=json.load(fh)
    print(json.dumps(clean(obj),ensure_ascii=False,indent=2,sort_keys=True))
except Exception as e:
    print("JSON_READ_ERROR:",repr(e))
    try:
        raw=open(p,"r",encoding="utf-8",errors="replace").read()[:30000]
        raw=re.sub(r'(?i)((?:api[_-]?key|secret|token|password|passwd|authorization|bearer)\s*[=:]\s*)\S+',r'\1[REDACTED]',raw)
        print(raw)
    except Exception as e2:
        print("RAW_READ_ERROR:",repr(e2))
PY
  else
    echo "MISSING"
  fi
}

section "0. AUDIT ID / HOST / TIME"
echo "audit_id=$TS"
date --iso-8601=seconds 2>/dev/null || date
hostnamectl 2>/dev/null || hostname
uname -a
id
echo "output=$OUT"
echo "matched_files=$MATCHES"

section "1. SAFETY BASELINE"
df -h / /home 2>/dev/null || true
df -i / /home 2>/dev/null || true
free -h 2>/dev/null || true
uptime 2>/dev/null || true
echo
echo "[authority snapshot]"
for f in \
  /home/z/z/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json \
  /home/z/z/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json \
  /home/z/z/runtime/exact25_edge_v1/auto_progress_to_200c/status_latest.json
do
  if [ -f "$f" ]; then
    echo "FILE=$f"
    grep -Ein '"?(paper|live|order|order_authority|execution_authority|action)"?[[:space:]]*:' "$f" 2>/dev/null | redact || true
  fi
done

section "2. CORE UNIT STATE / PID / EXEC"
CORE_UNITS=(
  q4r3-exact25-shadow-producer.service
  q4r3-exact25-persistent-single-event-writer.service
  q4r3-exact25-skill-trigger-lineage-observer.timer
  q4r3-exact25-six-profile-projection-observer.timer
  q4r3-exact25-future-pair-join-observer.timer
  q4r3-exact25-risk-scenario-grid-observer.timer
  q4r3-exact25-method-scoreboard-observer.timer
  q4r3-exact25-pre100-integrity-audit.service
  q4r3-exact25-pre100-integrity-audit.timer
  q4r3-exact25-100c-checkpoint-observer.service
  q4r3-exact25-100c-checkpoint-observer.timer
  q4r3-exact25-auto-progress-to-200c.service
  q4r3-exact25-auto-progress-to-200c.timer
  q4r3-storage-regrowth-guard.service
  q4r3-storage-regrowth-guard.timer
)

for u in "${CORE_UNITS[@]}"; do
  echo "===== UNIT: $u ====="
  systemctl show "$u" \
    -p Id -p Names -p FragmentPath -p UnitFileState -p LoadState \
    -p ActiveState -p SubState -p MainPID -p Result -p ExecMainStatus \
    -p ExecStart -p WorkingDirectory -p User -p Group \
    --no-pager 2>&1 | redact || true
done

echo
echo "[timers]"
systemctl list-timers --all --no-pager 2>/dev/null | \
  grep -Ei 'exact25|q4r3|storage-regrowth|100c|200c|pre100|skill|projection|pair|risk|scoreboard' | redact || true

echo
echo "[core process cmdline]"
for u in q4r3-exact25-shadow-producer.service q4r3-exact25-persistent-single-event-writer.service; do
  pid="$(systemctl show "$u" -p MainPID --value 2>/dev/null || echo 0)"
  echo "unit=$u pid=${pid:-0}"
  if [ "${pid:-0}" != "0" ] && [ -r "/proc/$pid/cmdline" ]; then
    tr '\0' ' ' < "/proc/$pid/cmdline" | redact
    echo
    echo -n "cwd="; readlink -f "/proc/$pid/cwd" 2>/dev/null || true
    echo -n "exe="; readlink -f "/proc/$pid/exe" 2>/dev/null || true
  fi
done

section "3. EXACT25 STATUS CHAIN"
JSON_FILES=(
  /home/z/z/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/checkpoint_100c_observer/violations_latest.json
  /home/z/z/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/pre100_integrity_audit/violations_latest.json
  /home/z/z/runtime/exact25_edge_v1/pre100_integrity_audit/fix_queue_latest.json
  /home/z/z/runtime/exact25_edge_v1/auto_progress_to_200c/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/auto_progress_to_200c/violations_latest.json
  /home/z/z/runtime/q4r3_exact25_auto_progress_to_200c_job_latest.json
  /home/z/z/runtime/q4r3_storage_regrowth_guard/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/skill_trigger_lineage_observer/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/six_profile_projection_observer/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/future_pair_join_observer/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/risk_scenario_grid_observer/status_latest.json
  /home/z/z/runtime/exact25_edge_v1/method_scoreboard_observer/status_latest.json
)
for f in "${JSON_FILES[@]}"; do
  show_json "$f"
done

section "4. FORMAL LEDGER SNAPSHOT"
LEDGER=/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
if [ -f "$LEDGER" ]; then
  stat -c 'path=%n | size=%s | mtime=%y | owner=%U:%G | mode=%a' "$LEDGER" || true
  echo -n "wc_line_count="; wc -l < "$LEDGER"
  echo -n "sha256_current="; sha256sum "$LEDGER" | awk '{print $1}'
  echo "[first 2 rows]"; head -n 2 "$LEDGER" | redact
  echo "[last 5 rows]"; tail -n 5 "$LEDGER" | redact
  python3 - "$LEDGER" <<'PY'
import collections,json,sys
p=sys.argv[1]
rows=[]
bad=[]
with open(p,"r",encoding="utf-8",errors="replace") as f:
    for i,line in enumerate(f,1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            bad.append((i,repr(e),line[:160]))
print("parsed_rows=",len(rows))
print("bad_json_rows=",len(bad))
for x in bad[:20]:
    print("BAD",x)

for k in ("event_id","close_event_id","close_id","trade_id"):
    vals=[str(r.get(k)) for r in rows if r.get(k) not in (None,"")]
    dup=[(v,c) for v,c in collections.Counter(vals).items() if c>1]
    print(f"duplicate_{k}_count=",len(dup))
    if dup[:10]:
        print(f"duplicate_{k}_sample=",dup[:10])

positions=collections.defaultdict(list)
for i,r in enumerate(rows,1):
    pid=r.get("position_id")
    if pid not in (None,""):
        positions[str(pid)].append((i,r.get("row_type"),r.get("close_event_id"),r.get("partial_index")))
multi={k:v for k,v in positions.items() if len(v)>1}
print("multirow_position_id_count=",len(multi))
for k,v in list(multi.items())[:10]:
    print("MULTI_POSITION",k,v)
PY
else
  echo "LEDGER_MISSING"
fi

section "5. GIT / ACTIVE TREE BASELINE"
if git -C /home/z/z -c safe.directory=/home/z/z rev-parse --git-dir >/dev/null 2>&1; then
  git -C /home/z/z -c safe.directory=/home/z/z status --short 2>&1 || true
  echo -n "branch="; git -C /home/z/z -c safe.directory=/home/z/z branch --show-current 2>&1 || true
  echo -n "head="; git -C /home/z/z -c safe.directory=/home/z/z rev-parse HEAD 2>&1 || true
  git -C /home/z/z -c safe.directory=/home/z/z log -8 --oneline --decorate 2>&1 || true
  echo "[worktrees]"
  git -C /home/z/z -c safe.directory=/home/z/z worktree list --porcelain 2>&1 || true
else
  echo "NO_GIT_REPO_AT_/home/z/z"
fi

section "6. TEAM / ADVISOR / ALIMI UNIT INVENTORY"
systemctl list-unit-files --no-pager 2>/dev/null | \
  grep -Ei 'lbot|mbot|obot|sbot|zbot|zico|lico|zlice|alpha|beta|gamma|delta|team|advisor|alimi' | redact || true
echo
systemctl list-units --all --no-pager 2>/dev/null | \
  grep -Ei 'lbot|mbot|obot|sbot|zbot|zico|lico|zlice|alpha|beta|gamma|delta|team|advisor|alimi' | redact || true
echo
echo "[masked]"
systemctl list-unit-files --state=masked --no-pager 2>/dev/null | \
  grep -Ei 'lbot|mbot|obot|sbot|zbot|zico|lico|zlice|team|advisor|alimi|paper-control' | redact || true

section "7. PROCESS / TIMER / CRON / LISTENER EVIDENCE"
ps -eo pid,ppid,user,etimes,%cpu,%mem,cmd --sort=pid 2>/dev/null | \
  grep -Ei 'lbot|mbot|obot|sbot|zbot|zico|lico|zlice|alpha|beta|gamma|delta|team|advisor|alimi|exact25|q4r3' | \
  grep -v grep | redact || true

echo "[listeners filtered by process names]"
ss -ltnup 2>/dev/null | \
  grep -Ei 'python|node|gunicorn|uvicorn|caddy|alimi|zbot|zico|lico|zlice|lbot|mbot|obot|sbot' | redact || true

echo "[root crontab]"
crontab -l 2>/dev/null | redact || echo "NO_ROOT_CRONTAB_OR_DENIED"

echo "[cron metadata]"
find /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.weekly \
  -maxdepth 1 -type f -printf '%p | %s bytes | %TY-%Tm-%Td %TH:%TM:%TS\n' \
  2>/dev/null | sort || true

section "8. STATIC CANONICAL FILE INVENTORY"
TOKENS='LBot|MBot|OBot|SBot|ZBot|ZICO|Zico|LiCo|Lico|Zlice|Alpha|Beta|Gamma|Delta|Team Lane|team_lane|advisor'
STATIC_ROOTS=()
for d in \
  /home/z/z/backend \
  /home/z/z/tools \
  /home/z/z/services \
  /home/z/z/systemd \
  /home/z/z/config \
  /home/z/z/data \
  /home/z/z/skills \
  /home/z/z/frontend \
  /home/z/z/web \
  /home/z/z/alimi \
  /etc/systemd/system
do
  [ -e "$d" ] && STATIC_ROOTS+=("$d")
done

printf 'static_scan_roots=%s\n' "${STATIC_ROOTS[*]:-NONE}"

if command -v rg >/dev/null 2>&1 && [ "${#STATIC_ROOTS[@]}" -gt 0 ]; then
  rg -i -l --hidden \
    --max-filesize 5M \
    -g '!.git/**' -g '!.worktrees/**' \
    -g '!node_modules/**' -g '!vendor/**' -g '!dist/**' -g '!build/**' \
    -g '!**/*backup*/**' -g '!**/*archive*/**' -g '!**/.trash/**' \
    -g '!*.log' -g '!*.jsonl' -g '!*.sqlite*' -g '!*.db' \
    "$TOKENS" "${STATIC_ROOTS[@]}" 2>/dev/null | sort -u > "$MATCHES" || true
else
  echo "RG_UNAVAILABLE_OR_NO_STATIC_ROOTS"
fi

echo -n "matched_file_count="; wc -l < "$MATCHES"
sed -n '1,600p' "$MATCHES"

echo
echo "[metadata + sha, first 600]"
while IFS= read -r f; do
  [ -f "$f" ] || continue
  stat -c 'path=%n | size=%s | mtime=%y | mode=%a | owner=%U:%G' "$f" 2>/dev/null || true
  sha256sum "$f" 2>/dev/null || true
done < <(sed -n '1,600p' "$MATCHES")

section "9. LIMITED RUNTIME NAME INVENTORY"
find /home/z/z/runtime \
  -maxdepth 5 -type f -size -5M \
  \( -iname '*lbot*' -o -iname '*mbot*' -o -iname '*obot*' -o -iname '*sbot*' \
     -o -iname '*zbot*' -o -iname '*zico*' -o -iname '*lico*' -o -iname '*zlice*' \
     -o -iname '*alpha*' -o -iname '*beta*' -o -iname '*gamma*' -o -iname '*delta*' \
     -o -iname '*team*' -o -iname '*advisor*' -o -iname '*alimi*' \) \
  -printf '%p | %s bytes | %TY-%Tm-%Td %TH:%TM:%TS\n' \
  2>/dev/null | sort | sed -n '1,1200p'

section "10. CALLER / CONTRACT / AUTHORITY EVIDENCE"
if command -v rg >/dev/null 2>&1 && [ "${#STATIC_ROOTS[@]}" -gt 0 ]; then
  echo "[definition/import/call/contract lines]"
  rg -n -i --hidden --max-filesize 5M \
    -g '!.git/**' -g '!.worktrees/**' \
    -g '!node_modules/**' -g '!vendor/**' -g '!dist/**' -g '!build/**' \
    -g '!**/*backup*/**' -g '!**/*archive*/**' -g '!**/.trash/**' \
    -g '!*.log' -g '!*.jsonl' -g '!*.sqlite*' -g '!*.db' \
    '(class|def|function|import|from|require|invoke|call|execute|run|handler|registry|owner|contract|heartbeat|freshness|stale|confidence|vote|veto|reason|position_id|strategy_id|method_id|skill_id|team_id).*(LBot|MBot|OBot|SBot|ZBot|ZICO|Zico|LiCo|Lico|Zlice|Alpha|Beta|Gamma|Delta)|(LBot|MBot|OBot|SBot|ZBot|ZICO|Zico|LiCo|Lico|Zlice).*(class|def|function|import|from|require|invoke|call|execute|run|handler|registry|owner|contract|heartbeat|freshness|stale|confidence|vote|veto|reason|position_id|strategy_id|method_id|skill_id|team_id)' \
    "${STATIC_ROOTS[@]}" 2>/dev/null | redact | sed -n '1,1800p' || true

  echo
  echo "[write/order/live/paper authority lines]"
  rg -n -i --hidden --max-filesize 5M \
    -g '!.git/**' -g '!.worktrees/**' \
    -g '!node_modules/**' -g '!vendor/**' -g '!dist/**' -g '!build/**' \
    -g '!**/*backup*/**' -g '!**/*archive*/**' -g '!**/.trash/**' \
    -g '!*.log' -g '!*.jsonl' -g '!*.sqlite*' -g '!*.db' \
    '(LBot|MBot|OBot|SBot|ZBot|ZICO|Zico|LiCo|Lico|Zlice|team|advisor).*(order|place_order|cancel_order|paper|live|writer|ledger|append|write|open\(|unlink|remove|systemctl|subprocess|private_api|api_key)|(order|place_order|cancel_order|paper|live|writer|ledger|append|write|private_api|api_key).*(LBot|MBot|OBot|SBot|ZBot|ZICO|Zico|LiCo|Lico|Zlice|team|advisor)' \
    "${STATIC_ROOTS[@]}" 2>/dev/null | redact | sed -n '1,1800p' || true
fi

section "11. ALIMI SOURCE / CARD BINDING EVIDENCE"
if command -v rg >/dev/null 2>&1 && [ "${#STATIC_ROOTS[@]}" -gt 0 ]; then
  rg -n -i --hidden --max-filesize 5M \
    -g '!.git/**' -g '!.worktrees/**' \
    -g '!node_modules/**' -g '!vendor/**' -g '!dist/**' -g '!build/**' \
    -g '!**/*backup*/**' -g '!**/*archive*/**' -g '!**/.trash/**' \
    -g '!*.log' -g '!*.jsonl' -g '!*.sqlite*' -g '!*.db' \
    '(alimi|summary|recent.*trace|decision.*trace|/pos|/pnl|/view|paper_only|stale.age|source.age|team bots|beta team|unbound|zbot|zico|lico|zlice)' \
    "${STATIC_ROOTS[@]}" 2>/dev/null | redact | sed -n '1,2000p' || true
fi

section "12. KNOWN MASKED UNIT DETAIL"
MASK_UNITS=(
  zel-alimi-paper-control-bridge-w207.service
  zel-alimi-paper-control-bridge-w207.timer
  zel-alimi-zbot-control-advisor-w210.service
  zel-alimi-zbot-control-advisor-w210.timer
)
for u in "${MASK_UNITS[@]}"; do
  echo "===== $u ====="
  systemctl show "$u" \
    -p Id -p LoadState -p UnitFileState -p ActiveState -p SubState \
    -p FragmentPath -p ExecStart -p WorkingDirectory -p Result -p ExecMainStatus \
    --no-pager 2>&1 | redact || true
  systemctl cat "$u" --no-pager 2>&1 | redact | sed -n '1,260p' || true
done

section "13. RECENT JOURNAL — READ ONLY / REDACTED"
for u in \
  q4r3-exact25-shadow-producer.service \
  q4r3-exact25-persistent-single-event-writer.service \
  q4r3-exact25-pre100-integrity-audit.service \
  q4r3-exact25-100c-checkpoint-observer.service \
  q4r3-exact25-auto-progress-to-200c.service \
  q4r3-storage-regrowth-guard.service
do
  echo "===== JOURNAL $u ====="
  journalctl -u "$u" -n 160 --no-pager -o short-iso 2>&1 | redact || true
done

section "14. COMPACT MACHINE SUMMARY"
python3 - <<'PY'
import json, os
paths={
 "checkpoint":"/home/z/z/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json",
 "integrity":"/home/z/z/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json",
 "auto200":"/home/z/z/runtime/exact25_edge_v1/auto_progress_to_200c/status_latest.json",
 "storage":"/home/z/z/runtime/q4r3_storage_regrowth_guard/status_latest.json",
 "trigger":"/home/z/z/runtime/exact25_edge_v1/skill_trigger_lineage_observer/status_latest.json",
 "projection":"/home/z/z/runtime/exact25_edge_v1/six_profile_projection_observer/status_latest.json",
 "pair":"/home/z/z/runtime/exact25_edge_v1/future_pair_join_observer/status_latest.json",
 "risk":"/home/z/z/runtime/exact25_edge_v1/risk_scenario_grid_observer/status_latest.json",
 "scoreboard":"/home/z/z/runtime/exact25_edge_v1/method_scoreboard_observer/status_latest.json",
}
for name,p in paths.items():
    if not os.path.isfile(p):
        print(f"{name}|MISSING")
        continue
    try:
        d=json.load(open(p,encoding="utf-8"))
    except Exception as e:
        print(f"{name}|READ_ERROR|{e!r}")
        continue
    keys=[
      "state","phase","verdict","current_closed_count","remaining_closed_count",
      "remaining_to_100c","remaining_to_200c","violation_count",
      "integrity_gate_locked","auto_continue_enabled","observer_only",
      "paper_enabled","live_enabled","order_enabled","order_authority",
      "execution_authority","profile_count","method_count","scenario_count",
      "skill_triggered_count","skill_blocked_count","exact_pair_count"
    ]
    vals=[f"{k}={d.get(k)}" for k in keys if k in d]
    print(name+"|"+"|".join(vals))
PY

section "15. AUDIT COMPLETION"
echo "READ_ONLY_AUDIT_V2_DONE"
echo "output=$OUT"
echo "matched_files=$MATCHES"
echo
echo "업로드 전 secret/token/password 문자열이 [REDACTED] 처리되었는지 확인하십시오."
echo "다음 단계에서는 어떤 unit도 수정하지 말고 OUT 파일 전체를 업로드하십시오."
