"""Bounded Q0 diagnosis; no Q2 rule or candidate economics are implemented.

Reuses sealed ledgers, the existing DEV loader and accounting. Historical
outcomes annotate observations only. A failed diagnostic is not an economic
rejection and consumes no new strategy hypothesis.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from backend.research.rebuild import break_channel_q1_v1 as previous
from backend.research.rebuild import break_channel_q2_observability_v1 as observability
from backend.research.rebuild import break_channel_q2_loss_analysis_v1 as losses

prior = previous.prior
old = previous.old
ROOT = old.ROOT
OUTPUT = 'research/development_evidence/BREAK_CHANNEL_Q2_DIAGNOSIS_20260906_V1'
SOURCE = OUTPUT + '/SOURCE_TO_CAUSE.md'
Q0_SEAL = 'a5509c187f94b163f8e0428be876f9ba0f64540142d2be45ff883238d5d32018'
Q1_SEAL = '3ef91131a4f248475d7db5da0813df46ef0c23da1cf43641cda706196eb65e6b'
Q1_DURABLE_SHA = '3fb9b9c56016392b2efd9ca2e355d5fa6e5800390ea04ac1bd52df72141e31bc'
Q1_AUDIT_SHA = 'a9112efa5cd58086f48e0b7ee065f7dff0845ee6e128a6a32611c9105086b055'
BUDGET = {'previous_applications': 25, 'conditional_Q2_maximum': 1,
          'new_trials_consumed': 0, 'cumulative_after': 25,
          'conditional_allocation_unconsumed': 1,
          'Q2_implemented': False, 'Q2_economics_computed': False,
          'Q3_authorized': False, 'automatic_extension': False,
          'paid_external_AI_calls': 0}
CODE = ['backend/research/rebuild/' + name for name in (
    'break_channel_q2_diagnosis_v1.py', 'break_channel_q2_observability_v1.py',
    'break_channel_q2_loss_analysis_v1.py', 'test_break_channel_q2_diagnosis_v1.py',
    'test_break_channel_q2_observability_v1.py', 'test_break_channel_q2_loss_analysis_v1.py')]


def read(path):
    return json.loads((ROOT / path).read_text())


def read_lines(path):
    return [json.loads(line) for line in gzip.decompress((ROOT / path).read_bytes()).splitlines()]


def authorize():
    prior.authorize()
    previous.authorize()
    q0 = read(prior.OUTPUT + '/receipt.json')
    q1 = read(previous.OUTPUT + '/receipt.json')
    for value, seal, label in ((q0, Q0_SEAL, 'Q0'), (q1, Q1_SEAL, 'Q1')):
        old.probe.verify_seal(value, label)
        if value['receipt_sha256'] != seal:
            raise RuntimeError('DIAGNOSIS_PARENT_IDENTITY:' + label)
    if q0['budget']['cumulative_after'] != 24 or q1['budget']['cumulative_after'] != 25:
        raise RuntimeError('DIAGNOSIS_PRIOR_COUNT_DRIFT')
    if q0['comparisons']['P_to_Q']['decision']['decision'] != 'DEV_INCONCLUSIVE':
        raise RuntimeError('DIAGNOSIS_Q0_STATUS_DRIFT')
    if q1['decision']['decision'] != 'DEV_REJECT' or q1['decision']['research_reference'] != 'Q0':
        raise RuntimeError('DIAGNOSIS_Q1_STATUS_DRIFT')
    durable = read(previous.OUTPUT + '/durable_receipt.json')
    old.probe.verify_seal(durable, 'Q1_DURABLE')
    if durable['result_receipt_sha256'] != Q1_SEAL:
        raise RuntimeError('DIAGNOSIS_DURABLE_PARENT_DRIFT')
    protected = {}
    for group in ('files_sha256', 'code_files_sha256', 'preserved_files_sha256'):
        protected.update(durable[group])
    protected[previous.OUTPUT + '/durable_receipt.json'] = Q1_DURABLE_SHA
    protected[previous.OUTPUT + '/POST_RUN_AUDIT.md'] = Q1_AUDIT_SHA
    for path, sha in protected.items():
        if old.file_sha(ROOT / path) != sha:
            raise RuntimeError('DIAGNOSIS_PROTECTED_BYTES:' + path)
    return q0, q1, read(prior.CONTRACT), protected


def decision():
    return {'Q2_status': 'NOT_RUN_NO_SUPPORTED_INTERVENTION',
            'economic_decision': 'NOT_RUN', 'research_reference': 'Q0',
            'Q0_original_status': 'DEV_INCONCLUSIVE', 'Q1_original_status': 'DEV_REJECT',
            'scope': 'THREE_NATIVE_STATES_AND_CONTINUOUS_RISK_OBSERVATIONS_ONLY',
            'cause': 'Loss-run damage exists, but the inspected pre-loss states do not reliably separate losses from normal/large winners across reused DEV periods.',
            'Q2_rule': None, 'Q2_goal_or_tradeoff_preregistered': False,
            'candidate_implementation_allowed_by_this_report': False,
            'no_general_channel_impossibility_claim': True,
            'no_automatic_next_candidate': True,
            'formal_pass': False, 'operating_adoption': False,
            'code_test_PASS_is_economic_PASS': False}


def report(r, obs, run):
    f = lambda x: 'NOT_RUN' if x is None else f'{x:,.4f}'
    lines = ['# Q0 losing-run diagnosis; Q2 not implemented', '',
        '**No new strategy economics were measured.** Q0 still has +4,076.1430 closed trade-bps, 5,224.6878 maximum grouped losing-run loss and 6,801.4788 maximum daily marked drawdown. The observed pre-loss states do not justify Q2. Q1 DEV_REJECT and Q0 DEV_INCONCLUSIVE are preserved.', '',
        'This completes the user-authorized no-evidence branch: actual ledger/cause discrimination, source linkage, regression and remote reproduction. It is not a claim that a Q2 economic experiment was completed or rejected.', '',
        'All figures below use the original common calendar and equal-notional research costs. They are trade-bps, not account return, account MDD or equal-risk performance.', '',
        '| Metric | P, preserved | Q0, preserved | Q2 |', '|---|---:|---:|---|']
    metrics = r['preserved_economics']; di = r['preserved_diagnostics']; md = r['preserved_marked_diagnostics']
    rows = [
        ('Closed / open', lambda s: str(metrics[s]['base_cost']['completed_T']) + ' / ' + str(metrics[s]['open_observations']['T'])),
        ('Win rate, %', lambda s:f(100*metrics[s]['base_cost']['win_rate'])),
        ('Gross expectancy, bps/trade',lambda s:f(metrics[s]['base_cost']['gross_expectancy_bps'])),
        ('Net expectancy, bps/trade',lambda s:f(metrics[s]['base_cost']['expectancy_bps_per_trade'])),
        ('PF',lambda s:f(metrics[s]['base_cost']['PF'])),
        ('Realized payoff',lambda s:f(metrics[s]['base_cost']['realized_payoff'])),
        ('Cost2 expectancy, bps/trade',lambda s:f(metrics[s]['cost2x']['expectancy_bps_per_trade'])),
        ('Closed net trade-bps',lambda s:f(metrics[s]['base_cost']['net_bps'])),
        ('Hypothetical unfinished net mark',lambda s:f(metrics[s]['open_observations']['hypothetical_liquidation_net_mark_bps'])),
        ('Closed plus hypothetical terminal net',lambda s:f(metrics[s]['closed_plus_hypothetical_terminal_mark_bps'])),
        ('Daily marked DD trade-bps',lambda s:f(md[s]['marked_DD_trade_sum_bps'])),
        ('Maximum grouped loss-run trade-bps',lambda s:f(di[s]['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'])),
        ('Exposure symbol-days',lambda s:f(metrics[s]['total_exposure_symbol_days'])),
        ('Maximum simultaneous symbols',lambda s:str(metrics[s]['exposure']['max_simultaneous_symbols'])),
        ('Top-symbol positive-profit share',lambda s:f(metrics[s]['concentration']['top_one_symbol_profit_share'])),
        ('Top-decile winner profit share',lambda s:f(metrics[s]['concentration']['top_decile_winners_share'])),
    ]
    for label, getter in rows:
        lines.append('| ' + label + ' | ' + getter('P') + ' | ' + getter('Q0') + ' | NOT_RUN |')
    lines += ['', 'No Q2 common/new/removed trades, saved losses, lost winner profit, cost delta or candidate confidence interval exists. These quantities are **NOT_RUN**, not zero or economic REJECT. Q0 remains unchanged by byte identity; no new profit-preservation claim is inferred from a hypothetical filter.', '',
        '## All losing and winning runs', '',
        'Exact simultaneous exits form one group. A negative group can contain an individual winning trade, and a positive group can contain an individual loss. Individual loss/win cohorts remain separate from group-run membership. Run labels and future outcomes are diagnostic labels only.', '',
        '| Sign/run | Groups / trades | Closed net | P same-calendar marked change | Q0 same-calendar marked change | Interval, UTC |', '|---|---:|---:|---:|---:|---|']
    for v in run['all_closed_sign_runs']:
        w = v['daily_enclosing_window']; stages = w['stages']
        lines.append(f"| {v['sign']} {v['run_id']} | {v['groups_n']} / {v['T']} | {f(v['net_bps'])} | {f(stages['P']['totals']['delta']['net_bps'])} | {f(stages['Q0']['totals']['delta']['net_bps'])} | {w['window_start_utc']} to {w['window_end_utc']} |")
    lines += ['', 'Windows enclose each run at UTC daily boundaries and mark every position, including positions already open or newly entered. Adjacent padded windows can overlap; do not sum them as disjoint PnL contributions. Their closed-run totals are not the same quantity as portfolio marked changes.', '',
        'The 16-loss February–April run has no exact same-time multi-symbol exit. Its largest loss is 1,078.8754 trade-bps, 20.65% of that run. Twelve protective-stop exits contribute -4,636.0630 and four bearish exits -588.6248. Therefore neither one outlier nor exact simultaneous closure fully explains it. The separate May–July daily marked drawdown includes other positions and coincident daily losses.', '',
        'Daily per-symbol negative marked contributions include price movement and hypothetical roundtrip cost changes; they do not establish simultaneous intrabar price losses. Full daily contributions, concurrency bins, all drawdown episodes, monthly outcomes, and top losses are in LOSS_RUNS.json.gz.', '',
        '## Pre-loss discrimination', '',
        '| Native observable | All UP true / total | Individual losses true / 57 | Individual wins true / 29 | Top three winners true / 3 |', '|---|---:|---:|---:|---:|']
    for state, cohorts in obs['cohort_state_counts'].items():
        values = [cohorts[k] for k in ('all_eligible_UP','closed_losses','closed_wins','top3_winners')]
        lines.append('| ' + state + ' | ' + ' | '.join(f"{v['true']} / {v['N']}" for v in values) + ' |')
    lines += ['', 'Unknown history stays unknown: successive-UP comparison has two unknown losses; the prior-position condition has six unknown losses and one unknown win. Counts with all-observation denominators above do not silently classify unknowns as false. OBSERVABILITY.json.gz reports true/false/unknown counts and all feature lineage.', '',
        'The last-DOWN unreclaimed state marks all three biggest winners. The nonascending prepared-UP state concentrates in the worst run but fails to separate losses in subsequent quarters. The prior-stop same/lower-channel state also occurs among normal and large wins. A previous executed-position feature would additionally depend on a changed child ownership path; it is not a ready-made static filter.', '',
        'Initial stop distance and confirmation movement were inspected continuously without choosing thresholds. Their loss/win distributions overlap. No risk cap, wait length, new indicator or alternate cutoff is selected from the realized worst losses.', '',
        'Quarters are defined by original signal time within repeatedly used DEV; Q1 has no winners, so within-quarter discrimination is unidentifiable there. Q2/Q3/Q4 are descriptive calendar quarters, not Q2/Q3 candidate names and not independent OOS.', '',
        '## Ordering and evidence limits', '']
    worst = max((v for v in run['all_closed_sign_runs'] if v['sign']=='LOSS'), key=lambda v:-v['net_bps'])
    lines += ['| Fixed Q0 interval | Marked net change | Negative days | Negative days with multiple losing symbols | Their net contribution |', '|---|---:|---:|---:|---:|']
    for name,w in [('Largest closed loss run, daily envelope',worst['daily_enclosing_window']),('Maximum marked DD',run['marked_drawdown']['worst'])]:
        a=w['concurrent_mark_summary']
        lines.append(f"| {name} | {f(w['stages']['Q0']['totals']['delta']['net_bps'])} | {a['negative_mark_days']} | {a['negative_mark_days_with_multiple_negative_symbols']} | {f(a['negative_mark_days_with_multiple_negative_symbols_net_sum_bps'])} |")
    dd_concurrent=run['marked_drawdown']['worst']['concurrent_mark_summary']
    lines += ['', f"The DD interval has multiple-symbol negative contributions on {dd_concurrent['negative_mark_days_with_multiple_negative_symbols']} of {dd_concurrent['negative_mark_days']} negative days ({100*dd_concurrent['negative_mark_days_with_multiple_negative_symbols_net_sum_bps']/dd_concurrent['negative_mark_day_net_sum_bps']:.2f}% of negative-day net losses). There are {dd_concurrent['multiple_negative_symbol_days']} such days across the whole interval, including a portfolio-positive day. The worst closed-run envelope has them on 8 of 28 negative days. These are different loss structures, not one causal contribution obtained by subtracting maximum statistics. Realized same-day co-loss is an outcome observation, not a pre-entry gate.", '']
    o = run['ordering_sensitivity']
    lines += [f"Fixed diagnostic shuffle: seed {o['seed']}, {o['permutations']:,} permutations of the unchanged {run['summary']['exit_groups']} simultaneous-exit group totals. Fractions reaching the observed maximum length and loss are {100*o['exchangeable_shuffle_fraction_max_length_at_least_observed']:.3f}% and {100*o['exchangeable_shuffle_fraction_max_loss_at_least_observed']:.3f}%. This preserves within-group values but destroys market, time and ownership dependence. Exchangeability is unverified: these are descriptive ordering fractions, not formal p-values, independent samples or proof of randomness.", '',
        'Small positive groups can break runs mechanically; two individually positive gross trades become net losses after costs, totaling -58.8990 trade-bps. Removing small winners or changing exit ordering was not replayed. Original group sign, individual outcome, calendar valuation and cost classifications are retained separately.', '',
        'The existing source provides daily channel and confirmation structure, not a proven losing-run remedy. SOURCE_TO_CAUSE.md separates source facts, ZEL design priors and these data observations. No unsupported rule is attributed to the authors. This diagnosis is limited to the inspected mechanisms and does not conclude that Q0 or all future improvements are impossible.', '',
        '## Completion and allocation', '',
        'Q2 economic status: **NOT_RUN_NO_SUPPORTED_INTERVENTION**. No candidate specification or outcome-dependent trade-off was invented. Existing 25 trials preserved; newly measured strategies 0; cumulative25; one conditional slot unconsumed. It is not automatically rolled into another named candidate. Q3 and automatic retuning remain unauthorized.', '',
        'Regression/CI checks establish diagnostic reproducibility, not economic adoption. validation/OOS decoded0; new paid external AI0; Gemini actual videoNOT_RUN without run/timestamp evidence. Top5/G5B/operating files are unchanged. executionNONE/orderBLOCKED/liveBLOCKED. Formal/unused-validation readiness is not advanced.', '']
    return '\n'.join(lines).encode()


def run(data_dir, verify_only=False):
    q0, q1, spec, protected = authorize()
    out = ROOT / OUTPUT
    policy, dev, four, _, access = prior.inputs.load_inputs(data_dir)
    if policy['combined_data_sha256'] != spec['data_sha256'] or policy['cost_binding_sha256'] != spec['cost_sha256']:
        raise RuntimeError('DIAGNOSIS_DATA_COST_DRIFT')
    if sorted(four) != spec['symbols']:
        raise RuntimeError('DIAGNOSIS_UNIVERSE_DRIFT')
    start, end = spec['evaluation_interval_ms']
    inputs = {}
    for name in ('trades','open_observations','events','daily_bars','daily_valuation'):
        a = q0['artifacts'][name]
        if old.file_sha(ROOT / a['path']) != a['file_sha256']:
            raise RuntimeError('DIAGNOSIS_SEALED_LEDGER_DRIFT:' + name)
        inputs[name] = read_lines(a['path'])
    by_stage = lambda name: {s:[v for v in inputs[name] if v['comparison_stage']==label]
                           for s,label in (('P','P'),('Q0','Q'))}
    ts, opened, events, daily = [by_stage(n) for n in ('trades','open_observations','events','daily_valuation')]
    bars = {s:[v for v in inputs['daily_bars'] if v['symbol']==s] for s in spec['symbols']}
    with old.probe.io_boundary([], out):
        obs = observability.build(four, ts['Q0'], events['Q0'], eval_start_ms=start, eval_end_ms=end)
        loss = losses.build(ts, opened, bars, daily, dev['cost_by_symbol'], start, end, events_by_stage=events)
    artifacts = {}
    for name, value in (('OBSERVABILITY.json.gz',obs),('LOSS_RUNS.json.gz',loss)):
        path = out / name
        raw = old.probe.canonical(value)
        payload = path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
        if gzip.decompress(payload) != raw:
            raise RuntimeError('DIAGNOSIS_REPRODUCTION_DRIFT:' + name)
        old.probe.write_immutable(path, payload, verify_only=verify_only)
        artifacts[name] = {'path':str(path.relative_to(ROOT)), 'file_sha256':old.file_sha(path)}
    q0_labels = {'P':'P','Q0':'Q'}
    r = old.seal({'batch_id':'BREAK_CHANNEL_Q2_DIAGNOSIS_20260906_V1',
        'diagnostic_revision':{'previous_local_draft_seal':'edca7e42e4721e6ddca361acd661dfe3b804825d18737a2c5afb91b72a0a474d',
            'correction':'Report now distinguishes19 portfolio-negative co-loss days from20 total co-loss days; ledger values and all diagnostic predicates unchanged. No strategy trial or retuning.'},
        'scope':'EXISTING_PARENT_DIAGNOSIS_NO_NEW_STRATEGY_ECONOMICS',
        'decision':decision(), 'budget':BUDGET,
        'Q0_receipt_sha256':q0['receipt_sha256'], 'Q1_receipt_sha256':q1['receipt_sha256'],
        'data_sha256':spec['data_sha256'], 'cost_sha256':spec['cost_sha256'],
        'symbols':spec['symbols'], 'evaluation_interval_ms':[start,end],
        'preserved_economics':{s:q0['metrics'][label] for s,label in q0_labels.items()},
        'preserved_diagnostics':{s:q0['diagnostics'][label] for s,label in q0_labels.items()},
        'preserved_marked_diagnostics':{s:q0['marked_diagnostics'][label] for s,label in q0_labels.items()},
        'preserved_P_to_Q0_uncertainty':q0['comparisons']['P_to_Q']['uncertainty'],
        'candidate_economics':None, 'candidate_attribution':None, 'candidate_uncertainty':None,
        'artifacts':artifacts, 'source_access':access,
        'source_note_sha256':old.file_sha(ROOT / SOURCE),
        'code_files_sha256':{p:old.file_sha(ROOT/p) for p in CODE},
        'preserved_files_sha256':protected,
        'data_reuse_history':q1['data_reuse_history'] + [{'batch':'BREAK_CHANNEL_Q2_DIAGNOSIS_20260906_V1','kind':'all-run/source/observability analysis only','new_trials_consumed':0,'independent_OOS':False}],
        'validation_rows_decoded':0,'OOS_rows_decoded':0,'Gemini_actual_video':'NOT_RUN',
        'paid_external_AI_calls':0,'G5B_changed':False,'operating_changed':False,'G6_authorized':False,
        **old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'analysis.json',old.probe.canonical(r),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(r,obs,loss),verify_only=verify_only)
    return r


if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true')
    args=ap.parse_args();result=run(args.data_dir.resolve(),args.verify_only)
    print(json.dumps({'analysis':result['receipt_sha256'],'decision':result['decision'],'budget':result['budget']},indent=2))
