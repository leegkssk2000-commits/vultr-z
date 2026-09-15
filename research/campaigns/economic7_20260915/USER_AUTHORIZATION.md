repo=leegkssk2000-commits/vultr-z

scope\_key=ZEL\_7CORE\_LONG\_CAMPAIGN\_MATERIAL\_FUSION\_WALKFORWARD\_AFTER\_652671A6F\_V1

첨부된 최신 대화 작업파일 전체를 읽고, 마지막 완료 지점에서 실제 작업을 계속하라.

이 Work은 새 장기 campaign이다.
이전 Chat/Work 내용을 안다고 가정하지 말고 첨부 handoff와 GitHub 저장 증거를 SSOT로 사용한다.

현재 마지막 확인 기준 anchor:

- latest known commit: `652671a6f`
- `strategy_specific_failover_router_v2` 완료
- 기존 generic Router V1은 대체됨
- 현재 경제개발 전면 대상은 아래 7개 lane
- 나머지 20개 전략은 material grade-up / fusion nursery 대상
- Active5 original parent 묶음 개발은 종료
- 기존 완료 실험을 반복하지 않는다.

## 0. 시작 즉시 해야 할 것

1. 최신 `origin/master`와 현재 관련 branch ancestry를 확인한다.
2. commit `652671a6f` 및 이후 이미 병합/완료된 작업을 1회만 확인한다.
3. 이미 완료된 replay/backtest/benchmark는 다시 실행하지 않는다.
4. 작업트리가 dirty이면 기존 변경을 삭제하지 말고 clean worktree를 별도로 생성한다.
5. 기존 runtime/evidence/result/ledger를 보존한다.
6. 기존 Router V2와 frozen candidate의 규칙을 정확히 회수한다.
7. 아래 기존 SSOT/contract가 repo에 있으면 우선 사용한다.
   - `strategy_specific_failover_router_v2`
   - `economic7_core_promotion_roadmap_v2`
   - `material_upgrade_program_v3`
   - `economic_material_policy_v2`
   - `economic_synthesis_router_v2`
   - `economic_dev_execution_split_v1`
8. 실제 경제 실행/후보 번호/예산은 단일 orchestrator만 소유한다.
9. subagent끼리 같은 후보/같은 replay를 중복 실행하지 않는다.

첫 보고에는 반드시:

- 실제 latest master SHA
- `652671a6f` ancestry 여부
- 7 lane 현재 상태
- 20 material 현재 grade
- 실행 중인 persistent producer 상태
- 12\~24개월 데이터 준비 상태
- 이번 Work에서 실제 시작한 parallel jobs
  를 표로 보고한다.

계획만 작성하고 종료하지 말고 실제 구현·실행으로 들어간다.

---

# 1. 최종 목표

우리는 연구 시스템을 만드는 것이 아니다.

목표는:

**비용·슬리피지·실행 현실성을 포함하고, 시장 causal state에 따라 적절한 alpha sleeve로 위험예산을 자동 라우팅하는 실제 경제형 crypto trading engine을 만드는 것.**

이번 Work의 장기 목표:

### A. 7개 개발 lane을 가능한 한 Core 자격까지 승격

1. `Keltner/Holy-Grail`
2. `Trend Rider coherent/stale-scratch`
3. `Break / TREND_DISPERSED`
4. `Supertrend regime specialist`
5. `Squeeze Break / PANIC-long`
6. `Cross-sectional MR V1`
7. `Micro EDGE`

단, **7개를 숫자 맞추기 위해 강제 PASS시키지 않는다.**

Core 자격을 못 얻으면:
`WATCH / DEV / REJECT / MATERIAL`
중 실제 증거에 맞는 상태로 남긴다.

---

# 2. 현재 경제 baseline 보존

Router V2 이전 결과를 다시 최적화 기준으로 되돌리지 않는다.

현재 확인된 개발 baseline에는 최소 다음 특성이 있다.

- signal T 약 `355`
- 약 `2.00 T/day`
- Router V2 Net 약 `+12,093 bps`
- Net expectancy 약 `+34.06 bps/T`
- PF 약 `2.211`
- DD 약 `1,647 bps`
- Max loss streak `14`
- 4월 손실은 causal Squeeze rule로 양수 전환
- 8월 winner preservation 약 `98%` 수준 회복

이 값들은 **development baseline**이지 fresh OOS 승인값이 아니다.

기존 180일 데이터는 이미 반복 관찰되었으므로 앞으로 신규 promotion 판단에서 fresh OOS처럼 취급하지 않는다.

---

# 3. Router V2를 frozen forward로 돌린다

Router V2를 다시 같은 180일에 맞춰 미세튜닝하지 않는다.

핵심 routing contract:

`Market causal state`
→ `strategy-specific health`
→ `GREEN / AMBER / RED`
→ `1.0x / 0.5x / 0.25x 또는 block`
→ 남는 risk는 **동일 시각에 이미 자기 독립 setup을 충족한 GREEN lane**에만 failover
→ 대체 신호가 없으면 `CASH`

금지:

- 월(month)을 feature로 사용
- “7월형이니까 OFF” 같은 사후 규칙
- 다른 전략에 강제 진입 생성
- winner가 컸다는 이유로 미래정보를 사용
- 동일 방향 correlated positions를 독립 거래처럼 취급

유지:

- Trend Rider same-hour/same-direction aggregate crowding cap
- Squeeze strategy-specific causal state
- Rider winner-preservation state
- cash fallback

fresh-forward에서 반드시 저장:

- state snapshot
- strategy health
- chosen risk multiplier
- suppressed risk
- failover receiver
- receiver setup evidence
- cash fallback 여부
- 이후 실제 trade result

---

# 4. 7개 Core campaign을 병렬화한다

각 lane별 전담 subagent를 둘 수 있다.
가능한 한 병렬로 사용하되 경제 실행은 중앙 ledger에서 dedup한다.

## 4.1 Keltner/Holy-Grail

현재 가장 강한 specialist 계보를 보존한다.

중점:

- Raschke식 trend strength
- new momentum high
- first EMA20 retracement ownership
- 재무장은 새로운 momentum이 형성된 뒤만
- 15m → 30m → 1h multi-TF pullback sequence
- RR/fat-tail runner
- fee-adjusted breakeven
- loss streak/DD
- universe 확장 시 quality 희석 검증

기존 좋은 entry/RR 구조를 무너뜨리는 무차별 frequency expansion 금지.

목표:
`edge density`, `T/day`, `PF`, `DD`, `loss streak`을 함께 개선.

---

## 4.2 Trend Rider

현재 `TREND_COHERENT + stale scratch + crowding cap` lineage만 사용한다.

중점:

- GMMA group separation/compression
- thrust shortening
- trend age
- cross-asset continuation
- post-entry volatility expansion
- recent causal MFE distribution
- breadth persistence
- same-direction correlated exposure

특히 3월/7월형 `follow-through drought`를 미래정보 없이 감지할 수 있는지를 fresh evidence로 본다.

진입 삭제보다:
`1x → 0.5x → 0.25x`
risk ownership 변경을 우선한다.

---

## 4.3 Break / TREND\_DISPERSED

side 최적화 금지.

개발 구조:
`contraction`
→ `expansion`
→ `break`
→ `retest`
→ `LPS/continuation`
→ `failed breakout invalidation`
→ runner

Crabel/VCP/Turtle 계열 material을 이용해:

- 한 fat winner 의존 감소
- false breakout 감소
- follow-through quality 개선
  을 검증한다.

---

## 4.4 Supertrend regime specialist

범용 Supertrend로 다시 살리지 않는다.

목표는:
**특정 causal trend/pullback regime에서만 ownership을 갖는 specialist**

기존 fresh/session 계약이 있으면 우선 완료한다.
새로운 임의 threshold tuning보다 preregistered fresh evidence를 우선한다.

---

## 4.5 Squeeze Break

현재 `PANIC_DISPERSION + LONG` child를 anchor로 한다.

Carter 계열:

- BB inside KC
- squeeze duration
- first fire
- momentum direction
- MA alignment
- initial thrust
- momentum decay
- 8\~10 bar lifecycle
- profit protection / runner

특히:

- false fire
- simultaneous multi-symbol fire
- volatility expansion failure
  를 분리한다.

fresh shadow에서 현재 양수 evidence가 쌓이면 별도 promotion ledger로 관리한다.

---

## 4.6 Cross-sectional MR V1

기존 V2/V3 실패를 반복하지 않는다.

V1의 독립성을 보존한다.

추가 연구:

- formation/trading period 분리
- stable pair identity
- normalized spread
- beta/market neutral residual
- displacement magnitude
- convergence speed
- BTC-neutrality
- holding horizon
- 15m / 30m / 최대 1h

단순 threshold 완화로 T를 늘리는 방식 금지.

---

## 4.7 Micro EDGE

OHLCV proxy 금지.

반드시 실제:

- BingX L2
- aggressive trade flow
- multi-level OFI
- depth imbalance/change
- spread
- lagged cross-asset OFI

를 사용한다.

maker/passive execution을 평가하려면 queue/fill model을 먼저 검증한다.
그 모델이 없으면 taker cost authority를 사용하고 maker 수익을 가정하지 않는다.

기존 frozen rule fresh-forward는 수정하지 않고 병렬 수집한다.

12\~24개월 OHLCV backfill이 있다고 해서 L2를 합성하지 않는다.
L2 history가 부족하면 **Micro만 별도의 fresh evidence lane**으로 유지한다.

---

# 5. 12\~24개월 장기 backfill

기존 180일은 너무 짧고 반복 관찰됐다.

이번 Work에서:

- 최소 12개월
- 가능하면 24개월
  의 canonical historical dataset을 구축한다.

가능하면 canonical 1m source에서:

- 15m
- 30m
- 1h
  를 deterministic aggregation한다.

요건:

- synthetic fill 금지
- forward fill 금지
- timestamp gap 검사
- duplicate 검사
- source/hash/receipt 저장
- symbol별 coverage
- fee/slippage authority 고정
- timezone 명시
- cache version/hash 고정

data source가 24개월을 지원하지 않으면 가능한 최대 길이를 사실대로 보고한다.

데이터가 없는 구간을 만들어내지 않는다.

---

# 6. Rolling Walk-Forward

단일 60/40 split을 최종 승격 근거로 사용하지 않는다.

최소 구조:

`formation/train`
→ `next untouched OOS`
→ roll
→ 다음 OOS
→ 반복

window 길이는 전략 TF/빈도에 맞게 설계하되 한 번 정하면 고정한다.

각 OOS window에서:

- T
- T/day
- WR
- gross expectancy/T
- cost/T
- net expectancy/T
- PF
- DD
- max loss streak
- average win/loss
- payoff
- monthly consistency
- symbol concentration
- single-winner concentration
- strategy correlation
- Edge Density=`NetExp/T × T/day`

를 저장한다.

한 window/한 달/한 symbol/한 fat winner가 전체 PASS를 만들면 Core 승격 금지.

이미 관찰한 180일 구간은 development/history로만 사용하고 fresh OOS로 라벨링하지 않는다.

---

# 7. Fresh-forward를 7개 동시에 수집

7개 전략을 하나씩 순차 수집하지 말고 **동시에 frozen-rule producer**로 운용한다.

요건:

- rule hash
- code SHA
- data source
- symbol
- timeframe
- setup timestamp
- state
- entry/exit
- gross
- fee
- slippage
- net
- MFE/MAE
- exit reason
- risk multiplier
- router decision

을 durable ledger에 남긴다.

프로세스 죽음/재부팅 시 자동 복구:

- systemd/watchdog/checkpoint
- idempotent resume
- duplicate close 방지

fresh-forward가 충분히 쌓이지 않았으면 **설비 구축 완료와 Core 승격을 혼동하지 않는다.**

---

# 8. 외부 benchmark 대규모 조사

이번 Work에서 병렬 research subagent를 적극 사용한다.

우선순위:

1. 원저자/공식 문서
2. 원 논문
3. 저자 인터뷰
4. 재현 가능한 전문 2차 자료
5. 커뮤니티 자료는 hypothesis 전용

단순 “조사 완료” 금지.

benchmark 완료 조건은 반드시:

`source`
→ `mechanism`
→ `causal observable`
→ `exact event grammar`
→ `entry`
→ `invalidation`
→ `lifecycle`
→ `execution`
→ `code binding`
→ `economic replay`
→ `walk-forward`

까지 연결된 경우다.

각 benchmark receipt에:

- URL/source
- author
- source tier
- exact quoted/paraphrased rule
- timeframe/context
- crypto translation assumption
- implementation file
- result
  를 저장한다.

전략 이름만 가져와 generic indicator 몇 개 붙이는 방식 금지.

---

# 9. 나머지 20개 Material Grade-Up

현재 20개 material baseline:

### C

- `rbreaker_like`
- `rsi_swing_fail`
- `trend_ma_macd`
- `turtle_trend`

### D

- `alpha_combo`
- `anchor_vwap_trend`
- `ema_ribbon_scalp`
- `grid_rebalance`
- `obv_trend`
- `pivot_reversal`
- `vol_spike_fade`
- `vwap_revert`

### HOLD

- `bb_revert`
- `fvg_revert`
- `liquidity_sweep`
- `mfi_rsi_div`
- `range_fade`
- `scalp_snap`
- `session_bias`
- `sr_levels`

현재 A/B material이 없다는 상태를 baseline으로 보존한다.

---

# 10. Material 등급상승 원칙

material은 standalone strategy와 동일하게 평가하지 않는다.

역할을 명확히 하나로 고정:

- `entry_quality`
- `context_filter_or_veto`
- `exit_or_risk`
- `execution/microstructure`

한 material이 여러 역할을 동시에 수행하게 하지 않는다.

### C → B

한 번에 한 축만 개선한다.

검증:
`host alone`
vs
`host + material`

marginal contribution으로:

- Net
- PF
- DD
- loss streak
- winner preservation
- T retention
  을 비교한다.

standalone은 약해도 host의 손실을 causal하게 줄이면 B 후보가 될 수 있다.

### D

entry 생성권을 주지 않는다.
먼저 veto/context/exit-risk sidecar 가치부터 검증한다.

### HOLD

data/execution/sample deficiency부터 해결한다.
증거 없이 등급을 올리지 않는다.

---

# 11. B×B Fusion Tournament

과거 C×C heavy search 실패를 반복하지 않는다.

**C×C 무차별 tournament 금지.**

최소 B가 실제 생성된 뒤에만 B×B를 시작한다.

예:

### Break

`Turtle persistence(B)`
\+
`RBreaker structure(B)`

### Trend Rider

`trend-quality(B)`
\+
`participation/OBV(B)`

### Squeeze

`compression/fire(B)`
\+
`volume participation(B)`
\+
필요 시 별도 risk sidecar

### MR

`relative-value anchor(B)`
\+
`stable pair formation(B)`

### Micro

`Liquidity Sweep L2(B)`
\+
`Scalp Snap exhaustion(B)`
\+
`integrated OFI(B)`

규칙:

- behavior cosine > 0.85 → duplicate, 합성 금지
- 역할이 같은 B+B보다 상호보완 역할 우선
- 한 fusion child에서 새 축은 최대 2개
- 결과 보고 전 규칙 동결
- parent/material receipts 모두 보존
- 경제 FAIL 조합 재실행 금지

B×B가 fresh/rolling에서 통과하면 A composite 후보로 승격한다.

A composite가 되어야 Core host에 실제 이식 후보가 된다.

---

# 12. Core 승격 Gate

최종 목표는 7개 Core지만 강제 승격하지 않는다.

최소 순서:

`Frozen rule`
→ `Fresh Net > 0`
→ `rolling OOS 반복 양수`
→ `PF target 충족`
→ `DD/LS budget 충족`
→ `T/빈도 충분`
→ `월/symbol/single-winner concentration 허용범위`
→ `기존 Core와 낮은 중복`
→ `portfolio marginal value > 0`

PF 목표는 기존 roadmap의 `≥1.2`를 최소 연구 기준으로 사용하되, repo SSOT에 더 엄격한 값이 있으면 SSOT를 따른다.

Core 승격 실패 시 증거를 삭제하지 말고 정확한 상태를 남긴다.

---

# 13. Portfolio / Failover 경제검증

개별 전략 PASS만 보지 않는다.

각 Core 후보가 추가될 때마다:

`existing portfolio`
vs
`portfolio + candidate`

를 비교한다.

필수:

- total T/day
- net/day
- Edge Density
- PF
- DD
- max LS
- positive month ratio
- tail loss
- fat-tail winner preservation
- simultaneous exposure
- correlation
- strategy ownership
- cash ratio
- failover utilization
- suppressed risk
- reallocated risk

특히 한 전략이 RED가 됐을 때 다른 전략이 실제 신호로 손실구간을 메우는지 검증한다.

“대체 전략이 있었다면 벌었을 것” 같은 사후 추정 금지.
당시 실제 signal/state가 존재한 경우만 failover로 인정한다.

---

# 14. Subagent 최대 활용

이 Work에서는 병렬 subagent를 적극 사용한다.

권장 구조:

- Orchestrator / economic ledger owner 1
- Data/backfill agent
- Walk-forward agent
- Keltner agent
- Trend Rider agent
- Break agent
- Supertrend agent
- Squeeze agent
- MR agent
- Microstructure agent
- External benchmark research agents
- Material grading agents
- Fusion tournament agent
- QA/CI reviewer
- Merge/integration owner

단:

- 동일 economic candidate 중복 실행 금지
- 서로 같은 파일을 동시에 무질서하게 수정하지 않는다.
- 필요하면 전략별 clean worktree를 사용한다.
- 최종 병합은 단일 integrator가 담당한다.
- subagent가 낸 아이디어는 경제 실행 전 중앙 registry에서 candidate id를 발급받는다.

---

# 15. CI / PR / Merge

유효 변경은 로컬 실험으로 끝내지 않는다.

필수:

- unit/integration test
- replay/self-test
- Black
- Ruff
- Mypy
- 관련 기존 CI
- independent review
- 정상 PR
- merge
- merged SHA
- master CI
- fixed merged revision 재현

실패하면 가장 작은 원인만 수정한다.

대규모 refactor로 실험 성공을 덮지 않는다.

---

# 16. 금지사항

- 7개를 억지로 Core PASS 처리
- 월 이름 기반 filter
- 미래 PnL/MFE/MAE를 entry feature로 사용
- holdout을 본 뒤 같은 holdout에 threshold 재튜닝
- 180일 반복 최적화를 fresh OOS라고 부르기
- OHLCV를 L2 proxy로 사용
- maker fill 검증 없이 maker economics 주장
- T를 거의 없애 WR/PF만 예쁘게 만들기
- 한 fat winner가 전체 결과를 만든 후보 승격
- C×C exhaustive search
- B가 없는데 B×B tournament를 가짜로 수행
- benchmark 조사만 하고 구현 안 한 상태를 완료라고 표시
- 이미 실패한 후보/조합 반복
- 기존 evidence/ledger 삭제
- dirty tree에 reset --hard / clean -fdx
- LIVE/order authority 임의 활성화

이 Work는 연구/검증/경제개발 권한이다.
명시적 별도 승인 없이는 실제 주문 권한을 열지 않는다.

---

# 17. Work가 오래 걸릴 때의 처리

fresh-forward 자체는 시간이 필요한 작업이다.

따라서 한 Work 실행 안에 필요한 표본이 아직 안 쌓이면:

- producer를 durable하게 설치
- 자동복구 확인
- 현재 accrued T 저장
- exact frozen rule/hash 저장
- 다음 재개 위치 저장
- 부족한 표본을 부족하다고 보고

하고 끝낸다.

표본이 없는 상태를 PASS/FAIL로 꾸미지 않는다.

반대로 backfill/rolling/material tournament처럼 지금 계산 가능한 작업은 중간에 멈추지 말고 가능한 범위까지 실제 완료한다.

---

# 18. 보고 형식

## 첫 중간보고

1. latest SHA / ancestry
2. 7 Core lane state
3. Router V2 state
4. 20 materials grade
5. 12/24m data state
6. fresh producer state
7. 병렬 subagent/job 목록
8. 실제 신규 실행 candidate 수

## 경제결과 표

각 전략마다:

`strategy | state | TF | T | T/day | WR | avg win | avg loss | payoff | gross/T | cost/T | net/T | PF | DD | maxLS | positive months | concentration | rolling OOS | fresh T | verdict`

## Material 표

`material | old grade | role | change | marginal Net | ΔPF | ΔDD | T retention | behavior cosine | new grade | verdict`

## Fusion 표

`composite | materials | roles | prereg rule | T | net/T | PF | DD | OOS | fresh | verdict`

## Router 표

`state | payer strategy | old risk | new risk | receiver | receiver-valid-signal | cash fallback | realized delta`

---

# 19. 최종 성공 조건

이번 campaign의 성공은 “실험 많이 함”이 아니다.

성공은 다음 중 실제 증거가 생기는 것이다.

1. 7 lane 중 Core 자격을 획득한 전략 수 증가
2. 기존 Core portfolio의 fresh/rolling 경제성 강화
3. negative regime에서 strategy failover가 실제 DD/PF를 개선
4. 20 materials 중 B/A grade material 생성
5. 검증된 B×B composite 생성
6. portfolio T/day가 늘면서 Net/T/PF/DD가 동시에 경제적으로 유지
7. 12\~24개월 + rolling + fresh evidence가 서로 모순되지 않음
8. 한 달/한 코인/한 winner 의존도가 감소
9. live-ready가 아니면 명확하게 BLOCKED 유지

---

# 20. 작업 종료 규칙

설명이나 새로운 roadmap만 만들어놓고 종료하지 않는다.

실제:
**확인 → 구현 → 실행 → 경제검증 → 리뷰 → CI → PR → merge → merged revision 재검증**

까지 가능한 범위는 완료한다.

단, fresh-forward처럼 물리적으로 시간이 필요한 증거는 거짓으로 완료하지 않는다.

마지막 보고에는 반드시:

- Core 승격된 전략
- DEV/WATCH/REJECT 전략
- 전략별 fresh T
- rolling walk-forward 결과
- 12\~24m 결과
- Router V2 forward 결과
- material C/D/HOLD → B/A 변화
- B×B tournament 결과
- 경제 portfolio 최종표
- 월별/연패/DD
- 남은 구조적 병목
- PR 번호
- merge SHA
- master CI
- 다음 재개용 durable handoff

를 한 번에 보고한다.

**핵심 원칙: 7개 전략을 억지로 좋게 보이게 만드는 것이 아니라, 7개가 서로 다른 시장 상태의 실제 양수 alpha가 되도록 만들고, 약해지는 전략의 자본을 그 순간 실제로 살아있는 다른 전략이 인수하는 경제 매매 엔진을 완성한다.**