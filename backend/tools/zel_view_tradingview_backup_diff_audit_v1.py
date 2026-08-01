from __future__ import annotations

import difflib
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CURRENT_CANDIDATES = (
    Path('/var/www/z-os-alimi/view/index.html'),
    Path('/var/www/z-os-alimi/view.html'),
    Path('/var/www/z-os-alimi/index.html'),
)
SEARCH_ROOTS = (
    Path('/var/www/z-os-alimi'),
    Path('/home/z/z/.deploy_backups'),
    Path('/home/z/z/backups'),
    Path('/var/backups'),
)
MARKERS = ('TradingView', 'tradingview', 'lightweight-charts', 'createChart', 'addCandlestickSeries', 'candlestick')
EXCLUDE = {'node_modules', '.git', '.venv', 'venv', '__pycache__'}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    current = next((p for p in CURRENT_CANDIDATES if p.is_file()), None)
    if current is None:
        raise SystemExit('CURRENT_VIEW_SOURCE_NOT_FOUND')
    current_text = current.read_text(errors='ignore')
    current_lines = current_text.splitlines()
    candidates = []
    seen = {str(current.resolve())}
    for root in SEARCH_ROOTS:
        if not root.exists(): continue
        count = 0
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in EXCLUDE]
            for name in files:
                if count >= 30000: break
                path = Path(base) / name
                count += 1
                try:
                    if path.suffix.lower() not in {'.html','.htm','.js','.jsx','.ts','.tsx'} or path.stat().st_size > 5_000_000: continue
                    resolved = str(path.resolve())
                    if resolved in seen: continue
                    seen.add(resolved)
                    text = path.read_text(errors='ignore')
                except OSError:
                    continue
                hits = [m for m in MARKERS if m.lower() in text.lower()]
                if not hits: continue
                ratio = difflib.SequenceMatcher(None, current_text[:500000], text[:500000], autojunk=False).ratio()
                current_only = sum(1 for line in difflib.ndiff(current_lines, text.splitlines()) if line.startswith('- '))
                candidate_only = sum(1 for line in difflib.ndiff(current_lines, text.splitlines()) if line.startswith('+ '))
                st = path.stat()
                candidates.append({'path':str(path),'sha256':sha(path),'bytes':st.st_size,'mtime':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'markers':hits,'similarity':round(ratio,6),'current_only_lines':current_only,'candidate_only_lines':candidate_only})
            if count >= 30000: break
    candidates.sort(key=lambda x:(-x['similarity'], -datetime.fromisoformat(x['mtime']).timestamp()))
    best = candidates[0] if candidates else None
    result = {
        'schema_version':'zel.view.tradingview.backup_diff.audit.v1',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'state':'PASS_TRADINGVIEW_BACKUP_CANDIDATE_FOUND' if best else 'HOLD_NO_TRADINGVIEW_BACKUP_CANDIDATE',
        'current':{'path':str(current),'sha256':sha(current),'bytes':current.stat().st_size,'markers':[m for m in MARKERS if m.lower() in current_text.lower()]},
        'candidate_count':len(candidates),
        'best_candidate':best,
        'top_candidates':candidates[:20],
        'restoration_contract':{'full_file_restore_allowed':False,'chart_block_only_candidate_review_required':True,'existing_cards_preserve':True,'golden_screenshot_required':True,'rollback_hash_required':True},
        'safety':{'read_only':True,'frontend_mutated':False,'runtime_mutated':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
    }
    Path('/tmp/zel_view_tradingview_backup_diff_audit_v1.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':result['state'],'current':result['current'],'candidate_count':len(candidates),'best_candidate':best},sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
