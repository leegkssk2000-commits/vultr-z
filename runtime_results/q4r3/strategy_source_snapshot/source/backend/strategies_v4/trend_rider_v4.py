# H85Y_3RD_DATA_RULES_APPLIED
# H85V internal upgraded strategy wrapper
# Strategy: trend_rider|enter_long
# Role: reserve
# Source: /home/z/z/backend/strategies/trend_rider.py
# Original strategy is not modified.

from h85v_common import evaluate_candidate

STRATEGY_KEY = "trend_rider|enter_long"
ROLE = "reserve"
SOURCE_STRATEGY_FILE = '/home/z/z/backend/strategies/trend_rider.py'

def evaluate(candidate, state_rows=None, failure_rows=None, policy=None):
    return evaluate_candidate(
        candidate=candidate or {},
        state_rows=state_rows or [],
        failure_rows=failure_rows or [],
        expected_key=STRATEGY_KEY,
        role=ROLE,
        source_strategy_file=SOURCE_STRATEGY_FILE,
    )
