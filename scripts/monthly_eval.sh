#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/z/z
POL=$ROOT/config/post620.yml
AL=$ROOT/logs/alerts.jsonl
TS=$(date -u +%s)
wr=$(sqlite3 $ROOT/db/z.sqlite "select avg(win) from runs where ts>=datetime('now','-30 day');")
pf=$(sqlite3 $ROOT/db/z.sqlite "select sum(pnl) from runs where ts>=datetime('now','-30 day');")
wr=${wr:-0}; pf=${pf:-0}
echo "{\"ts\":$TS,\"msg\":\"monthly_kpi\",\"wr\":$wr,\"pf\":$pf}" >> "$AL"
exit 0