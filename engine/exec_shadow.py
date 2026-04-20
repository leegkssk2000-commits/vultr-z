cat > "$ROOT/engine/exec_shadow.py" <<'PY'
from engine.utils.costs import est_slippage, fee_cost
# filled_price = px + side*est_slippage(spread, vol)
# pnl -= fee_cost(abs(notional))
class ShadowExec:
    def place(self, order):
        return {"ok": True, "mode": "paper", "order": order}
    def cancel(self, oid):
        return {"ok": True}
exec_shadow = ShadowExec()
PY