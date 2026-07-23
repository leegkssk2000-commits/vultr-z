#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_REMOTE_SHA="${2:-}"
BRANCH="r7a4d-historical-simulation-3600-v1"
CHILD_REL="backend/strategies/authentic/supertrend_flip_authentic.py"
VERIFY_REL="tools/r7a4d2_supertrend_authentic_child_implementation_and_formula_fixtures.py"
TMPROOT="$(mktemp -d /tmp/r7a4d2-supertrend-pandas3-repair.XXXXXX)"
WT="$TMPROOT/worktree"
LOG="$TMPROOT/repair.log"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo "STATE=HOLD_SUPERTREND_AUTHENTIC_PANDAS3_COMPAT_REPAIR"
  echo "BLOCKERS=[\"$1\"]"
  echo "RC=2"
  exit 2
}

[[ -d "$ROOT/.git" ]] || fail "ROOT_NOT_GIT_REPOSITORY"
[[ -n "$EXPECTED_REMOTE_SHA" ]] || fail "EXPECTED_REMOTE_SHA_REQUIRED"

echo "R7A4D2_SUPERTREND_AUTHENTIC_PANDAS3_COMPAT_REPAIR_START"
echo "MODE=ISOLATED_TEMP_WORKTREE_ONE_LINE_COMPAT_REPAIR"
echo "LEGACY_PARENT_MUTATION_ALLOWED=false"
echo "STRATEGY_FORMULA_MUTATION_ALLOWED=false"
echo "REGISTRY_MUTATION_ALLOWED=false"
echo "CONFIG_MUTATION_ALLOWED=false"
echo "ROUTER_MUTATION_ALLOWED=false"
echo "SERVICE_MUTATION_ALLOWED=false"
echo "SHADOW_START_ALLOWED=false"
echo "PAPER_LIVE_ORDER_ALLOWED=false"

git -C "$ROOT" fetch --no-tags origin "$BRANCH" >>"$LOG" 2>&1 || fail "GITHUB_FETCH_FAILED"
REMOTE_SHA="$(git -C "$ROOT" rev-parse FETCH_HEAD 2>/dev/null || true)"
echo "REMOTE_SHA=$REMOTE_SHA"
echo "EXPECTED_REMOTE_SHA=$EXPECTED_REMOTE_SHA"
[[ "$REMOTE_SHA" == "$EXPECTED_REMOTE_SHA" ]] || fail "UNEXPECTED_GITHUB_HEAD"

git -C "$ROOT" worktree add --detach "$WT" "$REMOTE_SHA" >>"$LOG" 2>&1 || fail "TEMP_WORKTREE_CREATE_FAILED"
CHILD="$WT/$CHILD_REL"
VERIFY="$WT/$VERIFY_REL"
[[ -f "$CHILD" ]] || fail "CHILD_FILE_MISSING"
[[ -f "$VERIFY" ]] || fail "VERIFIER_FILE_MISSING"

BEFORE_SHA="$(sha256sum "$CHILD" | awk '{print $1}')"
PATCH_RESULT="$(python3 - "$CHILD" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "finite_mask = values.applymap(_is_finite)"
new = "finite_mask = values.apply(lambda column: column.map(_is_finite))"
count = text.count(old)
if count != 1:
    print(f"PATCH_MATCH_COUNT_INVALID:{count}")
    raise SystemExit(2)
path.write_text(text.replace(old, new), encoding="utf-8")
print("PATCH_OK")
PY
)" || fail "$PATCH_RESULT"
[[ "$PATCH_RESULT" == "PATCH_OK" ]] || fail "$PATCH_RESULT"

grep -Fq 'values.applymap(_is_finite)' "$CHILD" && fail "APPLYMAP_STILL_PRESENT"
grep -Fq 'values.apply(lambda column: column.map(_is_finite))' "$CHILD" || fail "COMPAT_REPLACEMENT_MISSING"
AFTER_SHA="$(sha256sum "$CHILD" | awk '{print $1}')"
[[ "$BEFORE_SHA" != "$AFTER_SHA" ]] || fail "CHILD_HASH_UNCHANGED"

git -C "$WT" add "$CHILD_REL" || fail "GIT_ADD_FAILED"
git -C "$WT" -c user.name='Z Ops Assistant' -c user.email='z-ops@local.invalid' commit -m 'R7.A4D2 repair pandas 3 DataFrame applymap compatibility' >>"$LOG" 2>&1 || fail "GIT_COMMIT_FAILED"
REPAIR_SHA="$(git -C "$WT" rev-parse HEAD)"
echo "REPAIR_SHA=$REPAIR_SHA"
echo "CHILD_SHA256_BEFORE=$BEFORE_SHA"
echo "CHILD_SHA256_AFTER=$AFTER_SHA"

set +e
python3 "$VERIFY" --root "$WT" --target-sha "$REPAIR_SHA" 2>&1 | tee -a "$LOG"
VERIFY_RC=${PIPESTATUS[0]}
set -e
[[ "$VERIFY_RC" -eq 0 ]] || fail "POST_REPAIR_FIXTURE_VERIFY_FAILED_RC_${VERIFY_RC}"

git -C "$WT" diff --quiet "$REMOTE_SHA" -- "$CHILD_REL" || true
CHANGED_FILES="$(git -C "$WT" diff-tree --no-commit-id --name-only -r "$REPAIR_SHA")"
[[ "$CHANGED_FILES" == "$CHILD_REL" ]] || fail "PATCH_SCOPE_INVALID"

git -C "$WT" push origin "$REPAIR_SHA:refs/heads/$BRANCH" >>"$LOG" 2>&1 || fail "GITHUB_PUSH_FAILED"

FINAL_REMOTE_SHA="$(git -C "$ROOT" ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')"
[[ "$FINAL_REMOTE_SHA" == "$REPAIR_SHA" ]] || fail "REMOTE_SHA_POST_PUSH_MISMATCH"

echo "STATE=PASS_SUPERTREND_AUTHENTIC_PANDAS3_COMPAT_REPAIR"
echo "PATCH_SCOPE=$CHILD_REL"
echo "PATCH_SEMANTICS=ELEMENTWISE_FINITE_CHECK_ONLY"
echo "FORMULA_MUTATION_COUNT=0"
echo "LEGACY_PARENT_MUTATION_COUNT=0"
echo "REGISTRY_MUTATION_COUNT=0"
echo "CONFIG_MUTATION_COUNT=0"
echo "POST_REPAIR_FIXTURE_VERIFY_RC=0"
echo "REMOTE_REPAIR_SHA=$REPAIR_SHA"
echo "NEXT_STAGE=R7.A4D2_SUPERTREND_AUTHENTIC_STATE_TRANSITION_AND_BIDIRECTIONAL_REPLAY"
echo "BLOCKERS=[]"
echo "RC=0"
