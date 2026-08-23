#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, tempfile
from pathlib import Path
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as d


def run(out: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix='trend_rider_loss_fast_') as td:
        receipt=d._run_receipt('trend_rider', Path(td)/'trend_rider.json')
        row=d.diagnose('trend_rider', receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    return row


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,default=Path('out/a1_trend_rider_loss_cluster_fast_latest.json')); args=ap.parse_args()
    r=run(args.out)
    print(json.dumps({'completed_trades':r['completed_trades'],'loss_streak':r['current_loss_streak'],'route':r['recommended_route'],'top':r['ranked_causal_hypotheses'][:3]},sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
