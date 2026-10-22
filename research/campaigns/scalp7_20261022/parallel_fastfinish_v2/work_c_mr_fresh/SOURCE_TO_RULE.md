# MR frozen source → default-OFF forward preparation

**규칙 원문은 준비용 adapter를 작성할 만큼 완전하다.** 이번 대상은 이미 존재하는 `mr_reexpansion_bar4_30m_causal_control_v2` callback이다. 기존 native 함수를 재사용하는 default-OFF 입력·관측 연결이며, 새로운 MR 규칙이나 producer를 만드는 작업이 아니다. 실제 source/cost/계정 점유를 검증하거나 fresh PASS를 부여하지 않는다. 경제 실행·fresh T·주문은 모두 0이다.

`SOURCE_CONTRACT.json`의 rule은 synthetic 결과를 보기 전에 기존 원문에서 고정했다. 입력 schema 보강은 시각·provenance·중복·예약 검증용이며 entry/exit 수치와 순서는 바꾸지 않는다.

## Immutable identity와 원문

Master source context는 `d84623cdc7cf8a87022ab7448ae2624215321177`, 보존하는 C branch base는 `8afdaf552e24041fdc681d6d99817d43a75c20c9`다. 선택한 native module의 C base bytes와 master bytes가 동일한 SHA256임을 확인했다.

| 역할 | 원문 경로 / 함수 | 고정 SHA256 |
|---|---|---|
| 기존 frozen 결과·rule | `research/campaigns/scalp7_20260915/SCALP7_MR_REEXPANSION_EXIT_V1.json` | `4ede29c5186648d22ed11f9740a73a75a76e943f051c0dc58311b1ecbcca8731` |
| Legacy child | `backend/research/rebuild/a1_scalp7_mr_reexpansion_exit_v1.py::should_fail_reexpand/replay` | `08fc3c9f07c32f63123ea05f6e4ebf52bbf772d25661ffa7a7bce68871d55c8d` |
| Legacy parent / 6h pair 생성 | `backend/research/rebuild/a1_cross_sectional_mean_reversion_v1.py::build_market/replay` | `f2907e37144666d0540e343274406d7543edb8fab7f2ebb5449d5013f42dfe8f` |
| 재사용하는 native callback | `backend/research/rebuild/scalp7_mr_formation_v2.py::generate_signals/_control_signals/_frame/exit_update` | `1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5` |
| 기존 observed clock proof 검증 | `backend/research/rebuild/scalp7_observed_paper_v3.py::_usable` | `368b3e516438ab82222117d0200e9a71af578e7674c1aebb936d736c16590308` |
| 기존 actual clock barrier source | `backend/research/rebuild/scalp7_source_clock_v3.py` | `a42e6484d321f82c37fe815c3631cef30a9a124864d69404ec995319ff929814` |

Native module의 Git blob은 `0f76134ace2701dcad17ac6d8427c0e84b9e1feb`이다. Active signal/exit 계산의 repo 함수 closure는 위 native 파일 안에서 끝나며, 외부 수치 의존성은 NumPy/Pandas다. Clock 검증은 기존 `_usable → _ms → _num` 순수 helper만 호출한다. 해당 module의 import closure와 source/data/execution 비교 원문까지 15개 path/blob/SHA를 contract에 기록했다. `poll`, `quote_request`, `initialize`, `main`, legacy `replay`, 경제 engine을 시작하지 않는다.

## 정확한 기존 규칙

Universe 순서는 **BTC, ETH, SOL, XRP, LINK, DOGE USDT futures**다. 이 순서는 argmax/argmin 동률 처리에도 사용하므로 재정렬하거나 일부 상품만 선택하지 않는다.

1. 30m close의 `r_s(t)=close_s(t)/close_s(t−12 bars)−1`을 계산한다. 12 bars가 6h다.
2. 현재 return 최대 상품이 leader, 최소 상품이 laggard다. 현재 spread가 3% 이상이고, 직전 봉과 leader/laggard가 같으며, 현재 spread가 직전보다 엄격히 작을 때 원문 entry가 성립한다.
3. 원래 laggard long 0.5와 leader short 0.5, gross weight 합 1인 pair를 고정한다. 원래 두 상품과 signal spread를 position metadata에 보존한다.
4. 원 signal 이후 held bar 4부터 **원래 pair**의 현재 trailing 6h return 차이가 signal spread 이상으로 재확대하면 exit를 요청한다. 이후 시장의 새 leader/laggard로 교체하지 않는다.
5. 그렇지 않으면 held bar 8에서 만료한다. bar 8에서 재확대도 성립하면 native callback의 reason은 `THESIS_REEXPAND_FAIL_BAR4`가 `TIME_8BAR`를 덮는다. 숫자나 우선순위를 새로 고르지 않는다.
6. 같은 close에서 exit를 결정하고 대체 entry까지 만들지 않는다. Native signal 생성은 identity별 global pair occupancy를 유지한다. 외부 상품의 자금 예약은 별도 receipt로 검사한다.

이 MR에는 **hard stop, TP, partial, trailing stop, volume gate, regime filter가 없다.** 단일 방향 전략의 stop-first overlay를 이식하면 다른 전략이 된다. 따라서 stop 관련 negative case는 임의의 SL을 추가하지 않고 native `stop_price=None` 및 원본 signal geometry 보존을 검사해야 한다. Pair gap은 임의 stop/close 가격으로 처리하지 않는다.

Legacy `regime_lookup`는 기존 train/hold 및 기록용 regime 설명에 사용되며, MR entry/exit 필터가 아니다. Weekly BTC/ETH 회귀 formation, z-score·beta·mean-reached exit는 `mr_btceth_weekly_formation_30m_v2`라는 **다른 identity**이므로 이번 경로에서 선택하지 않는다.

## 신호 생성에 필요한 실제 관측

| 정보 | 필요한 상태 | 결손 처리 |
|---|---|---|
| 공통 시장 prefix | 6개 상품 모두 동일 UTC 30m grid, 중복 없는 순서, finite positive OHLC, 올바른 high/low, open/close/available timestamp, segment ID | 누락 상품을 버리거나 전진 채움하지 않고 HOLD |
| 6h feature | 현재 return에 13개 close, 직전 return 비교까지 14개 close. 기존 native warmup index 20 때문에 최소 21개 연속 봉을 보존 | gap을 압축해 12행을 6h라고 부르지 않음 |
| Signal clock | 현재 close와 모든 상품 availability, 이전 native decision 중 최댓값. 실제 as-of까지 사용할 수 있는 완료 봉만 전달 | 미래 봉·미마감 봉·늦은 source를 과거 close로 backdate하지 않음 |
| Exit clock/history | 원래 두 상품 각각 현재 close까지 13개 연속·동일 segment 봉; 모든 feature가 결정 시점 이전에 available | 빠진 pair history/다른 geometry/가짜 held bar를 거부 |
| Source receipt | Frame digest, source identity/cursor digest, observed/received/usable 시간과 기존 full clock proof가 원문 bytes에 연결됨 | Self-hash 일치만으로 exchange origin을 인증했다고 주장하지 않음 |
| Reference clock | 실제 caller의 wall/monotonic 증거가 역행하지 않고 source usability 및 as-of를 감쌈 | 시각 보정·허용오차·미래 timestamp 재작성 없음 |
| 비용 | 양수 finite의 6개 round-trip reference scenario; 선택 pair의 0.5/0.5 가중 1x 및 그 비용의 2x | unknown을 0으로 채우지 않음. 외부 실제 fee/funding 검증으로 승격하지 않음 |
| Volume | MR feature에 사용하지 않음 | UNKNOWN unit 그대로 유지; OFI나 volume 신호 생성 금지 |
| 계정 점유 | Caller의 snapshot-bound occupancy receipt와 pair 예약을 확인. 다른 상품이 account capital을 쓰는 경우도 포함 | 예약을 새로 쓰거나 해제하지 않음; 미예약은 `PENDING_EXTERNAL_CAPITAL_RESERVATION` |

기존 `scalp7_source_data_v2.aggregate_minutes(observed=True)`는 실제 constituent receipt의 최댓값으로 available time을 정하고 불완전 UTC bucket을 제외한다. 그 source의 historical `BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY`는 실제 미래 관측 receipt가 아니다. 이번 source review가 새로운 시장 데이터나 cursor를 수집하지 않았다.

완료 봉의 실제 수신은 model next-open보다 늦을 수 있다. 기존 pair engine은 `signal_ts_ms > signal_open_ts_ms+30m`를 `LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL`로 거부하며, 늦게 available한 보유 중 봉도 unresolved로 처리한다. Adapter는 원 신호를 관측 자료로 보존할 수 있지만 그 과거 open에서 체결했다고 하지 않는다. 다른 다음 open으로 조용히 밀거나 same-close로 바꾸는 것도 하지 않는다. 실제 fill은 별도 owner 결정과 양쪽 leg의 관측·execution 계약이 필요하다.

## 이미 존재하는 세 결과를 분리

아래는 **저장 원문 읽기**이며 새 replay나 새 수익이 아니다.

| 저장 identity | T | Net 1x 합산 trade-bps | PF 1x / WR | DD 1x 합산 trade-bps | Net 2x 합산 trade-bps | 분류 |
|---|---:|---:|---|---:|---:|---|
| Legacy frozen child | 61 | +386.379717 | 1.228793 / 57.3770% | 411.151841 | 이 legacy JSON에 미기재 | Old DEV; used hold 35T +145.526444; fresh 아님 |
| Causal-control parent | 75 | +188.812963 | 1.083412 / 56.0000% | 797.472755 | −927.373868 | `ROLLING_DIAGNOSTIC_FRESH_REQUIRED`, fresh T=0 |
| Causal-control bar4 child | 82 | +10.072568 | 1.003888 / 48.7805% | 634.455006 | **−1206.756009** | `ROLLING_DIAGNOSTIC_FRESH_REQUIRED`, fresh T=0 |

Later child의 Gross는 1226.901144, 1x Cost는 1216.828577이다. 2x PF는 0.627628, MaxLS는 1x/2x 모두 6이다. DD는 동시 outcome cohort를 합친 **realized equal-notional trade-bps drawdown**이며 account NAV나 open mark-to-market DD가 아니다. Child는 matching parent보다 1x DD가 작아졌지만 WR/Net이 약해졌고 양쪽 모두 2x에서 음수다. 이 증거를 61T 초기 양수 뒤에 숨기지 않는다.

Later child 원문 receipt SHA256은 `8484e929c5cced51148b6d8b6969b03d50fb15406cad3adca1ceee1f569aa6f5`, Git blob은 `4e5b89a1812e9173e0531243c874719fc9875e3b`이며 `inputs/saved_mr_causal_child_receipt.json`에 원 bytes를 보존했다. Receipt의 native module SHA가 현재 선택한 callback SHA와 일치한다. Ledger SHA는 `55f53ff96d88e63c4ce152499153b37a13a9e20a33735a4fc7e3db888c9264c8`이다. 원문 자체의 해석은 “chronological parameter OOS; strategy formation after inspected history; not genuine fresh”다.

Old 61T replay는 cached 5m 행 묶음 및 common-index 기반 30m에 next-open entry와 **같은 봉 close exit**를 적용했다. 기존 causal-control은 UTC 완료 봉·availability/segment·다음 open exit를 명시하는 별도 identity다. 따라서 이번 synthetic parity는 선택한 native callback의 signal/exit 결정 parity이며 61T 체결·PnL 재현을 주장하지 않는다.

## 현재 연결 범위와 owner 인계

순수 JSON API는 `prepare_signals(snapshot, enabled=False)` 및 `prepare_exit(snapshot, position, enabled=False)`다. 기본 OFF이며 enabled를 사용해도 collector, 계정 예약, paper/live 실행을 시작하지 않는다. 원문 signal은 origin snapshot으로 다시 확인하고, 기존 canonical opportunity key 및 caller의 `seen_opportunity_keys`를 사용해 같은 기회를 중복 producer에 배정하지 않는다.

기존 오래된 forward producer에도 이 MR native identity가 이미 등록되어 있고 상태는 `HOLD_FRESH_SOURCE_OR_IDENTITY`로 관측되었다. 이번 작업은 그 producer를 새로 등록하거나, B의 기존 PID/writer/state를 변경하는 작업이 아니다. 준비 output은 항상 `executable=false`, `real_sources_verified=false`, `fresh_T=0`, `fills=[]`, `PnL=null`, `shadow_active=false`를 유지한다.

Source rule의 첫 결손은 발견되지 않았다. **실제 미래 실행 가능 여부는 여전히 별도 gate**다: owner-approved boundary와 genuine observed 6-symbol source/clock/cursor, 외부 비용 사실, pair 자금 예약 및 양쪽 execution evidence가 필요하다. Caller-supplied evidence와 synthetic 시험의 통과가 이를 대신하지 않는다. A의 유일 owner/global-heavy 권한 아래에서만 다음 단계가 결정되며, 이 문서나 adapter가 경제 FULL/OOS/승격을 시작하지 않는다.
