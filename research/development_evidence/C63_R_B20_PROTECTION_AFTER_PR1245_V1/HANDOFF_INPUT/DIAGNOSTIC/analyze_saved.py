"""Read-only grouping of sealed R/C63 records. No strategy, price replay, or I/O to GitHub."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def analyze(archive: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        def read(name: str):
            data = source.read(name)
            return json.loads(gzip.decompress(data) if name.endswith('.gz') else data)
        hashes = read('evidence/EVIDENCE_HASHES.json')
        for name, digest in hashes.items():
            actual = hashlib.sha256(source.read('evidence/' + name)).hexdigest()
            if actual != digest:
                raise ValueError(f'Sealed evidence hash mismatch: {name}')
        spec = read('evidence/SPEC.json')
        summary = read('evidence/SUMMARY.json')
        records, periods = [], {}
        for period in ('DEV2025', 'SEEN2026'):
            result = read(f'evidence/R/{period}/RESULT.json.gz')
            accounting = read(f'evidence/R/{period}/ACCOUNTING_C63.json')
            deltas = {x['origin']: x['delta_bps'] for x in accounting['concentration']['origin_deltas']}
            rows = []
            for trade in result['trades']:
                context = trade['runner_context']
                if not context['extended']:
                    continue
                observations = {x['held']: x for x in context['observations']}
                if 19 not in observations or 20 not in observations:
                    raise ValueError('Missing held19/held20 observation')
                c19, c20 = observations[19]['close'], observations[20]['close']
                crossing = next((x for n, x in sorted(observations.items())
                                 if n > 20 and x['close'] < c20), None)
                early = crossing is not None and crossing['reason'] is None
                delta = deltas[trade['origin_key']]
                group = 'help' if delta > 1e-8 else 'harm' if delta < -1e-8 else 'unchanged'
                rows.append(dict(period=period, symbol=trade['symbol'], origin=trade['origin_key'],
                    original_entry_ts=trade['entry_ts'], c19=c19, c20=c20,
                    c20_gt_c19=c20 > c19, old_R_minus_C63_bps=delta, old_effect=group,
                    first_breach_held=None if crossing is None else crossing['held'],
                    first_breach_available_at=None if crossing is None else crossing['available_at'],
                    R_exit_already_signaled_at_first_breach=None if crossing is None else crossing['reason'],
                    breach_precedes_R_exit=early, old_R_final_held=len(observations)))
            if not math.isclose(math.fsum(r['old_R_minus_C63_bps'] for r in rows),
                                accounting['marked_delta_bps_not_realized'], abs_tol=1e-8):
                raise ValueError('Armed record attribution does not match sealed total')
            def group_stats(selection):
                return dict(n=len(selection),
                    help=sum(r['old_effect'] == 'help' for r in selection),
                    harm=sum(r['old_effect'] == 'harm' for r in selection),
                    unchanged=sum(r['old_effect'] == 'unchanged' for r in selection),
                    old_delta_sum_bps=math.fsum(r['old_R_minus_C63_bps'] for r in selection))
            periods[period] = dict(
                calendar={k: datetime.fromtimestamp(v / 1000, timezone.utc).isoformat()
                          for k, v in spec['periods'][period].items()},
                maturity_progress={label: group_stats([r for r in rows if r['c20_gt_c19'] == value])
                                   for label, value in [('C20_GT_C19', True), ('C20_LE_C19', False)]},
                maturity_anchor_breach={label: group_stats([r for r in rows if r['breach_precedes_R_exit'] == value])
                                        for label, value in [('EARLIER_THAN_R_EXIT', True), ('NO_EARLIER_TRIGGER', False)]},
                armed=group_stats(rows), saved_cost_bridge=accounting['bridges']['marked']['delta'],
                saved_same_calendar_risk=accounting['same_calendar_risk'])
            records.extend(rows)
        pooled = {v: math.fsum(summary['periods'][p]['snapshots'][v]['terminal_net_bps']
                               for p in ('DEV2025', 'SEEN2026')) for v in ('C63', 'R')}
        pooled['R_minus_C63_bps'] = pooled['R'] - pooled['C63']
        out = dict(status='SAVED_RECORD_GROUPING_ONLY', independent=False,
            new_candidates=0, new_economic_replays=0, new_model_calls=0,
            remote_writes=0, checked_sealed_hashes=len(hashes), armed_record_count=len(records),
            input_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            frozen_source_commit=spec['source_commit'],
            verified_merge_commit='144ebe51cff77113a155a00b3dde4a99145a450b',
            periods=periods, disjoint_window_arithmetic_not_continuous_backtest=pooled,
            limitations=[
              'Old final R-minus-C63 results are development labels, never executable features.',
              'Two diagnostic predicates were examined; this selection history must be retained.',
              'Earlier trigger coverage is not loss recovery, fill simulation, or proof of a good guard.',
              'Native OHLC/EMA/momentum were not independently reconstructed in this analysis.',
              'No hypothetical exit price or candidate net PnL has been calculated.',
              'The two source windows are non-contiguous; sums are not continuous account performance.'
            ])
        (destination / 'DIAGNOSTIC.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        with (destination / 'ARMED_RECORDS_37.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, default=Path('c63_risk_diagnostic'))
    args = parser.parse_args()
    output = analyze(args.archive, args.output)
    print(json.dumps({k: output[k] for k in ('status', 'checked_sealed_hashes', 'armed_record_count',
                      'new_candidates', 'new_economic_replays', 'disjoint_window_arithmetic_not_continuous_backtest')}, indent=2))
