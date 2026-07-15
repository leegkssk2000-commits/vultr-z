#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
SHA="${Q4R3_R05_SHA:?Q4R3_R05_SHA_REQUIRED}"
BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r05-canonical-team-package-v1}"
WT="/tmp/q4r3_team_advisor_r05_${SHA:0:12}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PREFIX="$(mktemp /tmp/q4r3_r05_ledger.XXXXXX)"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r05_canonical_team_package/status_latest.json"

cleanup() {
  local code="$?"
  rm -f "$PREFIX"
  if [[ "$code" -eq 0 ]]; then
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  else
    echo "WORKTREE_PRESERVED_FOR_DIAGNOSIS=$WT"
  fi
}
trap cleanup EXIT

cp --reflink=auto "$LEDGER" "$PREFIX"
SIZE="$(stat -c %s "$PREFIX")"
ZICO_BEFORE="$(systemctl show zico-ceo-canonical-adapter.service -p MainPID --value)"
PRODUCER_BEFORE="$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)"
WRITER_BEFORE="$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)"

if [[ -e "$WT" ]]; then
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi

git -C "$ROOT" -c safe.directory="$ROOT" fetch --no-tags origin "$SHA"
git -C "$ROOT" -c safe.directory="$ROOT" worktree add --detach "$WT" "$SHA"

"$PY" -m py_compile "$WT/canonical/teams/models.py" "$WT/canonical/teams/registry.py" "$WT/tools/q4r3_team_advisor_r05_validate_canonical_team_package.py"
PYTHONPATH="$WT" "$PY" -m pytest -q "$WT/tests/test_q4r3_team_advisor_r05_canonical_team_package.py"
mkdir -p "$(dirname "$OUT")"
PYTHONPATH="$WT" "$PY" "$WT/tools/q4r3_team_advisor_r05_validate_canonical_team_package.py" \
  --contract "$WT/config/q4r3_team_canonical_contract_v1.json" --output "$OUT"

"$PY" - "$OUT" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("state")=="PASS", p
assert p.get("package_owner_count")==4, p
assert p.get("runtime_binding_changed") is False, p
assert p.get("runtime_enabled") is False, p
assert p.get("execution_authority")=="none", p
print("R05_OUTPUT_GATE=PASS")
PY

[[ "$(systemctl show zico-ceo-canonical-adapter.service -p MainPID --value)" == "$ZICO_BEFORE" ]]
[[ "$(systemctl show q4r3-exact25-shadow-producer.service -p MainPID --value)" == "$PRODUCER_BEFORE" ]]
[[ "$(systemctl show q4r3-exact25-persistent-single-event-writer.service -p MainPID --value)" == "$WRITER_BEFORE" ]]
cmp -n "$SIZE" "$PREFIX" "$LEDGER"

EVIDENCE="evidence/q4r3_team_advisor_r05_canonical_team_package_latest.json"
mkdir -p "$WT/evidence"
cp -f "$OUT" "$WT/$EVIDENCE"
git -C "$WT" add "$EVIDENCE"
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name="ZEL Runtime Evidence" -c user.email="zel-runtime-evidence@localhost" commit -m "Record R0.5 canonical Team package evidence"
  git -C "$WT" push origin "HEAD:refs/heads/$BRANCH"
fi

echo Q4R3_TEAM_ADVISOR_R05_BOOTSTRAP_PASS
echo "EVIDENCE=$EVIDENCE"
