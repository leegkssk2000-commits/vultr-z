cat > $Z/scripts_backup_daily.sh <<'SH'
set -e
D=/home/z/z_backups; mkdir -p "$D"
cd /home/z
tar -czf "$D/z.$(date +%F_%H%M).tgz" z/config z/engine z/strategies z/templates z/static z/db z/.env 2>/dev/null || true
ls -1t "$D"/z.*.tgz | tail -n +8 | xargs -r rm -f
echo "BACKUP_OK"
SH