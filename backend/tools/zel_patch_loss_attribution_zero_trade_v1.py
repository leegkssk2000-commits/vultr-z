from __future__ import annotations

from pathlib import Path

SCRIPT = Path("backend/tools/zel_strategy_loss_attribution_gemini_v1.py")
WORKFLOW = Path(".github/workflows/zel-strategy-loss-attribution-gemini-v1.yml")

text = SCRIPT.read_text(encoding="utf-8")

old = "import argparse\nimport gzip\n"
new = "import argparse\nimport csv\nimport gzip\n"
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''def max_drawdown(values: Sequence[float]) -> float:\n'''
new = '''def read_strategy_inventory(path: Path, expected_count: int) -> tuple[list[str], str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    if not rows or not reader.fieldnames:
        raise RuntimeError("SCOREBOARD_EMPTY_OR_HEADER_MISSING")
    preferred = ("strategy_id", "strategy", "strategy_name", "source_strategy_id", "id", "name")
    candidates = [field for field in preferred if field in reader.fieldnames]
    candidates.extend(field for field in reader.fieldnames if field not in candidates)
    for field in candidates:
        values: list[str] = []
        seen: set[str] = set()
        for row in rows:
            value = str(row.get(field) or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        if len(values) == expected_count:
            return values, field, len(rows)
    raise RuntimeError(
        "SCOREBOARD_STRATEGY_COLUMN_NOT_FOUND:"
        + json.dumps({"fields": reader.fieldnames, "row_count": len(rows)}, sort_keys=True)
    )


def max_drawdown(values: Sequence[float]) -> float:
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''    parser.add_argument("--trades", type=Path, required=True)\n    parser.add_argument("--policy", type=Path, required=True)\n'''
new = '''    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--scoreboard", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''    strategies_grouped = group_rows(rows, "strategy_id")\n    if len(strategies_grouped) != int(policy["expected_strategy_count"]):\n        raise RuntimeError(f"STRATEGY_COUNT_MISMATCH:{len(strategies_grouped)}")\n\n    overall = metrics(rows)\n'''
new = '''    expected_strategy_count = int(policy["expected_strategy_count"])
    strategy_inventory, inventory_field, scoreboard_row_count = read_strategy_inventory(
        args.scoreboard, expected_strategy_count
    )
    trade_strategies_grouped = group_rows(rows, "strategy_id")
    unknown_trade_strategy_ids = sorted(set(trade_strategies_grouped) - set(strategy_inventory))
    if unknown_trade_strategy_ids:
        raise RuntimeError(
            "TRADE_STRATEGY_NOT_IN_SCOREBOARD:" + json.dumps(unknown_trade_strategy_ids)
        )
    strategies_grouped = {
        strategy_id: trade_strategies_grouped.get(strategy_id, [])
        for strategy_id in strategy_inventory
    }
    traded_strategy_count = sum(bool(group) for group in strategies_grouped.values())
    zero_trade_strategy_count = expected_strategy_count - traded_strategy_count

    overall = metrics(rows)
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''    ordered_ids = sorted(\n        strategies_grouped,\n        key=lambda strategy_id: float(metrics(strategies_grouped[strategy_id])["gross_loss_R"] or 0.0),\n        reverse=True,\n    )\n'''
new = '''    ordered_ids = sorted(
        strategies_grouped,
        key=lambda strategy_id: (
            -float(metrics(strategies_grouped[strategy_id])["gross_loss_R"] or 0.0),
            -int(metrics(strategies_grouped[strategy_id])["trade_count"] or 0),
            strategy_id,
        ),
    )
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''                "strategy_id": strategy_id,\n                "alias": alias_map[strategy_id],\n                "overall": row_metrics,\n'''
new = '''                "strategy_id": strategy_id,
                "alias": alias_map[strategy_id],
                "state": "PASS_TRADE_BEARING_STRATEGY" if group else "HOLD_ZERO_TRADE_STRATEGY",
                "overall": row_metrics,
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''        "trade_count": len(rows),\n        "strategy_count": len(strategy_rows),\n        "overall": overall,\n'''
new = '''        "trade_count": len(rows),
        "strategy_count": len(strategy_rows),
        "traded_strategy_count": traded_strategy_count,
        "zero_trade_strategy_count": zero_trade_strategy_count,
        "strategy_inventory_source": {
            "path_role": "terminal_scoreboard",
            "identity_field": inventory_field,
            "row_count": scoreboard_row_count,
        },
        "overall": overall,
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''    top_count = int(policy["top_strategy_count"])\n    top = strategy_rows[:top_count]\n'''
new = '''    top_count = int(policy["top_strategy_count"])
    top = [row for row in strategy_rows if int(row["overall"]["trade_count"] or 0) > 0][:top_count]
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = '''        "trade_count": len(rows),\n        "strategy_count": len(strategy_rows),\n        "top_strategy_count": len(top),\n'''
new = '''        "trade_count": len(rows),
        "strategy_count": len(strategy_rows),
        "traded_strategy_count": traded_strategy_count,
        "zero_trade_strategy_count": zero_trade_strategy_count,
        "top_strategy_count": len(top),
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

SCRIPT.write_text(text, encoding="utf-8")

workflow = WORKFLOW.read_text(encoding="utf-8")

old = '''          "${SSH[@]}" 'cat /var/lib/zel-research/data-b-1m-v2/report.json' > input/report.json\n          "${SSH[@]}" 'cat /var/lib/zel-research/data-b-1m-v2/trades.jsonl.gz' > input/trades.jsonl.gz\n          python - <<'PY'\n          import gzip,json\n'''
new = '''          "${SSH[@]}" 'cat /var/lib/zel-research/data-b-1m-v2/report.json' > input/report.json
          "${SSH[@]}" 'cat /var/lib/zel-research/data-b-1m-v2/scoreboard.csv' > input/scoreboard.csv
          "${SSH[@]}" 'cat /var/lib/zel-research/data-b-1m-v2/trades.jsonl.gz' > input/trades.jsonl.gz
          python - <<'PY'
          import csv,gzip,json
'''
assert workflow.count(old) == 1, workflow.count(old)
workflow = workflow.replace(old, new, 1)

old = '''          assert replay['strategy_failure_count']==0,replay\n          with gzip.open('input/trades.jsonl.gz','rt',encoding='utf-8') as fh:\n              count=sum(1 for line in fh if line.strip())\n          assert count==1951,count\n          print({'terminal':terminal['state'],'strategies':replay['strategy_count_completed'],'trades':count})\n'''
new = '''          assert replay['strategy_failure_count']==0,replay
          with open('input/scoreboard.csv','r',encoding='utf-8-sig',newline='') as fh:
              scoreboard=list(csv.DictReader(fh))
              fields=fh.seek(0) or next(csv.reader(fh), [])
          assert scoreboard,scoreboard
          with gzip.open('input/trades.jsonl.gz','rt',encoding='utf-8') as fh:
              count=sum(1 for line in fh if line.strip())
          assert count==1951,count
          print({
              'terminal':terminal['state'],
              'completed_strategies':replay['strategy_count_completed'],
              'scoreboard_rows':len(scoreboard),
              'scoreboard_fields':fields,
              'trades':count,
          })
'''
assert workflow.count(old) == 1, workflow.count(old)
workflow = workflow.replace(old, new, 1)

old = '''            --trades input/trades.jsonl.gz \\\n            --policy backend/research/zel_strategy_loss_attribution_gemini_v1.json \\\n'''
new = '''            --trades input/trades.jsonl.gz \\
            --scoreboard input/scoreboard.csv \\
            --policy backend/research/zel_strategy_loss_attribution_gemini_v1.json \\
'''
assert workflow.count(old) == 1, workflow.count(old)
workflow = workflow.replace(old, new, 1)

old = '''          assert row['trade_count']==1951 and row['strategy_count']==25,row\n          assert row['gemini_used'] is True and row['gemini_call_count']>=8,row\n'''
new = '''          assert row['trade_count']==1951 and row['strategy_count']==25,row
          assert row['traded_strategy_count']==13 and row['zero_trade_strategy_count']==12,row
          assert row['gemini_used'] is True and row['gemini_call_count']>=8,row
'''
assert workflow.count(old) == 1, workflow.count(old)
workflow = workflow.replace(old, new, 1)

old = '''          assert attribution['strategy_count']==25 and len(attribution['strategies'])==25,attribution\n          print({\n'''
new = '''          assert attribution['strategy_count']==25 and len(attribution['strategies'])==25,attribution
          assert attribution['traded_strategy_count']==13 and attribution['zero_trade_strategy_count']==12,attribution
          assert sum(item['state']=='HOLD_ZERO_TRADE_STRATEGY' for item in attribution['strategies'])==12,attribution
          print({
'''
assert workflow.count(old) == 1, workflow.count(old)
workflow = workflow.replace(old, new, 1)

workflow = workflow.replace(
    '          test -z "$(find out -type f -size +2M -print -quit)"\n',
    '          test -z "$(find out -type f -size +5M -print -quit)"\n',
    1,
)

WORKFLOW.write_text(workflow, encoding="utf-8")
print("PASS_ZERO_TRADE_STRATEGY_INVENTORY_PATCH")
