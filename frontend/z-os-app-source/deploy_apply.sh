#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/z/z/frontend/z-os-pwa}"
cd "$ROOT"

BUILD_ROOT="$PWD"
LEGACY_RX='zel_step3_team_stack_polish|zel_step3c_team_overlay_rebuild|zel_step3c_single_team_fix|zel_team_dense_overlay|zuiTeamOverlayModal1v4|zui-team-overlay|zui-team-modal|data-zui-team-modal|data-zui-team-overlay|zel-team-board-c|class/data selector containing zel-step3|zel-step3|LANE / TEAM OVERLAY|Active / standby / fallback / rejected'
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/home/z/z/backups/pwa_route_teams_${TS}"

if [[ -f pnpm-lock.yaml ]]; then
  PM_INSTALL=(pnpm install --frozen-lockfile)
  PM_BUILD=(pnpm run build)
elif [[ -f yarn.lock ]]; then
  PM_INSTALL=(yarn install --frozen-lockfile)
  PM_BUILD=(yarn build)
elif [[ -f package-lock.json ]]; then
  PM_INSTALL=(npm ci)
  PM_BUILD=(npm run build)
else
  echo "no_supported_lockfile_found" >&2
  exit 1
fi

echo "[1/6] install"
"${PM_INSTALL[@]}"

echo "[2/6] build"
"${PM_BUILD[@]}"
test -f dist/index.html

echo "[3/6] validate dist"
if grep -RInE "$LEGACY_RX" dist/index.html dist/assets 2>/dev/null; then
  echo "legacy_team_overlay_reference_found_in_dist" >&2
  exit 1
fi
if ! grep -Rqs 'data-zr-route-teams-panel' dist/assets; then
  echo "route_teams_panel_marker_missing_in_dist" >&2
  exit 1
fi
echo "PASS dist.index.asset_ref=$(grep -Eo '/assets/index-[^\" ]+\\.js' dist/index.html | head -n1)"
echo "PASS dist.zuiTeamOverlayModalV4=$(grep -Rsc 'zuiTeamOverlayModalV4' dist/assets | awk -F: '{s+=$2} END{print s+0}')"
echo "PASS dist.CandidateLaneFlow=$(grep -Rsc 'CandidateLaneFlow' dist/assets | awk -F: '{s+=$2} END{print s+0}')"
echo "PASS dist.legacy_team_overlay_render=$(grep -Rsc 'TEAM OVERLAY\\|zr-team-overlay-backdrop' dist/assets | awk -F: '{s+=$2} END{print s+0}')"

echo "[4/6] backup + deploy"
mkdir -p "$BACKUP_ROOT"
targets=(
  "/home/z/z/frontend/z-os-pwa/dist"
  "/var/www/html"
  "/var/www/z-os-pwa"
  "/var/www/z-os"
  "/var/www/z-os-app"
)

for target in "${targets[@]}"; do
  [[ -d "$target" ]] || continue
  safe_name="$(printf '%s' "$target" | sed 's#/#_#g; s#^_##')"
  mkdir -p "$BACKUP_ROOT/$safe_name"
  if [[ -f "$target/index.html" ]]; then
    cp -a "$target/index.html" "$BACKUP_ROOT/$safe_name/index.html"
  fi
  if [[ -d "$target/assets" ]]; then
    cp -a "$target/assets" "$BACKUP_ROOT/$safe_name/assets"
  fi
  rsync -a --delete dist/ "$target/"
done

echo "[5/6] validate deployed roots"
for target in "${targets[@]}"; do
  [[ -f "$target/index.html" ]] || continue
  if grep -RInE "$LEGACY_RX" "$target/index.html" "$target/assets" 2>/dev/null; then
    echo "legacy_team_overlay_reference_found_in_target=$target" >&2
    exit 1
  fi
  echo "PASS target=$target asset_ref=$(grep -Eo '/assets/index-[^\" ]+\\.js' "$target/index.html" | head -n1)"
  echo "PASS target=$target zuiTeamOverlayModalV4=$(grep -Rsc 'zuiTeamOverlayModalV4' "$target/assets" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')"
  echo "PASS target=$target CandidateLaneFlow=$(grep -Rsc 'CandidateLaneFlow' "$target/assets" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')"
  echo "PASS target=$target legacy_team_overlay_render=$(grep -Rsc 'TEAM OVERLAY\\|zr-team-overlay-backdrop' "$target/assets" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')"
done

echo "[6/6] verification hints"
cat <<'EOF'
Browser console validation:
const legacy = [...document.querySelectorAll('script[src],link[href]')]
  .map(x => x.src || x.href)
  .filter(x => /zel_step3_team_stack_polish|zel_step3c_team_overlay_rebuild|zel_step3c_single_team_fix|zel_team_dense_overlay|zuiTeamOverlayModal1v4/i.test(x));
const legacyNodes = document.querySelectorAll('[class*="zel-step3"],[data-zel-step3],[data-zui-team-modal],[data-zui-team-overlay],.zel-team-board-c').length;
const newPanel = document.querySelectorAll('[data-zr-route-teams-panel]').length;
const cards = document.querySelectorAll('[data-zr-team-card]').length;
const modalRoots = document.querySelectorAll('[data-zr-team-modal-root]').length;
const orderbooks = document.querySelectorAll('.zel-v6-book,.zel-btc-v8-card').length;
console.log({ legacy, legacyNodes, newPanel, cards, modalRoots, orderbooks });

Expected:
legacy=[]
legacyNodes=0
newPanel=1
cards=4
modalRoots<=1
orderbooks=5
EOF

echo "backup_root=$BACKUP_ROOT"
echo "build_root=$BUILD_ROOT"