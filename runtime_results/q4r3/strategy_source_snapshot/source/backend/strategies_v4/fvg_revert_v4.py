# H85Y_3RD_DATA_RULES_APPLIED
# H85V internal upgraded strategy wrapper
# Strategy: fvg_revert|enter_long
# Role: fuse_candidate
# Source: /home/z/z/backend/strategies/fvg_revert.py
# Original strategy is not modified.

from h85v_common import evaluate_candidate

STRATEGY_KEY = "fvg_revert|enter_long"
ROLE = "fuse_candidate"
SOURCE_STRATEGY_FILE = '/home/z/z/backend/strategies/fvg_revert.py'

def evaluate(candidate, state_rows=None, failure_rows=None, policy=None):
    return evaluate_candidate(
        candidate=candidate or {},
        state_rows=state_rows or [],
        failure_rows=failure_rows or [],
        expected_key=STRATEGY_KEY,
        role=ROLE,
        source_strategy_file=SOURCE_STRATEGY_FILE,
    )
