cat > "$ROOT/engine/exec_live.py" <<'PY'
class LiveExec:
    def place(self, order):
        raise NotImplementedError("wire exchange here")
    def cancel(self, oid):
        raise NotImplementedError
exec_live = None # attach real live exec to enable promotion
PY
