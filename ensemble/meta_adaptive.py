from ensemble.selector import select
# 간단: 외부에서 regime 주입 없으면 bull
def pick(regime=None):
    return select(regime or "bull")