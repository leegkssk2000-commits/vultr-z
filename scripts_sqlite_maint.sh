cat > $Z/scripts_sqlite_maint.sh <<'SH'
set -e
DB=/home/z/z/db/z.sqlite
test -f "$DB" || exit 0
command -v sqlite3 >/dev/null || exit 0
sqlite3 "$DB" ".backup '/home/z/z_backups/sql.$(date +%F_%H%M).sqlite'"
sqlite3 "$DB" 'PRAGMA optimize; VACUUM; ANALYZE;'
echo "SQLITE_OK"
SH