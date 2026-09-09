"""Artificial source-timing cases only: no exchange, market bars or PnL."""
import copy
from decimal import Decimal, localcontext, Inexact, Rounded
from fractions import Fraction
import unittest
from backend.research.benchmark.creator_squeeze_timing_v1 import (
    SOURCE_ID, Fact, EntryAllocation, ExitSequence, DailyLow, Unresolved,
    entry_readiness, runner_level, early_failure, economic_replay_authority, price,
)


def fact(v, at=1):
    return Fact(v, at, at, 'SYNTHETIC_EXPLICIT_FIXTURE')


def ready():
    return {k: fact(v) for k,v in dict(source_variant=SOURCE_ID,
        primary_timeframe='SOURCE_DAILY_SESSION', red_dots=3,
        close='101', ema21='100', high_context=True,
        cup_handle_context=True).items()}


def lows(values=('102','104','103')):
    return [DailyLow('EXAMPLE_SESSION_CALENDAR',i,Decimal(v),i+1) for i,v in enumerate(values)]


def runner():
    x=ExitSequence('100','2.5')
    for i,t in enumerate(('FIRST_HIGH','EXTENSION_1272')):
        x.request_target(t,10+i*2,fact(True))
        x.acknowledge_fill(Fraction(1,3),11+i*2,'filled-'+t)
    return x


class EntryTests(unittest.TestCase):
    def test_weekly_squeeze_is_not_required(self):
        self.assertEqual(entry_readiness(ready(),2)['status'],'PREPARE_ONLY')
    def test_preparing_is_not_placing_order(self):
        self.assertFalse(entry_readiness(ready(),2)['place_order'])
    def test_two_dots_wait(self):
        x=ready();x['red_dots']=fact(2)
        self.assertEqual(entry_readiness(x,2)['status'],'WAIT')
    def test_equal_ema_is_not_above(self):
        x=ready();x['close']=fact('100')
        self.assertEqual(entry_readiness(x,2)['status'],'WAIT')
    def test_undefined_pattern_does_not_become_true(self):
        x=ready();del x['cup_handle_context']
        self.assertEqual(entry_readiness(x,2)['status'],'UNRESOLVED')
    def test_false_pattern_wait(self):
        x=ready();x['cup_handle_context']=fact(False)
        self.assertEqual(entry_readiness(x,2)['status'],'WAIT')
    def test_future_context_rejected(self):
        x=ready();x['high_context']=fact(True,3)
        with self.assertRaises(Unresolved):entry_readiness(x,2)
    def test_falsely_early_availability_rejected(self):
        with self.assertRaises(Unresolved):Fact(True,4,2,'fixture').at(5)
    def test_general_plan_not_blended(self):
        x=ready();x['source_variant']=fact('GENERAL_PLAN_PRICE_ABOVE_MA34')
        with self.assertRaises(Unresolved):entry_readiness(x,2)
    def test_four_hour_not_three_source_days(self):
        x=ready();x['primary_timeframe']=fact('4H')
        with self.assertRaises(Unresolved):entry_readiness(x,2)
    def test_source_example_343_and_missing_pullbacks(self):
        b=EntryAllocation(10,3,4,3)
        self.assertEqual(b.request_breakout(1),('EMA21','EMA8'))
        with self.assertRaises(Unresolved):b.activate_breakout(2)
        b.acknowledge_cancel('EMA8',2);b.acknowledge_cancel('EMA21',2)
        self.assertEqual(b.activate_breakout(3),10)
        b.fill('BREAKOUT',10,4,'fill-1');self.assertEqual(b.filled,10)
    def test_only_unfilled_quantity_reassigned(self):
        b=EntryAllocation(10,3,4,3);b.fill('EMA8',3,1,'p1')
        b.request_breakout(2);b.acknowledge_cancel('EMA21',3)
        self.assertEqual(b.activate_breakout(4),7)
    def test_all_three_legs_do_not_exceed_cap(self):
        b=EntryAllocation(10,3,4,3);b.fill('EMA8',3,1,'p1');b.fill('EMA21',4,2,'p2')
        self.assertEqual(b.request_breakout(3),());self.assertEqual(b.activate_breakout(3),3)
        b.fill('BREAKOUT',3,4,'p3');self.assertEqual(b.filled,10)
    def test_fill_while_cancel_pending_reconciles(self):
        b=EntryAllocation(10,3,4,3);b.request_breakout(1)
        b.fill('EMA8',2,2,'race-fill');b.acknowledge_cancel('EMA8',3);b.acknowledge_cancel('EMA21',3)
        self.assertEqual(b.activate_breakout(4),8)
    def test_duplicate_fill_no_state_change(self):
        b=EntryAllocation(10,3,4,3);b.fill('EMA8',1,1,'same');old=copy.deepcopy(vars(b))
        with self.assertRaises(ValueError):b.fill('EMA8',1,2,'same')
        self.assertEqual(vars(b),old)
    def test_overfill_no_state_change(self):
        b=EntryAllocation(10,3,4,3);old=copy.deepcopy(vars(b))
        with self.assertRaises(ValueError):b.fill('EMA8',4,1,'too-much')
        self.assertEqual(vars(b),old)
    def test_cancelled_leg_cannot_fill(self):
        b=EntryAllocation(10,3,4,3);b.request_breakout(1);b.acknowledge_cancel('EMA8',2)
        with self.assertRaises(ValueError):b.fill('EMA8',1,3,'late')
    def test_late_event_and_duplicate_breakout_rejected(self):
        b=EntryAllocation(10,3,4,3);b.fill('EMA8',1,5,'real')
        with self.assertRaises(ValueError):b.request_breakout(4)
        b.request_breakout(6)
        with self.assertRaises(ValueError):b.request_breakout(6)


class ManagementTests(unittest.TestCase):
    def test_underlying_stop_initial_then_after_filled_first_third(self):
        x=ExitSequence('100','2.5');self.assertEqual(x.stop,Decimal('95'))
        x.request_target('FIRST_HIGH',1,fact(True));self.assertEqual(x.stop,Decimal('95'))
        x.acknowledge_fill(Fraction(1,6),2,'a');self.assertEqual(x.stop,Decimal('95'))
        x.acknowledge_fill(Fraction(1,6),3,'b');self.assertEqual(x.stop,Decimal('97.5'))
    def test_second_third_sets_underlying_entry_not_net_breakeven(self):
        x=runner();self.assertEqual(x.stop,Decimal('100'));self.assertEqual(x.remaining,Fraction(1,3))
    def test_no_future_target_fill(self):
        x=ExitSequence('100','2.5')
        with self.assertRaises(Unresolved):x.request_target('FIRST_HIGH',1,fact(True,2))
        self.assertEqual(x.remaining,Fraction(1))
    def test_pending_target_not_filled_by_a_touch(self):
        x=ExitSequence('100','2.5');x.request_target('FIRST_HIGH',1,fact(True))
        self.assertEqual(x.remaining,Fraction(1));self.assertEqual(x.stage,0)
        with self.assertRaises(ValueError):x.request_target('EXTENSION_1272',2,fact(True))
    def test_second_target_cannot_skip_first(self):
        with self.assertRaises(ValueError):ExitSequence('100','2.5').request_target('EXTENSION_1272',1,fact(True))
    def test_trailing_not_armed_on_entry(self):
        x=ExitSequence('100','2.5')
        with self.assertRaises(Unresolved):x.update_runner(lows(),calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.1')
    def test_prior_three_lows_only_and_stop_does_not_loosen(self):
        x=runner();value=x.update_runner(lows(),calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.1')
        self.assertEqual(value,Decimal('101.9'))
        self.assertEqual(runner_level(lows(('90','91','92')),calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=21,offset='.1',current_protection=value),value)
    def test_today_low_is_not_prior_low(self):
        a=lows();a[2]=DailyLow('EXAMPLE_SESSION_CALENDAR',3,Decimal('999'),3)
        with self.assertRaises(Unresolved):runner_level(a,calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.1',current_protection='100')
    def test_future_daily_low_rejected(self):
        a=lows();a[2]=DailyLow('EXAMPLE_SESSION_CALENDAR',2,Decimal('103'),25)
        with self.assertRaises(Unresolved):runner_level(a,calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.1',current_protection='100')
    def test_wrong_calendar_or_gap_rejected(self):
        with self.assertRaises(Unresolved):runner_level(lows(),calendar_id='CRYPTO_4H',current_session=3,decision_at=20,offset='.1',current_protection='100')
        with self.assertRaises(Unresolved):runner_level(lows()[:2],calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.1',current_protection='100')
    def test_zero_offset_not_inferred_from_just_below(self):
        with self.assertRaises(ValueError):runner_level(lows(),calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='0',current_protection='100')
    def test_full_sequence_is_one_original_position_not_three_wins(self):
        x=runner();x.request_target('EXTENSION_1618',20,fact(True))
        x.acknowledge_fill(Fraction(1,3),21,'last');self.assertEqual(x.remaining,Fraction(0));self.assertEqual(x.stage,3)
        with self.assertRaises(ValueError):x.request_target('EXTENSION_1618',22,fact(True))
    def test_duplicate_exit_and_overfill_no_change(self):
        x=ExitSequence('100','2.5');x.request_target('FIRST_HIGH',1,fact(True));x.acknowledge_fill(Fraction(1,6),2,'a')
        old=copy.deepcopy(vars(x))
        for amount,key in ((Fraction(1,3),'b'),(Fraction(1,6),'a')):
            with self.assertRaises(ValueError):x.acknowledge_fill(amount,3,key)
            self.assertEqual(vars(x),old)
    def test_lot_rounding_not_silently_filled(self):
        x=runner();self.assertEqual(x.quantity_for_fraction('9',Fraction(1,3),'1'),Decimal(3))
        with self.assertRaises(Unresolved):x.quantity_for_fraction('10',Fraction(1,3),'1')
    def test_underlying_positive_does_not_prove_option_positive(self):
        with self.assertRaises(Unresolved):early_failure(elapsed_trading_sessions=3,mark=fact('1'),mark_basis='UNDERLYING_RETURN',decision_at=2)
        self.assertTrue(early_failure(elapsed_trading_sessions=3,mark=fact('-1'),mark_basis='DIRECTIONAL_OPTION_NET_PNL',decision_at=2))
    def test_checkpoint_not_first_bar_or_daily_repeat(self):
        for n in (0,1,2,4):self.assertFalse(early_failure(elapsed_trading_sessions=n,mark=fact('-1'),mark_basis='DIRECTIONAL_OPTION_NET_PNL',decision_at=2))
    def test_checkpoint_zero_is_source_ambiguity_not_forced_exit(self):
        with self.assertRaises(Unresolved):early_failure(elapsed_trading_sessions=3,mark=fact('0'),mark_basis='DIRECTIONAL_OPTION_NET_PNL',decision_at=2)
    def test_positive_option_checkpoint_does_not_exit(self):
        self.assertFalse(early_failure(elapsed_trading_sessions=3,mark=fact('1'),mark_basis='DIRECTIONAL_OPTION_NET_PNL',decision_at=2))
    def test_no_economic_or_audited_trader_claim(self):
        x=economic_replay_authority();self.assertFalse(x['allowed']);self.assertEqual(x['complete_observed_trader_cases'],0);self.assertGreater(len(x['missing']),0)
    def test_no_network_model_or_market_imports(self):
        import ast,inspect
        import backend.research.benchmark.creator_squeeze_timing_v1 as m
        tree=ast.parse(inspect.getsource(m));names={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        self.assertLessEqual(names,{'__future__','dataclasses','decimal','fractions','typing'})
        self.assertFalse(any(isinstance(n,ast.Import) for n in ast.walk(tree)))
    def test_nonfinite_negative_float_prices_not_accepted(self):
        for v in ('NaN','Infinity','-1','0',True,100.1,'bad'):
            with self.assertRaises(ValueError):price(v)



class ExactArithmeticTests(unittest.TestCase):
    def test_third_cannot_be_rounded_to_small_lot(self):
        x=ExitSequence('100','2')
        with self.assertRaisesRegex(Unresolved,'LOT_ROUNDING_POLICY_REQUIRED'):
            x.quantity_for_fraction('1',Fraction(1,3),'1e-28')

    def test_low_precision_cannot_fabricate_lot_alignment(self):
        x=ExitSequence('100','2')
        with localcontext() as context:
            context.prec=6
            with self.assertRaisesRegex(Unresolved,'LOT_ROUNDING_POLICY_REQUIRED'):
                x.quantity_for_fraction('1',Fraction(1,3),'0.000001')

    def test_exact_quantity_is_context_invariant(self):
        x=ExitSequence('100','2')
        for precision in (2,6,28):
            with self.subTest(precision=precision), localcontext() as context:
                context.prec=precision
                self.assertEqual(x.quantity_for_fraction('123456789.03',Fraction(1,3),'.01'),Decimal('41152263.01'))

    def test_rounding_traps_are_not_relied_on(self):
        x=ExitSequence('100','2')
        with localcontext() as context:
            context.prec=2
            context.traps[Inexact]=context.traps[Rounded]=True
            self.assertEqual(x.quantity_for_fraction('123456789.03',Fraction(1,3),'.01'),Decimal('41152263.01'))

    def test_rational_lot_alignment_cases(self):
        x=ExitSequence('100','2')
        for total in range(1,11):
            for denominator in range(1,8):
                for step in ('1','.1','.01'):
                    fraction=Fraction(1,denominator)
                    exact=Fraction(total)*fraction
                    with self.subTest(total=total,denominator=denominator,step=step):
                        if (exact/Fraction(Decimal(step))).denominator==1:
                            self.assertEqual(Fraction(x.quantity_for_fraction(total,fraction,step)),exact)
                        else:
                            with self.assertRaises(Unresolved):x.quantity_for_fraction(total,fraction,step)

    def test_initial_stop_preserves_small_difference(self):
        with localcontext() as context:
            context.prec=3
            x=ExitSequence('100.09','.01')
            self.assertEqual(x.stop,Decimal('100.07'))

    def test_first_tranche_protection_does_not_round(self):
        with localcontext() as context:
            context.prec=3
            x=ExitSequence('100.09','.01')
            x.request_target('FIRST_HIGH',1,fact(True))
            x.acknowledge_fill(Fraction(1,3),2,'filled')
            self.assertEqual(x.stop,Decimal('100.08'))

    def test_initial_nonpositive_stop_still_rejected(self):
        for entry,atr in (('2','1'),('1','1')):
            with self.assertRaisesRegex(ValueError,'NONPOSITIVE_INITIAL_STOP'):ExitSequence(entry,atr)

    def test_runner_offset_preserves_exact_level(self):
        data=lows(('100.09','100.11','100.12'))
        with localcontext() as context:
            context.prec=3
            level=runner_level(data,calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.01',current_protection='99')
            self.assertEqual(level,Decimal('100.08'))

    def test_runner_still_cannot_loosen(self):
        with localcontext() as context:
            context.prec=3
            level=runner_level(lows(('100.09','100.11','100.12')),calendar_id='EXAMPLE_SESSION_CALENDAR',current_session=3,decision_at=20,offset='.01',current_protection='100.081')
            self.assertEqual(level,Decimal('100.081'))

    def test_bad_lot_policy_leaves_management_unchanged(self):
        x=runner();before=copy.deepcopy(vars(x))
        with self.assertRaises(Unresolved):x.quantity_for_fraction('10',Fraction(1,3),'1e-28')
        self.assertEqual(vars(x),before)

    def test_conformance_math_does_not_grant_economics(self):
        x=economic_replay_authority()
        self.assertFalse(x['allowed'])
        self.assertEqual(x['new_strategy_candidates'],0)
        self.assertEqual(x['formal_credit'],0)

if __name__=='__main__':unittest.main()
