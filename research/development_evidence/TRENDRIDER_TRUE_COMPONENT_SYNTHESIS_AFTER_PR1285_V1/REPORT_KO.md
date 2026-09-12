# TrendRider TRUE component synthesis — 최종 보고

**TrendRider Unified v1 = 생성안됨**

최종 상태: `TRUE_COMPONENT_SYNTHESIS_NOT_EARNED`

이번 scope는 Issue #1272의 원래 목표대로 Historical Primary exact16/81.25%와 Historical Broad exact30/70%의 실제 저장 증거만 사용했다. `P_COMMON`, `B_COMMON` proxy-common 결과, generic G1~G6는 parent/component 입력으로 사용하지 않았다.

## Immutable parents

| lane | T | WR | net bps | expectancy bps/T | PF | payoff | DD bps |
|---|---:|---:|---:|---:|---:|---:|---:|
| Primary exact core | 16 | 81.25% | 23297.7694 | 1456.1106 | 64.5012 | 14.8849 | 219.0678 |
| Broad exact parent | 30 | 70.00% | 34960.5772 | 1165.3526 | 60.8148 | 26.0635 | 413.7930 |

## Actual good component pool

`BROAD_WR80_STATE`만 GOOD quality component로 재검증되었다.

원본: PR #1056 / run 33125478124 / artifact 9668303286.

규칙: non-US는 허용하고, US에서는 `current chase_atr <= prior closed-bar chase_atr`일 때만 허용한다. 숫자 threshold sweep은 없다.

Historical Broad profile:
- 25T / WR 80%
- net +32984.2077 bps
- expectancy +1319.3683 bps/T
- PF 90.0147
- payoff 22.5037
- DD 310.0388 bps

`PRIMARY_HIGHAMP_PERSISTENCE`는 원본 PR #1044/run 33112033729/artifact 9663068779을 1회 복구 감사했으나, 원래 frozen24의 3-bar decision-time bar/feature payload가 저장되지 않아 `UNAVAILABLE_NO_PROXY`로 확정했다. 최신/대체 데이터로 재계산하지 않았다.

HTF_UP, transition add-only, donor state gates, fresh2/positive2는 기존 원본 증거상 약화 축 또는 불완전 source가 있어 synthesis GOOD pool에서 제외했다.

## U1 — 실제 좋은 부분만 합성

고정 architecture:

`PRIMARY_EXACT16_CORE OR (BROAD_ONLY AND EXACT_BROAD_WR80_STATE)`

Identity 결과:
- Primary/Broad overlap: 15
- Primary-only: 1
- Broad-only: 15
- WR80 selected: 25
- WR80 중 Broad-only 실제 추가분: **10T**
- Primary exact core retention: **100%**

Broad-only 추가 10T 자체:
- 10T / 7W / WR **70.00%**
- net **+9467.3705 bps**
- expectancy **+946.7370 bps/T**
- PF **43.5063**
- payoff **18.6456**
- DD **162.2192 bps**

최종 U1:

| candidate | T | wins | WR | net bps | expectancy bps/T | PF | payoff | DD bps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Primary exact16 | 16 | 13 | 81.25% | 23297.7694 | 1456.1106 | 64.5012 | 14.8849 | 219.0678 |
| U1 TRUE synthesis | 26 | 20 | **76.92%** | **32765.1399** | **1260.1977** | **56.5703** | **16.9711** | **310.0388** |

### Gate
PASS:
- Primary core retention = 100%
- Broad-only addition >=1
- final net > Primary
- payoff >= Primary
- DD <= Broad
- identity integrity clean

FAIL:
- WR >= Primary 81.25% → **76.92% FAIL**
- expectancy >= Primary 1456.11 → **1260.20 FAIL**
- PF >= Primary 64.50 → **56.57 FAIL**

따라서 U1은 수익 총액은 +9467bps 늘었지만 Primary의 selection quality를 희석했다. 특히 Broad의 WR80 component 전체는 80%였지만, Primary와 겹치는 15개를 제거하고 실제로 새로 추가되는 Broad-only 부분만 보면 10T/70%였다. 즉 해당 component의 강한 부분 상당수가 이미 Primary core에 포함되어 있었고, 남는 orthogonal contribution은 Primary quality를 유지하지 못했다.

## Robustness / handoff

Historical exact synthesis gate에서 FAIL했으므로 robustness replay는 규칙대로 실행하지 않았다.

- robustness: `NOT_RUN_HISTORICAL_GATE_FAILED`
- prospective G5A handoff: false
- formal credit: 0
- live/order/deploy: 0
- numeric rescue / threshold sweep / proxy substitution: 0

이 scope에서 추가 숫자조정 또는 새 component 발명은 하지 않는다.
