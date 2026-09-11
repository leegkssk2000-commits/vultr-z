"""Artificial money/selection gates; no historical screen or FULL execution."""
from copy import deepcopy
from math import fsum
from unittest.mock import patch
import unittest

from backend.research.rebuild import squeeze_sprint_account_v1 as a
from backend.research.rebuild import squeeze_sprint_screen_v1 as screen
from backend.research.rebuild.test_squeeze_sprint_screen_v1 import parent, raw_of, forced
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture, COST, POLICY
from backend.research.rebuild.test_chart_mechanism_execution_v1 import rows_of


def metric(**changes):
    value = dict(source_conformance='PASS', causal_integrity='PASS',
                 normal_increment_bps=10., cost2_increment_bps=5.,
                 ordinary_winner_retention=1., top_decile_winner_retention=1.,
                 loss_tail_worst_decile_mean_bps=-10., quantity_exposure_symbol_days=5.)
    value.update(changes)
    return value


def windows(value=None):
    return {p: deepcopy(value if value is not None else metric()) for p in a.PERIODS}


def full_parent():
    return dict(terminal_net_bps=100., terminal_cost2x_net_bps=80., net_bps=70.,
                marked_DD_trade_sum_bps=20., ordinary_winner_retention=1.,
                top_decile_winner_retention=1., loss_tail_worst_bps=-10.,
                loss_tail_worst_decile_mean_bps=-8., quantity_exposure_symbol_days=5.)


def full_child(**changes):
    value = dict(full_parent(), terminal_net_bps=110., terminal_cost2x_net_bps=90., net_bps=80.)
    value.update(changes)
    return value


def packet_cal(bars):
    return (dict(policy=POLICY, rows_by={'TEST': rows_of(bars)}, costs={'TEST': COST}),
            dict(start_ms=0, runoff_end_ms=bars[-1].open_ts + screen.tm.BAR))


class MoneyTests(unittest.TestCase):
    def test_open_partial_cash_and_cost2_weighted_once(self):
        bars, signal, features = fixture(n=100)
        rr = parent(bars, signal, features, 1, 3)
        raw = raw_of(rr)
        packet, cal = packet_cal(bars)
        result = a.charge({'TEST': rr}, packet, cal, 'ARTIFICIAL', a.SCREEN)
        snap = a.snapshot(result, result)
        gross = fsum(l['qty'] * (l['price'] / raw['entry_price'] - 1) * 10000
                     for l in raw['tm_legs']) / 3
        cost = fsum(l['qty'] * screen.tm.cost_at(COST, raw['entry_ts'], l['ts'])
                    for l in raw['tm_legs']) / 3
        self.assertAlmostEqual(snap['terminal_net_bps'], gross - cost)
        self.assertAlmostEqual(snap['terminal_cost2x_net_bps'], gross - 2 * cost)
        self.assertEqual((snap['closed'], snap['open']), (0, 1))
        self.assertEqual(snap['partial_count'], 1)
        self.assertIsNone(snap['win_rate'])
        self.assertEqual(len(result['open_observations'][0]['weighted_legs']), 2)
        self.assertAlmostEqual(result['open_observations'][0]['assembled_qty'], 1 / 3)
        self.assertEqual(result['candidate'], 'ARTIFICIAL')
        self.assertEqual(result['comparison_mode'], a.SCREEN)
        self.assertEqual(result['formal_credit'], 0)

    def test_component_metadata_survives_charging_and_one_campaign_win(self):
        bars, signal, features = fixture(n=100)
        rr = parent(bars, signal, features, 1, 9)
        packet, cal = packet_cal(bars)
        with patch.object(screen.comp, 'observe', side_effect=forced(89)):
            child_rr = screen.screen_symbol(rr, rows_of(bars), COST, cal['runoff_end_ms'], 'S1-07')
        control = a.charge({'TEST': rr}, packet, cal, 'CONTROL', 'SAVED_PARENT_FULL')
        child = a.charge({'TEST': child_rr}, packet, cal, 'S1-07', a.SCREEN)
        snap = a.snapshot(child, control)
        self.assertEqual((snap['closed'], snap['open']), (1, 0))
        self.assertEqual(snap['win_rate'], 1.)
        self.assertEqual(snap['component_exit_count'], 1)
        self.assertEqual(snap['component_trigger_count'], 1)
        self.assertEqual(snap['screen_changed_campaigns'], 1)
        self.assertEqual(snap['partial_count'], 1)
        self.assertEqual(child['events'], control['events'])
        self.assertEqual(child['trades'][0]['candidate'], 'S1-07')
        self.assertTrue(child['trades'][0]['component_exit'])

    def test_common_trade_bridge_uses_actual_money_and_cost_change(self):
        bars, signal, features = fixture(n=100)
        rr = parent(bars, signal, features, 1, 3)
        packet, cal = packet_cal(bars)
        with patch.object(screen.comp, 'observe', side_effect=forced(70)):
            child_rr = screen.screen_symbol(rr, rows_of(bars), COST, cal['runoff_end_ms'], 'S1-04')
        control = a.charge({'TEST': rr}, packet, cal, 'CONTROL', 'SAVED_PARENT_FULL')
        child = a.charge({'TEST': child_rr}, packet, cal, 'S1-04', a.SCREEN)
        value = a.screen_metrics(control, child)
        self.assertAlmostEqual(value['normal_increment_bps'], value['gross_delta_bps'] - value['cost_delta_bps'])
        self.assertAlmostEqual(value['cost2_increment_bps'], value['gross_delta_bps'] - 2 * value['cost_delta_bps'])
        self.assertEqual(value['component_exit_count'], 1)
        self.assertEqual(value['changed_campaigns'], 1)
        self.assertEqual(value['gross_decomposition']['occupancy_new_excluded_net_bps'], 0.)
        self.assertLess(value['exposure_delta_symbol_days'], 0.)
        self.assertEqual(value['FULL'], 0)
        self.assertEqual(value['canonical_candidates'], 0)

    def test_identity_screen_money_and_json_roundtrip(self):
        import json
        bars, signal, features = fixture(n=100)
        rr = parent(bars, signal, features)
        packet, cal = packet_cal(bars)
        result = a.charge({'TEST': rr}, packet, cal, 'CONTROL', 'SAVED_PARENT_FULL')
        copied = json.loads(json.dumps(result))
        value = a.screen_metrics(result, copied)
        self.assertEqual(value['normal_increment_bps'], 0.)
        self.assertEqual(value['cost2_increment_bps'], 0.)
        self.assertEqual(value['exposure_delta_symbol_days'], 0.)
        self.assertFalse(a.stage1_gate(value)['passed'])


class StageOneGateTests(unittest.TestCase):
    def test_retention_exact_point_six_passes_but_less_or_missing_fails(self):
        self.assertTrue(a.stage1_gate(metric(ordinary_winner_retention=.6,
                                            top_decile_winner_retention=.6))['passed'])
        for key in ('ordinary_winner_retention', 'top_decile_winner_retention'):
            for value in (.5999999999, None):
                self.assertFalse(a.stage1_gate(metric(**{key: value}))['passed'])

    def test_net_and_cost2_each_strictly_positive(self):
        for key in ('normal_increment_bps', 'cost2_increment_bps'):
            for value in (0., -1., float('nan')):
                self.assertFalse(a.stage1_gate(metric(**{key: value}))['passed'])
            self.assertTrue(a.stage1_gate(metric(**{key: 1e-12}))['passed'])

    def test_source_and_causality_required(self):
        for key in ('source_conformance', 'causal_integrity'):
            self.assertFalse(a.stage1_gate(metric(**{key: 'FAIL'}))['passed'])

    def test_windows_pass_separately_large_first_cannot_mask_second_loss(self):
        table = {'S1-02': windows(metric(cost2_increment_bps=100000., normal_increment_bps=100000.))}
        table['S1-02'][a.PERIODS[1]] = metric(cost2_increment_bps=-.01)
        result = a.select_stage1(table, a.components.REGISTRY)
        self.assertEqual(result['survivors'], [])
        self.assertTrue(result['decisions']['S1-02'][a.PERIODS[0]]['passed'])
        self.assertFalse(result['decisions']['S1-02'][a.PERIODS[1]]['passed'])

    def test_pareto_removes_dominated_even_if_higher_grade(self):
        table = {key: windows(metric()) for key in ('A', 'B', 'C', 'D')}
        table['A'] = windows(metric(cost2_increment_bps=6.))
        registry = {key: {'performance_grade': 'A' if key != 'A' else 'C'} for key in table}
        result = a.select_stage1(table, registry)
        self.assertEqual(result['survivors'], ['A'])
        self.assertEqual(result['pareto_or_deterministic_cap_excluded'], ['B', 'C', 'D'])

    def test_nondominated_limit_uses_grade_then_cost2_sum_then_stable_id(self):
        table = {key: windows(metric()) for key in ('Z', 'B', 'A', 'D')}
        registry = {'Z': {'performance_grade': 'A'}, 'B': {'performance_grade': 'B'},
                    'A': {'performance_grade': 'B'}, 'D': {'performance_grade': 'C'}}
        result = a.select_stage1(table, registry)
        self.assertEqual(result['survivors'], ['Z', 'A', 'B'])
        # Higher stress increment trades off exposure, so neither dominates.
        table['B'] = windows(metric(cost2_increment_bps=6., quantity_exposure_symbol_days=6.))
        result = a.select_stage1(table, registry)
        self.assertEqual(result['survivors'], ['Z', 'B', 'A'])
        reversed_table = dict(reversed(list(table.items())))
        self.assertEqual(result, a.select_stage1(reversed_table, registry))


class StageTwoGateTests(unittest.TestCase):
    def test_stage2_requires_full_retention_not_screen_point_six(self):
        self.assertTrue(a.full_gate(full_child(), full_parent())['passed'])
        for key in ('ordinary_winner_retention', 'top_decile_winner_retention'):
            for value in (.6, .999, None):
                result = a.full_gate(full_child(**{key: value}), full_parent())
                self.assertFalse(result['passed'])

    def test_stage2_net_cost2_closed_net_must_each_improve(self):
        p = full_parent()
        for key in ('terminal_net_bps', 'terminal_cost2x_net_bps', 'net_bps'):
            self.assertFalse(a.full_gate(full_child(**{key: p[key]}), p)['passed'])
            self.assertFalse(a.full_gate(full_child(**{key: p[key] - 1}), p)['passed'])

    def test_stage2_dd_and_both_loss_metrics_cannot_worsen(self):
        p = full_parent()
        self.assertFalse(a.full_gate(full_child(marked_DD_trade_sum_bps=p['marked_DD_trade_sum_bps'] + .001), p)['passed'])
        for key in ('loss_tail_worst_bps', 'loss_tail_worst_decile_mean_bps'):
            self.assertFalse(a.full_gate(full_child(**{key: p[key] - .001}), p)['passed'])
        self.assertTrue(a.full_gate(full_child(loss_tail_worst_bps=None,
                                               loss_tail_worst_decile_mean_bps=None), p)['passed'])
        no_losses = dict(p, loss_tail_worst_bps=None, loss_tail_worst_decile_mean_bps=None)
        self.assertFalse(a.full_gate(full_child(), no_losses)['passed'])

    def test_stage2_windows_independent_and_survivor_limit_two(self):
        parents = windows(full_parent())
        table = {key: windows(full_child()) for key in ('A', 'B', 'C')}
        registry = {key: {'performance_grade': 'C'} for key in table}
        result = a.select_stage2(table, parents, registry)
        self.assertEqual(result['survivors'], ['A', 'B'])
        table['A'][a.PERIODS[1]]['ordinary_winner_retention'] = .6
        result = a.select_stage2(table, parents, registry)
        self.assertEqual(result['survivors'], ['B', 'C'])
        self.assertFalse(result['decisions']['A'][a.PERIODS[1]]['passed'])


if __name__ == '__main__':
    unittest.main()
