from pathlib import Path

path=Path('backend/tools/zel_ema_mfe_mae_semantics_probe_v1.py')
text=path.read_text(encoding='utf-8')
old='import os\nfrom datetime import datetime, timezone\n'
new='import os\nfrom collections import Counter\nfrom datetime import datetime, timezone\n'
if new not in text:
    if text.count(old)!=1:
        raise RuntimeError(f'IMPORT_MATCH_COUNT_{text.count(old)}')
    text=text.replace(old,new,1)
path.write_text(text,encoding='utf-8')
