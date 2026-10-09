"""Generated source-chain fixtures only; no HTTP, VPS, signals, or PnL."""
from __future__ import annotations

import ast
import csv
import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ops import issue1388_canonical_daily_close_audit_v1 as a

SYMBOL = "BTC-USDT"
REQUESTED = "2026-09-15T12:00:00+00:00"
RECEIVED = "2026-09-15T12:00:00.100000+00:00"


def write(root, relative, raw):
    p = root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
    return a.sha(raw)


def csv_bytes(rows):
    out = io.StringIO(newline=""); writer = csv.DictWriter(out, fieldnames=a.FIELDS, lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    return gzip.compress(out.getvalue().encode(), mtime=0)


def raw_row(ts):
    return dict(time=ts, open="10", high="14", low="9", close="11", volume="2")


def request_fixture(root, segment, start, end, missing=()):
    rows = [raw_row(t) for t in range(start, end, a.MINUTE_MS) if t not in set(missing)]
    body = a.json_bytes(dict(code=0, data=list(reversed(rows))))  # Native reverse order is legitimate.
    relative = f"requests/{SYMBOL}/{start}_{end}"
    body_hash = write(root, segment + "/" + relative + ".body", body)
    query = dict(symbol=SYMBOL, interval="1m", timeZone=0, startTime=start, endTime=end-1, limit=1000, timestamp=a.utc_ms(REQUESTED))
    receipt = dict(schema=a.HISTORY_SCHEMA+".http_response", source=a.SOURCE,
                   symbol=SYMBOL, interval="1m", start_ms=start, end_exclusive_ms=end,
                   http_status=200, body_path=relative+".body", body_sha256=body_hash,
                   body_bytes=len(body), requested_at_utc=REQUESTED, received_at_utc=RECEIVED,
                   source_timezone="UTC", volume_unit="UNKNOWN",
                   timestamp_semantics="UNVERIFIED_REPORTED_GRID_NO_OPEN_CLOSE_AUTHORITY",
                   query=query, url=a.SOURCE+"?"+"&".join(f"{k}={v}" for k,v in query.items()))
    receipt_hash = write(root, segment+"/"+relative+".receipt.json", a.json_bytes(receipt))
    normalized = [a.normalize_row(row) for row in rows]
    return normalized, receipt_hash, body_hash


def day_fixture(root, start=a.CUTOFF_MS-a.DAY_MS, end=a.CUTOFF_MS):
    segment = "canonical_postgap_20260213"; sources, all_rows = [], []
    for lo, hi in a._windows(start, end):
        rows, receipt_hash, _ = request_fixture(root, segment, lo, hi)
        path = f"normalized_chunks/{SYMBOL}/{lo}_{hi}.csv.gz"
        normalized_hash = write(root, segment+"/"+path, csv_bytes(rows))
        sources.append(dict(path=f"requests/{SYMBOL}/{lo}_{hi}.receipt.json", sha256=receipt_hash,
                            normalized_path=path, normalized_sha256=normalized_hash))
        all_rows.extend(rows)
    artifact_path = f"1m/{SYMBOL}/{start}_{end}.csv.gz"
    artifact_hash = write(root, segment+"/"+artifact_path, csv_bytes(all_rows))
    receipt = dict(schema=a.HISTORY_SCHEMA+".daily", symbol=SYMBOL, start_ms=start,
                   end_exclusive_ms=end, start_utc=a.utc_text(start), end_exclusive_utc=a.utc_text(end),
                   rows_1m=len(all_rows), expected_rows_1m=len(all_rows), gap_count=0, duplicate_count=0,
                   volume_unit="UNKNOWN", synthetic_fill=False, forward_fill=False,
                   source_receipts=sources, artifacts=[dict(timeframe_minutes=1, path=artifact_path,
                   sha256=artifact_hash, row_count=len(all_rows), incomplete_boundary_buckets_excluded=[])]
                   + [dict(timeframe_minutes=x) for x in (15,30,60)])
    relative = f"{segment}/daily_receipts/{SYMBOL}/{start}_{end}.json"
    save_day(root, relative, receipt)
    return segment, start, end, relative, all_rows


def save_day(root, relative, receipt):
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = a.sha(a.json_bytes(receipt))
    write(root, relative, a.json_bytes(receipt))


def rebind_response(root, relative, index, change):
    daily = json.loads((root/relative).read_bytes()); source = daily["source_receipts"][index]
    segment = relative.split("/")[0]
    receipt_path = root/segment/source["path"]
    receipt = json.loads(receipt_path.read_bytes()); body_path=root/segment/receipt["body_path"]
    payload=json.loads(body_path.read_bytes()); change(payload)
    body=a.json_bytes(payload); body_path.write_bytes(body)
    receipt.update(body_sha256=a.sha(body), body_bytes=len(body))
    receipt_raw=a.json_bytes(receipt); receipt_path.write_bytes(receipt_raw)
    source["sha256"]=a.sha(receipt_raw); save_day(root,relative,daily)


def calendar():
    return [dict(day_start_ms=t, terminal_ts_ms=t+a.DAY_MS-a.MINUTE_MS,
                 model_available_ts_ms=t+a.DAY_MS, close="11", count_1m=1436 if t==a.GAP_DAY_MS else 1440,
                 missing_1m=4 if t==a.GAP_DAY_MS else 0, proof=["a"*64]*9,
                 clock=[a.utc_ms(REQUESTED),a.utc_ms(RECEIVED),a.utc_ms(RECEIVED)])
            for t in range(a.START_MS,a.CUTOFF_MS,a.DAY_MS)]


class CanonicalCloseAudit(unittest.TestCase):
    def test_native_full_day_chain_and_terminal_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); segment,start,end,_,expected=day_fixture(root)
            reader=a.Reader(root); rows,proof=a.audit_daily(reader,segment,SYMBOL,start,end)
            self.assertEqual(rows,expected)
            self.assertEqual(rows[-1]["timestamp_ms"],a.CUTOFF_MS-a.MINUTE_MS)
            self.assertEqual(len(proof["proof"]),len(a.PROOF_FIELDS))
            self.assertEqual(proof["proof"][6],a.sha(a.json_bytes(rows[-1])))
            self.assertEqual(proof["proof"][7],a.sha(a.json_bytes(raw_row(rows[-1]["timestamp_ms"]))))
            self.assertGreater(proof["clock"][2],end)
            stability=reader.finish()
            self.assertEqual(stability["files_checked"],8)
            self.assertEqual(stability["before_inventory_metadata_and_digest_sha256"],stability["after_inventory_metadata_and_digest_sha256"])

    def test_fixed_calendar_and_dated_361_suffix_reject_stale_closes(self):
        rows=calendar(); out=a.project_calendar(rows)
        self.assertEqual(out["suffix_count"],361)
        self.assertEqual(out["suffix_start_utc"],"2025-09-19T00:00:00+00:00")
        self.assertEqual(out["suffix_end_exclusive_utc"],"2026-09-15T00:00:00+00:00")
        self.assertEqual(out["source_minutes"],525596)
        for bad in (rows[:361],rows[4:-1],rows[:-1],rows[1:]):
            with self.assertRaisesRegex(a.AuditError,"FIXED_365_CALENDAR"):
                a.project_calendar(bad)
        stale=[{**r,'day_start_ms':r['day_start_ms']-a.DAY_MS,'terminal_ts_ms':r['terminal_ts_ms']-a.DAY_MS,
                'model_available_ts_ms':r['model_available_ts_ms']-a.DAY_MS} for r in rows]
        with self.assertRaisesRegex(a.AuditError,"FIXED_365_CALENDAR"):
            a.project_calendar(stale)
        six={symbol:a.project_calendar(calendar()) for symbol in a.SYMBOLS}
        self.assertEqual(sum(x['verified_reported_terminal_rows'] for x in six.values()),2190)
        self.assertLess(len(a.json_bytes({'symbols':six})),a.MAX_OUTPUT_BYTES)

    def test_missing_terminal_future_duplicate_and_fractional_timestamp_block(self):
        for change,reason in (
            (lambda body:body['data'].pop(0),'RAW_MISSING_MINUTES'),
            (lambda body:body['data'].append(body['data'][0]),'RAW_DUPLICATE'),
            (lambda body:body['data'][0].update(time=a.CUTOFF_MS),'OUTSIDE_REQUEST_OR_FIXED_CUTOFF'),
            (lambda body:body['data'][0].update(time=float(a.CUTOFF_MS-a.MINUTE_MS)),'EXACT_INTEGER'),
        ):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); segment,start,end,relative,_=day_fixture(root)
                rebind_response(root,relative,-1,change)
                with self.assertRaisesRegex(a.AuditError,reason):
                    a.audit_daily(a.Reader(root),segment,SYMBOL,start,end)

    def test_self_rehashed_raw_close_cannot_replace_normalized_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); segment,start,end,relative,_=day_fixture(root)
            rebind_response(root,relative,-1,lambda body:body['data'][0].update(close='12'))
            with self.assertRaisesRegex(a.AuditError,'NORMALIZED_CHUNK_HASH_OR_RAW_ROW_BINDING'):
                a.audit_daily(a.Reader(root),segment,SYMBOL,start,end)

    def test_daily_selfhash_and_csv_hash_or_row_order_are_required(self):
        for kind in ('selfhash','normalized_hash','normalized_order','artifact_row'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); segment,start,end,relative,rows=day_fixture(root)
                receipt=json.loads((root/relative).read_bytes())
                if kind=='selfhash':
                    receipt['gap_count']=1; write(root,relative,a.json_bytes(receipt))
                elif kind=='normalized_hash':
                    (root/segment/receipt['source_receipts'][0]['normalized_path']).write_bytes(b'broken')
                elif kind=='normalized_order':
                    source=receipt['source_receipts'][0]; path=source['normalized_path']
                    source['normalized_sha256']=write(root,segment+'/'+path,csv_bytes(list(reversed(rows[:999]))))
                    save_day(root,relative,receipt)
                else:
                    artifact=receipt['artifacts'][0]; replacement=[dict(r) for r in rows]; replacement[-1]['close']='12'
                    artifact['sha256']=write(root,segment+'/'+artifact['path'],csv_bytes(replacement))
                    save_day(root,relative,receipt)
                with self.assertRaises(a.AuditError):a.audit_daily(a.Reader(root),segment,SYMBOL,start,end)

    def test_request_retrieval_clock_is_not_historical_day_close(self):
        for field,value in (('received_at_utc','2025-09-15T00:00:00Z'),
                            ('requested_at_utc','2026-09-15T12:00:00+02:00')):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); segment,start,end,relative,_=day_fixture(root)
                day=json.loads((root/relative).read_bytes()); source=day['source_receipts'][0]
                request=json.loads((root/segment/source['path']).read_bytes()); request[field]=value
                source['sha256']=write(root,segment+'/'+source['path'],a.json_bytes(request)); save_day(root,relative,day)
                with self.assertRaises(a.AuditError):a.audit_daily(a.Reader(root),segment,SYMBOL,start,end)

    def test_native_prefix_schema_keeps_exact_four_minute_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); sources=[]; full=[]
            for start,end in a._windows(a.GAP_DAY_MS,a.GAP_DAY_MS+a.DAY_MS):
                missing=set(range(a.GAP_START_MS,a.GAP_END_MS,a.MINUTE_MS)) & set(range(start,end,a.MINUTE_MS))
                rows,rhash,bhash=request_fixture(root,'canonical_12m',start,end,missing)
                if not missing:write(root,f'canonical_12m/normalized_chunks/{SYMBOL}/{start}_{end}.csv.gz',csv_bytes(rows))
                sources.append(dict(receipt=f'{a.RUNTIME_ROOT}/canonical_12m/requests/{SYMBOL}/{start}_{end}.receipt.json',
                                    receipt_sha256=rhash,body_sha256=bhash)); full.extend(rows)
            prefix=[r for r in full if r['timestamp_ms']<a.GAP_START_MS]
            path=f'canonical_gapday_prefix/{SYMBOL}/1m.csv.gz'; digest=write(root,path,csv_bytes(prefix))
            manifest=dict(symbols=[dict(symbol=SYMBOL,rows_1m=1232,sources=sources,
                         artifacts=[dict(file=f'{a.RUNTIME_ROOT}/{path}',rows=1232,sha256=digest,boundary_buckets_excluded=[])]+[{}]*3)])
            observed,suffix,proof=a.audit_prefix(a.Reader(root),manifest,SYMBOL)
            self.assertEqual(observed,prefix); self.assertEqual(len(observed),1232); self.assertEqual(len(suffix),204)
            self.assertEqual(proof['missing_minutes_preserved'],list(range(a.GAP_START_MS,a.GAP_END_MS,a.MINUTE_MS)))
            self.assertEqual(a._day(a.GAP_DAY_MS,observed+suffix,dict(proof=[],clock=[]))['missing_1m'],4)
            invalid=[r for r in full if r['timestamp_ms']!=a.GAP_START_MS-a.MINUTE_MS]
            with self.assertRaisesRegex(a.AuditError,'DAY_GAP_OR_MISSING_TERMINAL'):
                a._day(a.GAP_DAY_MS,invalid,dict(proof=[],clock=[]))

    def test_reader_rejects_changed_source_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); relative='canonical_12m/MANIFEST.json'; write(root,relative,b'{}\n')
            reader=a.Reader(root); reader.read(relative,100)
            (root/relative).write_bytes(b'changed')
            with self.assertRaises(a.AuditError):reader.finish()
            link=root/'canonical_12m/link.json'; link.symlink_to(root/relative)
            with self.assertRaisesRegex(a.AuditError,'SYMLINK_SOURCE'):
                a.Reader(root).read('canonical_12m/link.json',100)
            with self.assertRaisesRegex(a.AuditError,'PATH_OUTSIDE'):
                a.Reader(root).read('../outside',100)

    def test_gzip_inflation_and_numeric_invalidity_fail_closed(self):
        with self.assertRaisesRegex(a.AuditError,'GZIP_INFLATION_LIMIT'):
            a._csv_rows(gzip.compress(b'x'*(a.MAX_INFLATED_BYTES+1)))
        for value in (True,1.0,'1.0'):
            with self.assertRaises(a.AuditError):a.integer(value,text_allowed=True)
        with self.assertRaises(a.AuditError):a.integer('9'*5000,text_allowed=True)
        for close in ('NaN','Infinity','0','-1',True):
            with self.assertRaises(a.AuditError):a.normalize_row({**raw_row(a.START_MS),'close':close})
        with self.assertRaisesRegex(a.AuditError,'SOURCE_NUMBER_EXPANSION_LIMIT'):
            a.normalize_row({**raw_row(a.START_MS),'close':'1e1000000'})
        with self.assertRaisesRegex(a.AuditError,'INVALID_GZIP_CSV'):
            a._csv_rows(gzip.compress(('timestamp_ms,open,high,low,close,volume\n'+str(a.START_MS)+','+'1'*140000+',2,1,1,1\n').encode()))

    def test_full_inventory_pin_blocks_rehashed_or_extra_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); reader=a.Reader(root)
            for relative in a.MANIFEST_HASHES:
                write(root,relative,b'{}\n'); reader.read(relative,100)
            fixture_expected=a.sha(a.json_bytes({k:v[1] for k,v in reader.files.items()}))
            with patch.object(a,'SOURCE_INVENTORY_FILES',3),patch.object(a,'SOURCE_INVENTORY_SHA256',fixture_expected):
                self.assertEqual(a.verify_inventory(reader)['files'],3)
                write(root,'canonical_12m/MANIFEST.json',b'{"self_rehashed":true}\n')
                changed=a.Reader(root)
                for relative in a.MANIFEST_HASHES:changed.read(relative,100)
                with self.assertRaisesRegex(a.AuditError,'PINNED_FULL_SOURCE_INVENTORY'):
                    a.verify_inventory(changed)
                write(root,'canonical_12m/requests/BTC-USDT/future.body',b'future')
                with self.assertRaisesRegex(a.AuditError,'INVENTORY_EXTRA_FILES'):
                    a.verify_inventory(changed)

    def test_stdin_cli_is_stdlib_read_only_and_prints_one_blocked_json(self):
        source=Path(a.__file__).read_bytes(); tree=ast.parse(source)
        imported=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imported.update(n.name.split('.')[0] for n in node.names)
            if isinstance(node,ast.ImportFrom):imported.add((node.module or '').split('.')[0])
        self.assertFalse(imported & {'urllib','requests','http','socket','backend','ops','pandas','numpy'})
        with tempfile.TemporaryDirectory() as tmp:
            before=list(Path(tmp).rglob('*'))
            result=subprocess.run([sys.executable,'-B','-','--runtime-root',tmp],input=source,capture_output=True,check=False)
            self.assertEqual(result.returncode,2); self.assertEqual(result.stderr,b'')
            value=json.loads(result.stdout); self.assertEqual(value['state'],'BLOCKED_CANONICAL_CLOSE_SOURCE_AUDIT')
            self.assertFalse(value['strategy_ready']); self.assertFalse(value['chronology_economic_eligible'])
            self.assertEqual(value['remote_writes'],0); self.assertEqual(value['network_calls'],0)
            self.assertEqual(before,list(Path(tmp).rglob('*')))


if __name__=='__main__':unittest.main()
