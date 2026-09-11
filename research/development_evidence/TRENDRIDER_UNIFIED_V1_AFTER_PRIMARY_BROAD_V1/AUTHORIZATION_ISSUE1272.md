scope_key=TRENDRIDER_UNIFIED_V1_AFTER_PRIMARY_BROAD_V1
status=AUTHORIZED_EXECUTE_NOW

## 0. 목적
TrendRider Primary와 TrendRider Broad를 영구적인 두 전략처럼 유지하는 구조를 종료하고, 두 lane의 **재현 가능한 장점만 인과적으로 합친 단일 `TrendRider Unified v1`**을 만든다.

이번 작업은 과거 승리거래를 outcome 보고 합치는 union이 아니다. 기존 두 lane은 immutable parent/control로 보존하고, 결과를 보기 전에 entry-observable 규칙을 동결한 **새 unified child 하나**를 만든다.

현재 master 관측=`c768828077b9d5310dc53bff0243a9e4ffbc2f4a`; reset 기준이 아니다. 시작 시 최신 origin/master 확인 후 이후 master 이력 보존.

## 1. 부모 상태와 역할
### Primary — quality donor
- lane=`trend_rider_primary_wr8125`
- frozen parent=16T / 81.25% WR
- latest strict ceiling=24T / 87.5% (historical diagnostic only)
- current terminal=`FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED`
- 6M robustness: 224T, net +87.21bps, expectancy +0.389bps/T, PF 1.0046
- recent3M: 123T, net -4275.95bps, expectancy -34.76bps/T, PF 0.6008
- donor cells exhausted, donor winners0

따라서 Primary 전체를 incumbent로 되살리지 않는다. **81.25%를 만든 entry-quality gene을 설명하는 donor/control**로만 사용한다.

### Broad — coverage/economic parent
- lane=`trend_rider_broad_wr7000`
- frozen parent=30T / 70% WR
- historical G4 economics: net 34960.58bps, expectancy 1165.35bps/T, PF 60.81, payoff 26.06, DD 413.79bps
- current role=`G4_ECONOMIC_SURVIVOR`
- 기존 G5 replay/proxy 21T는 0 wins, expectancy -100.95bps/T이나 production_grade_T=0이며 formal production PASS/FAIL로 재해석 금지

Unified는 **Broad coverage를 기본으로 하되 Primary의 quality gene으로 Broad-only 추가기회를 선별**하는 방향을 우선한다.

## 2. 핵심 unified architecture
기본 형태를 다음으로 고정한다:

`UNIFIED_SIGNAL = PRIMARY_SIGNAL OR (BROAD_ONLY_SIGNAL AND ADD_ONLY_QUALITY_GATE)`

- `PRIMARY_SIGNAL`: exact frozen Primary policy identity에서 발생한 신호.
- `BROAD_ONLY_SIGNAL`: Broad에는 있으나 같은 opportunity identity에서 Primary에는 없는 신호.
- `ADD_ONLY_QUALITY_GATE`: signal/entry 시점에 관측 가능한 causal feature만 사용.
- Primary/Broad가 동시에 신호이면 하나의 opportunity/trade만 생성; 중복 진입 금지.
- exit/risk/size는 비교 공정성을 위해 parent 공통 owner를 우선 유지하며, 이 sprint에서 entry architecture 외 축을 동시에 바꾸지 않는다.

목표는 **Primary의 선택정밀도 + Broad의 coverage/large-winner 기회**를 하나의 entry architecture로 합치는 것이다.

## 3. 금지
- Primary winner membership이나 Broad winner outcome을 직접 rule로 사용.
- 승리/패배 trade_id, symbol, 연도, 세션을 결과 보고 예외 처리.
- 기존 Primary/Broad policy 자체를 rewrite.
- 같은 lane+axis의 과거 실패를 숫자만 바꿔 재시험.
- threshold/grid/sweep.
- exit/SL/TP/RR/position size 동시 변경.
- fresh/prospective/G5B data를 DEV feature discovery에 사용.
- 현재 Squeeze v1 prospective qualification data 접근/혼합.
- paid Gemini/OpenAI.
- live/order/deploy.

## 4. Stage 0 — exact parent reconstruction / common opportunity ledger
경제실행 전에 두 parent를 **동일한 opportunity identity와 동일한 frozen data/cost clock** 위에서 재구성한다.

필수:
- Primary exact16 membership/hash/receipt parity.
- Broad exact30 membership/hash/receipt parity.
- overlap / Primary-only / Broad-only opportunity 전수 분해.
- 동일 underlying signal/opportunity 중복 제거.
- parent별 entry decision 시점의 observable feature snapshot 저장.
- 당시 outcome은 attribution용 answer column으로 격리하고 feature selection에는 직접 사용 금지.
- 과거 PR #1044/#1052 등 lane donor/ADD_ONLY 시도 및 attempted-axis ledger를 읽어 중복 axis 제거.

부모 parity 실패 시 후보 경제실행 금지하고 BLOCKED_PARENT_PARITY로 종료.

## 5. Stage 1 — quality gene decomposition, cheap screen
새 canonical candidate 번호를 소비하지 않고 최대6개의 **서로 다른 causal gene/mechanism**만 screen.

우선 inventory는 과거 source/attempted-axis에서 실제 존재가 확인되는 entry-observable feature만 사용:
- session state
- st_gap_state
- chase_state
- atr_state
- geometry_balance
- directional/persistence state

단, 이미 동일 lane+axis에서 terminal reject된 형태는 재사용 금지. 숫자 threshold는 새로 sweep하지 않는다.

각 gene은 Broad-only opportunity에서 다음을 측정:
- admitted / rejected T
- WR
- net / expectancy / PF / payoff
- cost2
- DD contribution
- ordinary/top-decile winner retention
- loss removal vs winner clipping
- Primary overlap preservation
- signal-day/symbol/regime concentration
- causal prefix / lookahead / duplicate

Stage1은 FULL lifecycle 후보가 아니라 **Broad-only ADD_ONLY cohort의 quality screen**이다.

Hard gates는 기존 SSOT economics를 완화하지 않는다:
- causal/integrity PASS
- net expectancy >0
- PF >=1
- payoff >=1
- cost2 survival positive
- winner retention >=60%

최대2 gene survivor. survivor0이면 outcome 복사를 강제하지 말고 unified architecture를 만들지 않은 채 `NO_CAUSAL_UNIFIED_GENE`로 종료.

## 6. Stage 2 — Unified child 최대2개, chronological FULL
Stage1 survivor만 canonical economic child로 만든다.

- `U1 = PRIMARY OR (BROAD_ONLY AND best_gene)`
- survivor가 2개이며 서로 orthogonal할 때만 결과 전에 동결한 `U2 = PRIMARY OR (BROAD_ONLY AND geneA AND/OR geneB)`를 1개 추가 허용.
- AND/OR 선택은 outcome 전에 mechanism semantics로 결정하고 freeze; 결과 보고 바꾸지 않는다.
- 같은 축이면 U2 금지.

최대2 candidates. 동일한 승인된 USED_DEV/common historical partitions에서 chronological FULL 각 candidate×각 partition first1만 실행. parent controls는 exact saved identity로 재사용 가능하면 replay0; common-baseline parity에 필수면 control replay를 별도 candidate로 세지 않되 1회만 허용.

필수 FULL:
- actual chronological occupancy
- same-symbol conflict
- fee/funding/cost2
- open/censored
- DD/exposure/loss tail
- new/removed/displaced trades
- Primary core retention
- Broad-only accepted/rejected contribution
- ordinary/top10 winner retention
- concentration/top1 dependency

## 7. Stage 3 — final TrendRider Unified v1 선택
비교표:
`Primary control | Broad control | U1 | U2(if exists)`

최종 선택은 WR 한 숫자만 최대화하지 않는다. 기존 SSOT 경제 gate를 모두 통과한 후보만 대상으로:
1. 두 개발 partition 모두 net/expectancy/PF/payoff/cost2 non-fail.
2. Primary core의 일반/큰 winner 훼손과 Broad coverage 손실을 함께 보고.
3. Pareto 비교: worst-window expectancy, PF, WR, DD, winner retention, concentration.
4. 한 후보가 다른 후보를 Pareto dominate하면 그 후보 선택.
5. tradeoff가 남으면 더 단순한 rule / fewer axes / 더 낮은 concentration을 deterministic tie-break로 사용.

survivor가 없으면 **Broad를 다시 final이라 부르지 말고 `TREND_RIDER_UNIFIED_NOT_EARNED`**로 종료. 새로운 numeric rescue 금지.

survivor가 있으면 exact identity를:
`TrendRider Unified v1`
로 seal하고 strategy digest / code SHA / parent receipts / gene receipts / data-cost hashes / exact rules를 묶는다.

## 8. Hard stop / prospective handoff
이번 bounded sprint 뒤 자동 미세개선 금지.

Unified v1이 만들어지면:
- Primary/Broad는 historical control/archive로 유지.
- Unified 하나만 차기 prospective G5A qualification lane으로 준비.
- DEV에 사용한 데이터는 formal future credit=0.
- 깨끗한 prospective qualification boundary를 새로 만들어야 함.
- G5A qualification dataset과 그 뒤 G5B fresh dataset은 시간적으로 분리.
- G5B terminal 전 G6 금지.

Unified가 만들어지지 않으면 Primary/Broad를 억지 합성하지 말고 결과와 blocker를 보고 후 종료.

## 9. 예산/병렬화
병렬 허용:
- parent identity/history audit
- feature/gene decomposition
- Stage1 screens
- causal/red-team/accounting review

단일 Economic Owner:
- candidate numbering
- FULL dispatch
- ledger persist

예산:
- Stage1 gene screens max6 / canonical candidate0
- Stage2 canonical candidates max2
- chronological FULL max4 (+ parent parity에 절대 필요한 control replay 최대2, 중복 금지)
- retry/sweep/FIXED arbitrary OOS/new prospective decode/paidAI/live/order/deploy=0

## 10. 첫 보고
먼저 한눈에:
1. Primary/Broad exact identity와 현재 상태.
2. overlap / Primary-only / Broad-only T.
3. 과거 attempted axis 표와 이번 재사용 금지 목록.
4. Stage1 gene screen 표.
5. survivor<=2.

## 11. 최종 보고
- `Primary | Broad | U1 | U2` 경제표
- T/WR/net/expectancy/PF/payoff/DD/cost2/loss-tail/exposure
- Primary winner retention
- Broad-only accepted contribution
- removed loser / clipped winner
- signal overlap/new/displaced
- concentration
- final `TrendRider Unified v1` exact rules/digest 또는 `TREND_RIDER_UNIFIED_NOT_EARNED`
- 총 candidates/FULL
- CI/review/normal PR merge/exact merge verification
- prospective G5A handoff 상태

완료 후 이 scope만 REPORT_ONLY로 닫고 자동 후속 tuning을 만들지 마라.

