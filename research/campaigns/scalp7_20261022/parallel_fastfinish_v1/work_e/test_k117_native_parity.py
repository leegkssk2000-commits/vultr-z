"""Synthetic native-opportunity checks: real HG and frozen ObjectiveLifetime.

Only indicator enrichment is scripted. No market dataset, economic replay,
collector, network, workflow or prospective credit is used. The reference
comparison executes the frozen AST insertion, not build()'s unavailable
state_lifetime_adapter import; execution._single is a signal recorder only.
"""
import ast
from copy import deepcopy
from datetime import datetime
import hashlib
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import k117_adapter as k


D = k.dependencies()
SYMBOL = 'BTC-USDT'
T = (int(datetime.fromisoformat(D.manifest['freeze_at_utc']).timestamp() * 1000) // k.TF + 2) * k.TF
DAY = 86_400_000
END = (T // DAY - 1) * DAY
FIT = {'train_start_ms': END - 90 * DAY, 'train_end_ms': END,
       'last_fit_observation_ms': END - DAY, 'train_rows': 90,
       'training_feature_sha256': '1' * 64, 'disp_q67': 1.,
       'meanabs_q85': 1., 'vol_q25': 1., 'vol_q67': 2.}
FIT['sha256'] = k.digest(FIT)
SOURCE = {'identity_sha256': '2' * 64, 'volume_units': 'BASE_ASSET',
          'synthetic_fill': False, 'stale_ms': 90_000,
          'stale_authority': 'SYNTHETIC_TEST_ONLY', 'higher_timeframe_complete': True}
COST = {'source_sha256': '3' * 64, 'available_ts_ms': T, 'fee_bps': 6.,
        'funding_bps': 1., 'slippage_bps': 3., 'kind': 'FIXTURE_ONLY'}
OBJECTIVE_SHA = '40659bc91044cca35ea6fc0aad383487b59ac16ec8aeb74639f8f5663e131bb7'
NATIVE_FUNCTION_SHA = '9cab68472492d27a0a990cdce73e51ecd8009866f2ba12fc3a29b02381094252'


def candle(index, *, o=100., h=101., l=99., c=100., step=None,
           regime='TREND_DISPERSED', target=110., side=1):
    """A weak bootstrap, or rising GMMA/EMA20 with explicit OHLC geometry."""
    opened = T + (index - 122) * k.TF
    row = {'open_ts_ms': opened, 'close_ts_ms': opened + k.TF,
           'available_ts_ms': opened + k.TF, 'feature_available_ts_ms': opened + k.TF,
           'segment_id': 0, 'open': o, 'high': h, 'low': l, 'close': c,
           'volume': 1000., 'atr': 2., 'adx14': 20. if step is None else 35.,
           'g20': 99. if step is None else 100. + step,
           'hi20': target, 'lo20': 90., 'regime': regime,
           'regime_available_ts_ms': opened + k.TF,
           'regime_fit_end_ts_ms': END, 'regime_spec_sha256': FIT['sha256']}
    for rank, period in enumerate(D.positive.LONG_GMMA):
        row['g' + str(period)] = 99. if step is None else 105. - rank + step * .1
    if side == -1:
        for key in ('open', 'close', 'g20', *('g' + str(n) for n in D.positive.LONG_GMMA)):
            row[key] = 200. - row[key]
        row['high'], row['low'] = 200. - row['low'], 200. - row['high']
        row['hi20'], row['lo20'] = 200. - row['lo20'], 200. - row['hi20']
    return row


def bootstrap(side=1):
    return [candle(i, side=side) for i in range(122)]


def touch(side=1, **kwargs):
    return candle(122, o=100., h=102., l=99., c=101., step=0, side=side, **kwargs)


def turn(side=1, **kwargs):
    return candle(123, o=101., h=104., l=100., c=103., step=1, side=side, **kwargs)


def feed(adapter, rows):
    frame = D.pd.DataFrame(rows)
    # Preserve raw validation, clocks, fit checks and both policy state machines.
    with patch.object(D.positive, 'enriched_segments', side_effect=lambda checked: [checked.copy()]):
        return adapter.on_bar(symbol=SYMBOL, frame=frame,
                              asof_ms=rows[-1]['available_ts_ms'], source=SOURCE,
                              fit=FIT, frozen_cost_bps=10.)


def normalized_native(signal):
    result = deepcopy(signal)
    result['identity'] = k.IDENTITY
    result['max_hold_bars'] = 50
    result['meta']['lifecycle_adapter_parent_identity'] = D.positive.KELTNER_PARENT
    return result


def frozen_opportunity_reference(rows):
    """Use the unchanged frozen transformer; stub only trade execution.

    This intentionally does not claim to exercise frozen build()'s code-signature
    dependency, which is absent from this checkout. Both source bytes and the
    insertion counts are checked independently before compiling its AST.
    """
    from ops import scalp7_keltner_fresh_touch_successor_v1 as successor

    objective_source = (k.HERE / 'frozen' / 'objective_lifetime.py').read_bytes()
    if hashlib.sha256(objective_source).hexdigest() != OBJECTIVE_SHA:
        raise AssertionError('frozen objective bytes changed')
    native_source = inspect.getsource(successor._fresh_touch_successor)
    if hashlib.sha256(native_source.encode()).hexdigest() != NATIVE_FUNCTION_SHA:
        raise AssertionError('frozen native function changed')
    frozen_tree = ast.parse(objective_source)
    build = next(node for node in frozen_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build')
    transformer = next(node for node in build.body if isinstance(node, ast.ClassDef) and node.name == 'Patch')
    counts = {'init': 0, 'after': 0, 'veto': 0}
    scope = {'ast': ast, 'counts': counts}
    exec(compile(ast.Module(body=[deepcopy(transformer)], type_ignores=[]),
                 'frozen_objective_patch_test.py', 'exec'), scope)
    tree = scope['Patch']().visit(ast.parse(native_source))
    if counts != {'init': 1, 'after': 1, 'veto': 1}:
        raise AssertionError(counts)
    ast.fix_missing_locations(tree)
    recorded, objective_events = [], []

    def record_signal(signal, *args):
        recorded.append(deepcopy(signal))
        return None, None, int(signal['signal_ts_ms']), None

    native_scope = dict(vars(successor))
    native_scope.update(_ObjectiveLifetime=D.objective, _objective_events=objective_events,
                        execution=SimpleNamespace(_frame_records=D.execution._frame_records,
                                                  _single=record_signal))
    exec(compile(tree, 'frozen_opportunity_reference_test.py', 'exec'), native_scope)
    frame = D.pd.DataFrame(rows)
    with patch.object(D.positive, 'enriched_segments', side_effect=lambda checked: [checked.copy()]):
        result = native_scope['_fresh_touch_successor'](
            {SYMBOL: frame}, {SYMBOL: 10.},
            [{'label': 'SYNTHETIC_ONLY', 'partition': 'validation', 'start_ms': T,
              'end_ms': int(rows[-1]['close_ts_ms']) + k.TF}])
    if result['trades'] or result['unresolved']:
        raise AssertionError('economic execution is forbidden in this reference')
    return recorded, objective_events


class NativeOpportunityParity(unittest.TestCase):
    def start(self, side=1):
        adapter, rows = k.Adapter(enabled=True, fixture=True), bootstrap(side)
        self.assertEqual(feed(adapter, rows)['status'], 'NO_SIGNAL')
        self.assertFalse(adapter.state['signals'][SYMBOL]['bootstrap_unknown'])
        return adapter, rows

    def append(self, adapter, rows, row):
        rows.append(row)
        return feed(adapter, rows)

    def test_actual_hg_touch_then_turn_emits_both_sides(self):
        for side in (1, -1):
            with self.subTest(side=side):
                adapter, rows = self.start(side)
                self.assertEqual(self.append(adapter, rows, touch(side))['status'], 'NO_SIGNAL')
                self.assertEqual(adapter.state['signals'][SYMBOL]['hg']['stage'], 1)
                row = turn(side)
                actual = self.append(adapter, rows, row)
                self.assertEqual(actual['status'], 'SIGNAL', actual)
                reference = 99. if side == 1 else 101.
                expected = D.native._keltner_parent_signal(SYMBOL, row, side, reference,
                                                          'TREND_DISPERSED', row['close_ts_ms'], 10.)
                self.assertEqual(actual['signal'], normalized_native(expected))
                self.assertFalse(adapter.state['positions'])
                self.assertIsNone(adapter.state['NAV'])

    def test_known_veto_without_hit_keeps_original_touch(self):
        adapter, rows = self.start()
        self.append(adapter, rows, touch())
        self.assertEqual(self.append(adapter, rows, turn(regime='TREND_COHERENT'))['status'], 'NO_SIGNAL')
        saved = adapter.state['signals'][SYMBOL]
        self.assertEqual(saved['hg']['stage'], 1)
        self.assertIsNotNone(saved['objective']['first_veto_ts'])
        self.assertIsNone(saved['objective']['first_hit_ts'])
        signal = self.append(adapter, rows, candle(124, o=103., h=106., l=102., c=105., step=2))
        self.assertEqual(signal['status'], 'SIGNAL', signal)
        self.assertEqual(signal['signal']['invalidation_price'], 99.)
        self.assertFalse(adapter.state['signals'][SYMBOL]['objective']['events'])

    def test_hit_without_known_veto_does_not_expire(self):
        adapter, rows = self.start()
        self.append(adapter, rows, candle(122, o=100., h=111., l=99., c=101., step=0))
        self.assertEqual(adapter.state['signals'][SYMBOL]['objective']['first_hit_ts'], T + k.TF)
        signal = self.append(adapter, rows, candle(123, o=101., h=113., l=100., c=112., step=1))
        self.assertEqual(signal['status'], 'SIGNAL', signal)
        self.assertFalse(adapter.state['signals'][SYMBOL]['objective']['events'])

    def test_veto_then_frozen_objective_suppresses_turn_and_requires_new_touch(self):
        for side in (1, -1):
            with self.subTest(side=side):
                adapter, rows = self.start(side)
                self.append(adapter, rows, touch(side))
                self.append(adapter, rows, turn(side, regime='RANGE_MIXED', target=109.))
                result = self.append(adapter, rows, candle(124, o=103., h=111., l=102., c=110., step=2,
                                                          target=120., side=side))
                self.assertEqual(result['status'], 'NO_SIGNAL')
                saved = adapter.state['signals'][SYMBOL]
                self.assertEqual(saved['hg']['stage'], 0)
                event, = saved['objective']['events']
                self.assertEqual(event['frozen_prior20_objective'], 110. if side == 1 else 90.)
                self.assertEqual(event['first_known_veto_ts_ms'], T + 2 * k.TF)
                self.assertEqual(event['first_objective_hit_ts_ms'], T + 3 * k.TF)
                self.assertEqual(event['reason'], 'PRIOR_OBJECTIVE_COMPLETE_AFTER_KNOWN_VETO')
                self.assertFalse(adapter.state['pending'])
                no_touch = candle(125, o=110., h=113., l=104., c=112., step=3, target=120., side=side)
                self.assertEqual(self.append(adapter, rows, no_touch)['status'], 'NO_SIGNAL')
                new_touch = candle(126, o=106., h=108., l=103., c=105., step=4, target=120., side=side)
                self.assertEqual(self.append(adapter, rows, new_touch)['status'], 'NO_SIGNAL')
                new_turn = candle(127, o=105., h=111., l=104., c=110., step=5, target=120., side=side)
                signal = self.append(adapter, rows, new_turn)
                self.assertEqual(signal['status'], 'SIGNAL', signal)
                self.assertEqual(signal['signal']['invalidation_price'], 103. if side == 1 else 97.)

    def test_hit_before_known_veto_expires_on_veto_clock(self):
        adapter, rows = self.start()
        self.append(adapter, rows, candle(122, o=100., h=111., l=99., c=101., step=0))
        result = self.append(adapter, rows, candle(123, o=101., h=113., l=100., c=112., step=1,
                                                  regime='COMPRESSION', target=120.))
        self.assertEqual(result['status'], 'NO_SIGNAL')
        event, = adapter.state['signals'][SYMBOL]['objective']['events']
        self.assertEqual(event['first_objective_hit_ts_ms'], T + k.TF)
        self.assertEqual(event['expired_ts_ms'], T + 2 * k.TF)
        self.assertEqual(event['reason'], 'KNOWN_VETO_WITH_OBJECTIVE_ALREADY_COMPLETE')
        self.assertEqual(adapter.state['signals'][SYMBOL]['hg']['stage'], 0)

    def test_unknown_turn_context_can_retry_without_losing_native_opportunity(self):
        adapter, rows = self.start()
        self.append(adapter, rows, touch())
        before = deepcopy(adapter.state['signals'][SYMBOL])
        bad = turn()
        bad['regime_available_ts_ms'] += 1
        result = self.append(adapter, rows, bad)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(adapter.state['signals'][SYMBOL], before)
        rows[-1] = turn()
        self.assertEqual(feed(adapter, rows)['status'], 'SIGNAL')

    def test_unknown_regime_labels_hold_and_allow_same_bar_recovery(self):
        for regime in ('UNKNOWN', 'UNRECOGNIZED_SYNTHETIC_REGIME'):
            with self.subTest(regime=regime):
                adapter, rows = self.start()
                self.append(adapter, rows, touch())
                before = deepcopy(adapter.state['signals'][SYMBOL])
                result = self.append(adapter, rows, turn(regime=regime))
                self.assertEqual(result['status'], 'UNKNOWN', result)
                self.assertEqual(result['action'], 'hold')
                self.assertEqual(adapter.state['signals'][SYMBOL], before)
                self.assertFalse(adapter.state['pending'])
                rows[-1] = turn()
                self.assertEqual(feed(adapter, rows)['status'], 'SIGNAL')

    def test_accepted_position_survives_objective_hit(self):
        adapter, rows = self.start()
        self.append(adapter, rows, touch())
        self.append(adapter, rows, turn(regime='TREND_COHERENT'))
        signal = self.append(adapter, rows, candle(124, o=103., h=106., l=102., c=105., step=2))['signal']
        stamp = signal['signal_ts_ms']
        opened = {'evidence_kind': 'OBSERVED_OPEN_EVENT', 'receipt_sha256': '4' * 64,
                  'source_ts_ms': stamp, 'received_at_ms': stamp, 'price': 105.}
        self.assertEqual(adapter.entry_open(symbol=SYMBOL, opened=opened,
                                            cost_model=COST, asof_ms=stamp)['status'], 'OPEN')
        self.assertTrue(adapter.state['signals'][SYMBOL]['hg']['episode_traded'])
        owned = deepcopy(adapter.state['positions'][SYMBOL])
        result = self.append(adapter, rows, candle(125, o=105., h=111., l=104., c=110., step=3))
        self.assertEqual(result['status'], 'NO_SIGNAL')
        self.assertEqual(adapter.state['positions'][SYMBOL], owned)
        self.assertFalse(adapter.state['signals'][SYMBOL]['objective']['events'])
        self.assertFalse(adapter.state['trades'])

    def test_restart_between_veto_and_hit_has_identical_policy_and_ledger(self):
        adapter, rows = self.start()
        self.append(adapter, rows, touch())
        self.append(adapter, rows, turn(regime='VOL_EXPANSION_MIXED'))
        restarted = k.Adapter(enabled=True, fixture=True, state=adapter.state)
        rows.append(candle(124, o=103., h=111., l=102., c=110., step=2))
        self.assertEqual(feed(adapter, rows), feed(restarted, rows))
        self.assertEqual(k.digest(adapter.state), k.digest(restarted.state))
        self.assertEqual(len(adapter.state['signals'][SYMBOL]['objective']['events']), 1)

    def test_frozen_full_loop_opportunity_matches_incremental(self):
        for side in (1, -1):
            with self.subTest(side=side):
                adapter, rows = self.start(side)
                self.append(adapter, rows, touch(side))
                signal = self.append(adapter, rows, turn(side))['signal']
                # A next-open bar lets the real frozen entry gate verify price.
                rows.append(candle(124, o=103., h=105., l=102., c=104., step=2, side=side))
                recorded, expired = frozen_opportunity_reference(rows)
                self.assertEqual(len(recorded), 1)
                self.assertEqual(signal, normalized_native(recorded[0]))
                self.assertFalse(expired)

    def test_frozen_full_loop_veto_expiry_matches_incremental(self):
        adapter, rows = self.start()
        for row in (touch(), turn(regime='RANGE_MIXED'),
                    candle(124, o=103., h=111., l=102., c=110., step=2)):
            self.assertEqual(self.append(adapter, rows, row)['status'], 'NO_SIGNAL')
        recorded, expired = frozen_opportunity_reference(rows)
        self.assertFalse(recorded)
        self.assertEqual(expired, adapter.state['signals'][SYMBOL]['objective']['events'])

    def test_frozen_source_bytes_still_match_original_pins(self):
        self.assertEqual(hashlib.sha256((k.HERE / 'frozen' / 'objective_lifetime.py').read_bytes()).hexdigest(), OBJECTIVE_SHA)
        self.assertEqual(hashlib.sha256((k.ROOT / 'backend/research/rebuild/scalp7_positive_lanes_v2.py').read_bytes()).hexdigest(),
                         'b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2')
        self.assertEqual(hashlib.sha256((k.ROOT / 'ops/scalp7_keltner_fresh_touch_successor_v1.py').read_bytes()).hexdigest(),
                         'e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855')
        k.pins()


if __name__ == '__main__':
    unittest.main(verbosity=2)
