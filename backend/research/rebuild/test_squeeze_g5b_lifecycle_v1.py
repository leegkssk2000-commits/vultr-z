"""Synthetic causal lifecycle parity, observable depth and capacity acceptance."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from unittest.mock import patch
import unittest

from backend.research.rebuild import squeeze_g5b_lifecycle_v1 as e
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture, COST


def entry(signal, eligible=True):
    return dict(signal=deepcopy(signal), source_signal_sha=e.digest(signal),
                context=dict(eligible=eligible, reason=None if eligible else 'FROZEN_REG71_VETO'))


def depth(stamp, price, *, qty=100., observed=None, suffix=''):
    return dict(source_ts=stamp, observed_ms=stamp if observed is None else observed,
                snapshot_id=str(stamp)+suffix, bids=[[price, qty]], asks=[[price, qty]])


def run(entries=(60,), *, n=150, bars=None, features=None, no_depth=(), stop=None):
    bars0, signal, features0 = fixture(n=n)
    bars = bars if bars is not None else bars0
    features = features if features is not None else features0
    adapter = e.LifecycleAdapter()
    for j in range(min(entries)-1, len(bars) if stop is None else stop):
        stamp = bars[j].open_ts+e.BAR
        candidates = [entry(dict(signal, signal_index=j, signal_ts=stamp,
                                 setup_id=str(j+1)))] if j+1 in entries else []
        costs = {key: dict(entry_ts=lot['entry_ts'], as_of_ms=stamp,
                          round_trip_bps=e.tm.cost_at(COST, lot['entry_ts'], stamp),
                          cost_sha=e.digest(COST), basis='SYNTHETIC')
                 for key, lot in adapter.lots.items() if lot['entry_ts'] is not None}
        adapter._observe_close('TEST', dict(close_ts=stamp, close=bars[j].close,
            momentum=features[j]['momentum'], daily=e.tm.daily_observation(bars, j),
            entries=candidates), observed_ms=stamp, checkpoint_costs=costs)
        if j+1 < len(bars) and j+1 not in no_depth:
            adapter.observe_depth('TEST', depth(stamp, bars[j+1].open))
    return adapter


class LifecycleTests(unittest.TestCase):
    def test_exact_selector_preserves_all_legacy_objects(self):
        for name in ('A1_KELTNER', 'A1_SUPERTREND', 'A1_BREAK'):
            legacy = object()
            self.assertIs(e.select_adapter(name, 'time_stop', legacy), legacy)
        self.assertIs(e.select_adapter(e.LANE_ID, e.ADAPTER_ID, None), e.LifecycleAdapter)
        with self.assertRaisesRegex(ValueError, 'EXACT_SQUEEZE'):
            e.select_adapter(e.LANE_ID, 'time_stop', None)

    def test_d3_next_open_and_open_censor_match_parent(self):
        bars, signal, features = fixture()
        _, parent, trace = e.tm.position(bars, signal, 'M1', features, len(bars)*e.BAR, COST)
        adapter = run()
        lot = next(iter(adapter.lots.values()))
        self.assertEqual(lot['partial_count'], 1)
        self.assertEqual(lot['remaining'], Fraction(2, 3))
        partial = [leg for leg in lot['legs'] if leg['kind'] == 'PARTIAL_FILL'][0]
        self.assertEqual(partial['source_ts'], parent['tm_legs'][0]['ts'])
        self.assertEqual(partial['qty'], parent['tm_legs'][0]['qty'])
        self.assertEqual(partial['price'], parent['tm_legs'][0]['price'])
        result = e.verify_saved_campaign(parent, trace, COST)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['economic_replays'], 0)
        snap = adapter.snapshot()['lots'][0]
        self.assertFalse(snap['terminal_liquidation'])
        self.assertEqual(snap['status'], 'OPEN')
        self.assertIsNone(snap['final_net_bps'])
        self.assertGreater(snap['remaining_mark_cost_bps'], 0)

    def test_equal_partial_fill_does_not_fund_prior_close(self):
        adapter = run((60, 78, 79), n=85)
        decisions = [row for row in adapter.events if row['kind'] == 'ENTRY_DECISION']
        self.assertEqual([r['admitted'] for r in decisions], [True, False, True])
        self.assertEqual(decisions[1]['available_qty'], 0)
        self.assertAlmostEqual(decisions[2]['allocated_qty'], 1/3)
        self.assertEqual(adapter.capacity('TEST')[0], 1)

    def test_equal_final_fill_does_not_fund_prior_close(self):
        bars, _, features = fixture()
        features[70]['momentum'] = 0
        adapter = run((60, 71, 72), bars=bars, features=features)
        decisions = [r for r in adapter.events if r['kind'] == 'ENTRY_DECISION']
        self.assertEqual([r['admitted'] for r in decisions], [True, False, True])
        self.assertEqual(decisions[2]['allocated_qty'], 1)

    def test_pending_entry_reservation_prevents_double_allocation(self):
        adapter = run((60, 61, 62), n=65, no_depth=(60, 61))
        decisions = [r for r in adapter.events if r['kind'] == 'ENTRY_DECISION']
        self.assertEqual([r['admitted'] for r in decisions], [True, False, False])
        self.assertEqual(decisions[1]['reserved_qty'], 1)
        fill = [r for r in adapter.events if r['kind'] == 'ENTRY_FILL'][0]
        self.assertEqual(fill['execution_delay_ms'], 2*e.BAR)

    def test_missing_depth_keeps_pre_partial_momentum_ownership(self):
        bars, _, features = fixture(n=85)
        features[78]['momentum'] = 0.
        adapter = run(n=85, bars=bars, features=features, no_depth=(78,))
        lot = next(iter(adapter.lots.values()))
        self.assertFalse(lot['runner'])
        self.assertEqual(lot['partial_count'], 0)
        self.assertEqual(lot['legs'][-1]['reason'], 'MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN')
        self.assertTrue(any(r['kind'] == 'UNFILLED_PARTIAL_CANCELLED' for r in adapter.events))

    def test_after_partial_negative_momentum_does_not_exit_runner(self):
        bars, _, features = fixture()
        for row in features[79:]:
            row['momentum'] = -1.
        lot = next(iter(run(bars=bars, features=features).lots.values()))
        self.assertTrue(lot['runner'])
        self.assertEqual(lot['status'], 'OPEN')

    def test_floor_precedes_be_and_sma_and_gap_is_real(self):
        bars, _, features = fixture()
        bars[95] = replace(bars[95], close=80., low=79.)
        bars[96] = replace(bars[96], open=75., low=74.)
        lot = next(iter(run(bars=bars, features=features).lots.values()))
        self.assertEqual(lot['legs'][-1]['reason'], 'FIXED_FLOOR_CLOSE_NEXT_OPEN')
        self.assertEqual(lot['legs'][-1]['price'], 75.)

    def test_be_precedes_daily_sma(self):
        bars, _, features = fixture()
        bars[95] = replace(bars[95], close=99., low=98.)
        bars[96] = replace(bars[96], open=85., low=84.)
        lot = next(iter(run(bars=bars, features=features).lots.values()))
        self.assertEqual(lot['legs'][-1]['reason'], 'RUNNER_BREAKEVEN_CLOSE_NEXT_OPEN')
        self.assertEqual(lot['legs'][-1]['price'], 85.)

    def test_sma_only_at_completed_daily_close(self):
        bars, _, features = fixture()
        bars[130] = replace(bars[130], close=110., low=109.)
        bars[131] = replace(bars[131], close=110., low=109.)
        bars[132] = replace(bars[132], open=107., low=106.)
        lot = next(iter(run(bars=bars, features=features).lots.values()))
        self.assertEqual(lot['legs'][-1]['reason'], 'RUNNER_SMA10_CLOSE_NEXT_OPEN')
        self.assertEqual(lot['legs'][-1]['source_ts'], 132*e.BAR)

    def test_d3_safety_partial_and_final_single_book(self):
        bars, signal, features = fixture()
        for j in range(60):
            bars[j] = replace(bars[j], open=150., high=151., low=149., close=150.)
        adapter = run(bars=bars, features=features)
        lot = next(iter(adapter.lots.values()))
        self.assertEqual([r['kind'] for r in lot['legs']], ['ENTRY_FILL', 'PARTIAL_FILL', 'FINAL_FILL'])
        self.assertEqual(lot['legs'][-2]['source_ts'], lot['legs'][-1]['source_ts'])
        self.assertEqual(sum(r['qty'] for r in lot['legs'][1:]), 1)
        self.assertEqual(lot['remaining'], 0)
        closed, _, trace = e.tm.position(bars, signal, 'M1', features, len(bars)*e.BAR, COST)
        self.assertEqual(e.verify_saved_campaign(closed, trace, COST)['status'], 'PASS')

    def test_d3_no_profit_never_retries(self):
        bars, _, features = fixture()
        for j in range(60, 78):
            bars[j] = replace(bars[j], open=100., high=101., low=99., close=100.)
        lot = next(iter(run(bars=bars, features=features).lots.values()))
        self.assertTrue(lot['managed'])
        self.assertFalse(lot['runner'])
        self.assertEqual(lot['partial_count'], 0)

    def test_repeated_independent_reuse_matches_exact_rationals(self):
        adapter = run((60, 79, 97, 115, 133))
        self.assertEqual([r['allocation'] for r in adapter.lots.values()],
                         [Fraction(1), Fraction(1, 3), Fraction(1, 9), Fraction(1, 27), Fraction(1, 81)])
        self.assertLessEqual(adapter.capacity('TEST')[0], 1)
        # Force one lot's own intent; the other quantity/runner is unchanged.
        lots = list(adapter.lots.values())
        before = deepcopy(lots[1])
        stamp = 151*e.BAR
        lots[0]['pending'] = adapter._intent('FINAL', 'RUNNER_BREAKEVEN_CLOSE', stamp, stamp)
        adapter.observe_depth('TEST', depth(stamp, 99.))
        self.assertEqual(lots[1], before)

    def test_gap_cancellation_releases_reserved_capacity_only(self):
        bars, _, features = fixture(n=64)
        bars[60] = replace(bars[60], open=85., low=84.)
        adapter = run(n=64, bars=bars, features=features)
        lot = next(iter(adapter.lots.values()))
        self.assertEqual(lot['status'], 'GAP_CANCELLED')
        self.assertEqual(lot['legs'], [])
        self.assertEqual(adapter.capacity('TEST'), (0, 0, 1))

    def test_observed_depth_vwap_no_liquidity_reuse(self):
        adapter = run(n=61, stop=60, no_depth=(60,))
        stamp = 60*e.BAR
        result = adapter.observe_depth('TEST', dict(source_ts=stamp, observed_ms=stamp,
            snapshot_id='book', bids=[[99., 2.]], asks=[[101., .25], [103., .75]]))
        self.assertEqual(result[0]['price'], 102.5)
        self.assertEqual(result[0]['notional'], 102.5)
        self.assertEqual(result[0]['qty'], 1)

    def test_insufficient_depth_then_delayed_observable_fill(self):
        adapter = run(n=61, stop=60, no_depth=(60,))
        stamp = 60*e.BAR
        self.assertEqual(adapter.observe_depth('TEST', depth(stamp, 100., qty=.5)), [])
        self.assertEqual(adapter.capacity('TEST'), (0, 1, 0))
        filled = adapter.observe_depth('TEST', depth(stamp+300000, 105.))
        self.assertEqual(filled[0]['price'], 105.)
        self.assertEqual(filled[0]['execution_delay_ms'], 300000)

    def test_old_depth_does_not_backfill_delayed_decision(self):
        bars, signal, _ = fixture(n=60)
        adapter = e.LifecycleAdapter()
        stamp = 60*e.BAR
        adapter._observe_close('TEST', dict(close_ts=stamp, close=100., momentum=1.,
            daily=e.tm.daily_observation(bars, 59), entries=[entry(signal)]), observed_ms=stamp+1000)
        self.assertEqual(adapter.observe_depth('TEST', depth(stamp, 100., observed=stamp+1000)), [])
        self.assertEqual(adapter.capacity('TEST'), (0, 1, 0))
        self.assertEqual(adapter.observe_depth('TEST', depth(stamp+2000, 102.))[0]['price'], 102.)

    def test_duplicate_and_reverse_equal_phase_rejected(self):
        adapter = run(n=61, stop=60)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            adapter.observe_depth('TEST', depth(60*e.BAR, 100.))
        bars, _, _ = fixture(n=60)
        with self.assertRaisesRegex(ValueError, 'CAUSAL_PHASE_ORDER'):
            adapter._observe_close('OTHER', dict(close_ts=60*e.BAR, close=100., momentum=1.,
                daily=e.tm.daily_observation(bars, 59), entries=[]), observed_ms=60*e.BAR)

    def test_missing_close_visible_and_fails_closed(self):
        adapter = run(n=62, stop=60)
        bars, _, _ = fixture(n=62)
        with self.assertRaisesRegex(ValueError, 'MISSING_OR_UNORDERED'):
            adapter._observe_close('TEST', dict(close_ts=62*e.BAR, close=101., momentum=1.,
                daily=e.tm.daily_observation(bars, 61), entries=[]), observed_ms=62*e.BAR)
        self.assertEqual(adapter.events[-1]['kind'], 'MISSING_CLOSE_BLOCK')
        self.assertEqual(adapter.events[-1]['missing_intervals'], 1)

    def test_incomplete_future_observation_and_bad_book_rejected(self):
        bars, _, _ = fixture(n=60)
        obs = dict(close_ts=60*e.BAR, close=100., momentum=1., daily=e.tm.daily_observation(bars, 59), entries=[])
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE_OR_FUTURE'):
            e.LifecycleAdapter()._observe_close('TEST', obs, observed_ms=60*e.BAR-1)
        with self.assertRaisesRegex(ValueError, 'FUTURE_OR_UNIDENTIFIED'):
            e.LifecycleAdapter().observe_depth('TEST', depth(10, 100., observed=9))
        with self.assertRaisesRegex(ValueError, 'DEPTH_SORT_ORDER'):
            e.LifecycleAdapter().observe_depth('TEST', dict(source_ts=0, observed_ms=0,
                snapshot_id='bad', bids=[[99., 1.], [100., 1.]], asks=[[101., 1.]]))

    def test_future_price_mutation_preserves_event_prefix(self):
        bars, _, features = fixture()
        changed = deepcopy(bars)
        for j in range(100, len(changed)):
            changed[j] = replace(changed[j], open=50., high=500., low=1., close=50.)
        original = run((60, 79, 97, 115), bars=bars, features=features)
        mutated = run((60, 79, 97, 115), bars=changed, features=features)
        truncated = run((60, 79, 97, 115), bars=bars, features=features, stop=99)
        def prefix(adapter):
            return [r for r in adapter.events if r.get('observed_ms', 10**30) < 100*e.BAR]
        self.assertEqual(prefix(original), prefix(mutated))
        self.assertEqual(prefix(original), prefix(truncated))

    def test_canonical_entry_uses_frozen_reg71_predicates(self):
        bars, signal, features = fixture(n=60)
        original = dict(eligible=True, reason=None, range_context=dict(strict_escape=True))
        daily = dict(eligible=False, value=90., signal_close=100., available_at=60*e.BAR,
                     daily_closes=[dict(close=float(90+j)) for j in range(6)])
        with patch.object(e.tm.native, 'm1_setups', return_value=([signal], [], features)), \
             patch.object(e.tm.c63, 'context', return_value=original), \
             patch.object(e.tm.daily, 'observation', return_value=daily):
            obs = e.canonical_observation(bars)
        self.assertEqual(obs['entries'][0]['context'], e.tm.c70_context(original, daily))
        self.assertTrue(obs['entries'][0]['context']['eligible'])
        self.assertEqual(obs['entries'][0]['source_signal_sha'], e.digest(signal))

    def test_pending_terminal_partial_does_not_release_capacity(self):
        adapter = run(n=78)
        lot = adapter.snapshot()['lots'][0]
        self.assertEqual(lot['remaining'], 1)
        self.assertEqual(lot['pending']['action'], 'PARTIAL')
        self.assertEqual(lot['censor_reason'], 'PENDING_EXIT_OUTSIDE_OBSERVATIONS')
        self.assertFalse(lot['terminal_liquidation'])
        self.assertEqual(adapter.capacity('TEST'), (1, 0, 0))

    def test_missing_cost_blocks_d3_without_producing_credit(self):
        adapter = run(n=78, stop=77)
        bars, _, _ = fixture(n=78)
        stamp = 78*e.BAR
        adapter._observe_close('TEST', dict(close_ts=stamp, close=bars[77].close, momentum=1.,
            daily=e.tm.daily_observation(bars, 77), entries=[]), observed_ms=stamp)
        lot = adapter.snapshot()['lots'][0]
        self.assertTrue(lot['managed'])
        self.assertIsNone(lot['pending'])
        self.assertIsNone(lot['remaining_mark_cost_bps'])
        self.assertEqual(lot['formal_credit'], 0)
        self.assertTrue(any(r['kind'] == 'CHECKPOINT_COST_MISSING_BLOCK' for r in adapter.events))


    def test_invalid_cost_is_atomic_and_cannot_consume_d3(self):
        adapter = run(n=78, stop=77)
        bars, _, _ = fixture(n=78)
        stamp = 78*e.BAR
        obs = dict(close_ts=stamp, close=bars[77].close, momentum=1.,
                   daily=e.tm.daily_observation(bars, 77), entries=[])
        lot_id = next(iter(adapter.lots))
        before = adapter.snapshot()
        bad = {lot_id:dict(entry_ts=0, as_of_ms=stamp, round_trip_bps=20., cost_sha='bad')}
        with self.assertRaisesRegex(ValueError, 'CHECKPOINT_COST_LINEAGE'):
            adapter._observe_close('TEST', obs, observed_ms=stamp, checkpoint_costs=bad)
        self.assertEqual(adapter.snapshot(), before)
        good = {lot_id:dict(entry_ts=adapter.lots[lot_id]['entry_ts'], as_of_ms=stamp,
                           round_trip_bps=20., cost_sha='synthetic')}
        adapter._observe_close('TEST', obs, observed_ms=stamp, checkpoint_costs=good)
        self.assertEqual(adapter.lots[lot_id]['pending']['action'], 'PARTIAL')
        self.assertEqual(adapter.lots[lot_id]['daily_count'], 3)

    def test_cost_equality_does_not_trigger_partial(self):
        adapter = run(n=78, stop=77)
        bars, _, _ = fixture(n=78)
        stamp = 78*e.BAR
        lot_id = next(iter(adapter.lots))
        lot = adapter.lots[lot_id]
        cost = (bars[77].close/lot['entry_price']-1)*10000
        adapter._observe_close('TEST', dict(close_ts=stamp, close=bars[77].close, momentum=1.,
            daily=e.tm.daily_observation(bars, 77), entries=[]), observed_ms=stamp,
            checkpoint_costs={lot_id:dict(entry_ts=lot['entry_ts'], as_of_ms=stamp,
                                         round_trip_bps=cost, cost_sha='synthetic')})
        self.assertIsNone(adapter.lots[lot_id]['pending'])
        self.assertTrue(adapter.lots[lot_id]['managed'])

    def test_partial_missing_depth_never_releases_capacity(self):
        adapter = run(n=79, stop=78, no_depth=(78,))
        stamp = 78*e.BAR
        self.assertEqual(adapter.observe_depth('TEST', depth(stamp, 109., qty=.1)), [])
        lot = next(iter(adapter.lots.values()))
        self.assertEqual(lot['remaining'], 1)
        self.assertFalse(lot['runner'])
        self.assertEqual(adapter.capacity('TEST'), (1, 0, 0))

    def test_shared_depth_cannot_be_reused_by_independent_lots(self):
        adapter = run((60, 79), n=82)
        first, second = list(adapter.lots.values())
        stamp = 83*e.BAR
        for lot in (first, second):
            lot['pending'] = adapter._intent('FINAL', 'FIXED_FLOOR_CLOSE', stamp, stamp)
        fills = adapter.observe_depth('TEST', depth(stamp, 95., qty=2/3))
        self.assertEqual(len(fills), 1)
        self.assertEqual(first['status'], 'CLOSED')
        self.assertEqual(second['remaining'], Fraction(1, 3))
        self.assertEqual(second['status'], 'OPEN')
        self.assertEqual(adapter.capacity('TEST')[0], Fraction(1, 3))

    def test_safety_remainder_waits_for_observed_depth_without_duplicate_partial(self):
        bars, _, features = fixture(n=80)
        for j in range(60):
            bars[j] = replace(bars[j], open=150., high=151., low=149., close=150.)
        adapter = run(bars=bars, features=features, n=80, stop=78, no_depth=(78,))
        stamp = 78*e.BAR
        partial = adapter.observe_depth('TEST', depth(stamp, 109., qty=1/3))
        self.assertEqual([r['kind'] for r in partial], ['PARTIAL_FILL'])
        lot = next(iter(adapter.lots.values()))
        self.assertEqual(lot['remaining'], Fraction(2, 3))
        self.assertEqual(lot['pending']['action'], 'FINAL')
        final = adapter.observe_depth('TEST', depth(stamp+300000, 108., qty=1.))
        self.assertEqual([r['kind'] for r in final], ['FINAL_FILL'])
        self.assertEqual(lot['partial_count'], 1)
        self.assertEqual(lot['remaining'], 0)
        self.assertEqual(final[0]['execution_delay_ms'], 300000)

    def test_public_canonical_path_cannot_invent_missing_history_entry(self):
        from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture
        bars = momentum_fixture(n=50)
        observation = e.canonical_observation(bars[:31])
        self.assertEqual(len(observation['entries']), 1)
        self.assertFalse(observation['entries'][0]['context']['eligible'])
        self.assertEqual(observation['entries'][0]['context']['reason'],
                         'COMPLETED_DAILY_EMA21_HISTORY_UNAVAILABLE')
        adapter = e.LifecycleAdapter()
        adapter.observe_completed('TEST', bars[:31], observed_ms=31*e.BAR)
        self.assertEqual(adapter.lots, {})
        self.assertFalse(adapter.events[-1]['admitted'])


    def test_second_lot_invalid_cost_rolls_back_first_lot_too(self):
        adapter = run((60, 79), n=82)
        bars, _, _ = fixture(n=83)
        stamp = 83*e.BAR
        keys = list(adapter.lots)
        costs = {key: dict(entry_ts=lot['entry_ts'], as_of_ms=stamp,
                           round_trip_bps=20., cost_sha='synthetic')
                 for key, lot in adapter.lots.items()}
        costs[keys[1]]['entry_ts'] = 0
        before = adapter.snapshot()
        with self.assertRaisesRegex(ValueError, 'CHECKPOINT_COST_LINEAGE'):
            adapter._observe_close('TEST', dict(close_ts=stamp, close=99., momentum=1.,
                daily=e.tm.daily_observation(bars, 82), entries=[]), observed_ms=stamp,
                checkpoint_costs=costs)
        self.assertEqual(adapter.snapshot(), before)

    def test_invalid_second_signal_rolls_back_first_reservation(self):
        bars, signal, _ = fixture(n=60)
        adapter = e.LifecycleAdapter()
        stamp = 60*e.BAR
        first, bad = entry(signal), entry(dict(signal, setup_id='OTHER'))
        bad['source_signal_sha'] = 'INVALID'
        before = adapter.snapshot()
        with self.assertRaisesRegex(ValueError, 'EXACT_SIGNAL_CLOCK_OR_HASH'):
            adapter._observe_close('TEST', dict(close_ts=stamp, close=100., momentum=1.,
                daily=e.tm.daily_observation(bars, 59), entries=[first, bad]), observed_ms=stamp)
        self.assertEqual(adapter.snapshot(), before)
        adapter._observe_close('TEST', dict(close_ts=stamp, close=100., momentum=1.,
            daily=e.tm.daily_observation(bars, 59), entries=[first]), observed_ms=stamp)
        self.assertEqual(adapter.capacity('TEST'), (0, 1, 0))


if __name__ == '__main__':
    unittest.main()
