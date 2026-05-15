#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="/home/z/z/frontend"
ENV_FILE="$BASE/.z_app_source_root.env"
[ -f "$ENV_FILE" ] || { echo "FAIL: env lock missing: $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"

[ "$APP_SOURCE_ROOT" = "$ROOT" ] || { echo "FAIL: APP_SOURCE_ROOT mismatch: env=$APP_SOURCE_ROOT cwd=$ROOT" >&2; exit 1; }
[ "$APP_DEPLOY_ROOT_1" = "/var/www/z-os-app" ] || { echo "FAIL: deploy root must be /var/www/z-os-app" >&2; exit 1; }

cd "$ROOT"
npm run build
npm run validate

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BK="/home/z/z/backups/app_canonical_deploy_${TS}"
mkdir -p "$BK"
echo "== backup current live root =="
rsync -a "$APP_DEPLOY_ROOT_1"/ "$BK/var_www_z-os-app/"

echo "== deploy dist -> live root =="
rsync -a --delete "$APP_DIST_DIR"/ "$APP_DEPLOY_ROOT_1"/

echo "== live verify =="
curl -k -L -sI "https://app.z-os.vip/?v=$TS" | grep -Ei 'date:|cache-control:|server:|x-zel-root:' || true
curl -k -L -s "https://app.z-os.vip/?v=$TS" -o /tmp/z_app_live_after_canonical_deploy.html
grep -nE 'assets/index-|_emergency_runtime_guard|zel_team|zuiTeam|TeamOverlay|ALIMI|source=baseline-preserve' /tmp/z_app_live_after_canonical_deploy.html || true

cat > "$BK/rollback.sh" <<ROLLBACK
#!/usr/bin/env bash
set -Eeuo pipefail
rsync -a --delete "$BK/var_www_z-os-app/" "$APP_DEPLOY_ROOT_1/"
echo "ROLLED_BACK_TO=$BK"
ROLLBACK
chmod +x "$BK/rollback.sh"

echo "RESULT=PASS_DEPLOYED_FROM_CANONICAL_SOURCE_ROOT"
echo "BACKUP=$BK"
echo "ROLLBACK=$BK/rollback.sh"
