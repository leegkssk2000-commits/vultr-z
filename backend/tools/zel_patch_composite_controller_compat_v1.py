from __future__ import annotations

from pathlib import Path

V2 = Path("backend/tools/zel_composite_post_terminal_controller_v2.sh")

OLD = '''"${SSH[@]}" \\
  "python3 - --source-root /home/z/z --trades /var/lib/zel-research/data-b-1m-v2/trades.jsonl.gz --stdout" \\
  < "$ROOT/backend/tools/zel_trade_method_runtime_behavior_v1.py" \\
  > "$OUT/trade_method_behavior.json"
python - <<'PY'
'''

NEW = '''set +e
"${SSH[@]}" \\
  "python3 - --source-root /home/z/z --trades /var/lib/zel-research/data-b-1m-v2/trades.jsonl.gz --stdout" \\
  < "$ROOT/backend/tools/zel_trade_method_runtime_behavior_v1.py" \\
  > "$OUT/trade_method_behavior.json"
trade_method_behavior_rc=$?
set -e
test "$trade_method_behavior_rc" -eq 0 -o "$trade_method_behavior_rc" -eq 1
python - <<'PY'
'''


def main() -> int:
    text = V2.read_text(encoding="utf-8")
    if "trade_method_behavior_rc=$?" not in text:
        if text.count(OLD) != 1:
            raise SystemExit(f"TRADE_METHOD_CALL_FRAGMENT_COUNT:{text.count(OLD)}")
        text = text.replace(OLD, NEW, 1)
        V2.write_text(text, encoding="utf-8")
    required = (
        "trade_method_behavior_rc=$?",
        'test "$trade_method_behavior_rc" -eq 0 -o "$trade_method_behavior_rc" -eq 1',
        "HOLD_TRADE_METHOD_ENABLED_COUNTERFACTUAL_ADAPTER_REQUIRED",
        "0 <= row['enabled_strategy_count'] <= row['strategy_count']",
    )
    current = V2.read_text(encoding="utf-8")
    for marker in required:
        if marker not in current:
            raise SystemExit(f"REQUIRED_MARKER_MISSING:{marker}")
    print("PASS_COMPOSITE_CONTROLLER_COMPAT_PATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
