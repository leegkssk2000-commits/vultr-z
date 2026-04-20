from engine.runner import run_once

# 필요한 전략 이름들 예시 (엔진에 있는 실제 함수명으로 교체)
DEFAULT_STRATEGIES = ["gate_fvg", "kpi_gate", "regime", "slo_gate"]

def dispatch_signals():
    # TODO: 실제 입력데이터 주입
    print("dispatch signals")
    return run_once(DEFAULT_STRATEGIES)
