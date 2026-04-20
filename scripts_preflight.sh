cat > $Z/scripts_preflight.sh <<'SH'
set -e
cd /home/z/z
echo "[1] venv/gunicorn"; test -x venv/bin/gunicorn
echo "[2] app import"; venv/bin/python - <<'PY'
from app import create_app
app=create_app(); print("APP_OK", bool(app))
PY
echo "[3] db"; test -d db || mkdir -p db; test -f db/z.sqlite || :> db/z.sqlite
echo "[4] tables"; command -v sqlite3 >/dev/null && sqlite3 db/z.sqlite '.tables' || true
echo "[5] port"; ss -ltnp | grep -E ':(8000)\s' || echo "not-listening"
echo "[6] health"; curl -sS http://127.0.0.1:8000/api/health || echo "no-health"
echo "DONE"
SH