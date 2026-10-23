# CURRENT TrendRider 원문·source/lifecycle audit

**판정: CURRENT_TRENDRIDER_SOURCE_FEATURE_BLOCKED → CURRENT_TRENDRIDER_NO_CAUSAL_CHILD.**

`upload/ZEL_D_DOWNLOAD(1).txt`를 전체 읽고, 지정 current255 5 JSON 및 later256 9 JSON의 원문과 두 실제 checkout의 실행 dependency 19종을 검토했다. 기존 D256/K117 경제·native replay와 과거 7반례를 재실행하지 않았다. 아래 결손은 현재 artifact에서 새로 확인한 결과다. H4/H5는 양쪽 모두 기존 **NO_PROVEN_EDGE / HOLD_CONCENTRATION_FRAGILITY**를 유지한다.

## 1. 첫 결손 입력

각 원래 신호의 `feature_sha`와 일치하는 **전체 FeatureSnapshot 본문** `{strategy_id,symbol,signal_ts,close,atr,values}`, 그 본문을 만든 **정확한 OHLC prefix/seed의 원본 바이트와 해시**, 그리고 **완성봉 available timestamp 증빙**이 없다. current255의 255행 모두 feature_sha가 있으나 full body는 0행이다. later256의 256행도 같다. 두 archive 전체 14 JSON의 OHLC 객체·full feature 객체·available timestamp·funding_rows는 모두 0개다.

첫 current255 행은 `1000PEPE-USDT`, signal_ts=`1789394400000`, feature_sha=`d6fcf77cb5f5a3c9bea44fc88f7e9efa1f9f29c543377669589270f0bf18f588`이다. 이 해시에 대응하는 close/ATR/values 원문이 첫 결손이며 해시나 SL로 이를 역산해 채우지 않는다. BTC/ETH prior trend·volatility·chase를 붙이려면 이외에도 **각 의사결정 시각 이전에 가용한 BTC/ETH snapshot 및 as-of 결속**이 필요하다. 기존 단일 종목 policy는 이를 암묵적으로 제공하지 않는다.

검토 범위는 지정 두 run archive, 실제 checkout source/workflow/contract다. 저장소/VPS 전체 어디에도 원시자료가 없다고 단정하지 않는다. 다른 자료가 발견되더라도 이 run의 prefix/seed 및 native feature_sha에 맞는 검증 없이는 대체할 수 없다. 새로운 시장 API로 최신1,000봉을 받는 것은 이 입력을 복구하는 행위가 아니다.

## 2. 현재 lineage를 과거 D256과 분리

| 항목 | 지정 current255 | later256 별도 관측 |
| --- | --- | --- |
| run / job | 39918582893 / 120299946055 | 39930858426 / 120338476850 |
| 실제 checkout (상위 담당자가 job log로 확정한 pin) | `bfcf40a34c73d3b98ac6256fac47997dc6f0f230` | `749bc9f771b8340c3bebc30bab10c3cbda6dd1ce` |
| ZIP SHA256 | `e5ea0c56919eb4d35e71a2b137d2e9d54a23bd52dc93dd5e913f7dc320e0710f` | `c66cad2ecdf1833a0ca0d2100b6fc10880c6041327dc27da1037393bead29e72` |
| ZIP bytes / JSON 수 | 479644 / 5 | 958133 / 9 |
| long-only 파일 SHA256 | `e35f3916525be25aff707cc45b37e010dfb27d08bb25c58dba896c9b9f0ab593` | `cdabca6842c76a4b4bd2ed5ac05f543094abd8175fb140fa62d3d79caf2d5c57` |
| 내부 native receipt SHA256 | `00f4995935325317c2d50f5d6b17bd0cb549e0b1a66f3a24a8a9f5939b0a14a2` | `1b6fc24f41377bcef83f2935b7e113a4fc9fdc869ac337d60681b76fb18c6533` |
| delayed parent 내부 receipt | `a1fef38f8a6fa62647346e07259a7c262d446a9b2f00e1f6d942070db5ba370e` | `0ff25e26e26abedf7ff458497874838082a5bcb7e81631885cf82502fb476fb6` |
| parent 완료 / long-only 완료 | 293 / 255 | 296 / 256 |
| signal UTC 범위 | 2026-09-14 14:00–2026-10-23 02:00 | 2026-09-14 16:00–2026-10-23 06:00 |
| entry UTC 범위 | 2026-09-14 16:00–2026-10-23 04:00 | 2026-09-14 18:00–2026-10-23 08:00 |
| SL / TIMEOUT | 193 / 62 | 194 / 62 |
| 저장 native Net trade-bps | 1184.9203927069432 | 1366.3469831938278 |
| 저장 native DD trade-bps | 19015.395694347524 | 19032.106869854862 |

공통 identity는 `trend_rider_delayed_fill_long_only_v1`; 원형 `trend_rider`, delayed parent `trend_rider_one_bar_delayed_fill_v1`, 1h 12종목, long-only boundary `2026-08-22T09:55:34Z`다. WR80 및 G5는 별개이며 합치지 않는다. 실제 workflow는 `ref: master`를 checkout하므로 run의 event head, audit 시작 master 또는 D branch HEAD를 실행 source로 대신 사용하지 않았다. 위 checkout에서 직접 GitHub read-only fetch한 모든 파일의 Git blob SHA를 로컬 재검산했다.

두 표본은 +1행 단순 append 관계가 아니다. 저장행을 `(symbol,signal_ts,side)`로 비교하면 공통249, current255에만6, later256에만7이다. 공통249 중 feature_sha190·sealed SL97·realized_cost149가 서로 다르다. 이는 새 평가를 실행한 결과가 아니라 다운로드된 두 receipt의 필드 대조다. 코드가 같아도 최신창 재조회 결과를 이전 표본의 봉인 source로 취급할 수 없다는 실측 근거다. 상세는 `SOURCE_LINEAGE_COMPARISON.json`에 남겼다.

## 3. 실제 checkout 원문 결속

`source/SOURCE_INDEX.json`은 source 경로·actual ref·URL·Git blob SHA·원문 SHA256·bytes·로컬 경로를 38건(19종×2ref) 보관한다. `source/current255/`와 `source/later256/` 19종의 원문은 **전부 byte-identical**하다. 계약 원문은 실제 `backend/research/contracts/` 경로에서 읽었다. 공개한 index의 `local_path`는 이 디렉터리 기준이며, `original_local_path`는 최초 수집 위치다.

| source basename | Git blob SHA1 (두 checkout 동일) | 역할 |
| --- | --- | --- |
| trend_policy_batch_v1.py | `5212f92a0b181e523c235dc546b64ea2852045e7` | original feature 및 intent |
| policy_kernel_v1.py | `28875a0bfd16b07f3686f128cb2f6943f8364006` | prefix EMA/ATR, risk geometry |
| a1_exact25_generic_evaluator_v1.py | `5da6ed21eab6d5482602bc1b856537f74f268a15` | 최초 parent, fetch, 비용, lifecycle |
| a1_exact25_generic_evaluator_v2.py | `b8fbf673287270925fb32536449d5f9ada352f10` | adapter 및 source quality gate |
| a1_exact25_policy_adapter_v1.py | `8f41a6855be575b458df21df07fa1f22c038bade` | native function dispatch |
| a1_trend_rider_delayed_fill_evaluator_v1.py | `82821e69159b685944f41ab43231cb98b92e8ed3` | delay, 재계산 stop, ownership |
| a1_trend_rider_long_only_exact_parent_evaluator_v1.py | `f776611535c99a6abadc9de616f5ffdd0d06a6e4` | long subset, source rebase |
| a1_trend_rider_exact_parent_repair_batch_v1.py | `7e33b17e97dcc68d636bda48e0ad808232973ddb` | long-only metrics, DD |
| a1_trend_rider_h4_h5_hardening_v1.py | `12ea0e5d5dfd954e3c97fbdccc174a4ccbfbb55a` | fresh bars/control/diagnostic groups |
| zel_economic_hardening_gate_v1.py | `3ef5950181836e0e044d46750b798479b3a0a201` | H4/H5 source receipt verifier |
| a1_trend_rider_prospective_observer_v1.py | `97316511ce25e466c55a131768cab4fe3617620a` | observer 상태 추출 |
| a1_rebuilt_bb_revert_cost_authority_v1.json | `61bba3439dc7f41cabb73d8aa047b87cb0f7eb35` | frozen cost authority |
| a1_trend_rider_long_only_exact_parent_v1.json | `d44b7fd17aa3298b6112f7a0217ffd23748fec5f` | long-only frozen contract |
| a1_trend_rider_delayed_fill_v1.json | `476e5f36abb6456c459f4b9ea87ee49968f3a830` | delayed frozen contract |

두 표본 모든 trade policy_sha는 policy blob `5212f92...`에 일치한다. row config_sha는 `ac462a17bf7c607cd0d3e97fa37bd33c5cc0672b7a81ecf37bd9e586d91fd2c4`이고 top-level delayed wrapper config_sha는 `0770c62569a05e1a2caf6335f2554b9403453e8653a89565f2d9f4c90e49e50d`다. 두 층을 같은 해시라고 취급하지 않는다. 비용 authority canonical SHA는 `9a397e21412e2ab739f55953dc8fda6e4a66d8ac022d1de105876a2fb95debec`다.

정책·kernel·generic v1/v2·adapter·delayed·long-only·repair metrics·cost authority는 과거 D256에 저장해 둔 원문과도 byte-identical이다. 따라서 동일 코드 경로의 결손이 현재에도 있다는 정적 증거는 있다. 과거 D256의 7개 counterexample와 48tests를 이번에 새로 돌린 실적으로 표기하지 않는다.

## 4. original policy, fields, availability

실제 경로는 `generic_v2.main → generic_v1.main → policy adapter → compute_trend_rider_feature → _snapshot → build_trend_rider_intent/_build`다. 원문 위치는 아래 `source/current255/` 기준이며 later256도 동일하다.

- `trend_policy_batch_v1.py:117,166,187`: full prefix에서 ATR14, EMA50, Supertrend(10,3), prior candle 색을 계산한다. native values는 `supertrend,direction,ema50,long_confirm,short_confirm,st_gap_atr,chase_atr`다. 이미 존재하는 st_gap>=0.10, chase<=2.0 gate를 유지하며 새 임계치를 채택하지 않았다.
- `_snapshot`의 해시 본문은 strategy/symbol/signal_ts/close/atr/values다. fresh는 `now_ts-signal_ts`로 정하며 별도의 close/available timestamp가 아니다. `generic_v1.py:327`은 `now_ts_ms=bars[i].ts_ms`로 호출한다.
- `policy_kernel_v1.py:89,117`: EMA/ATR는 prefix 시작/seed에 의존한다. `generic_v1.py:181`의 sealed-geometry 주석도 rolling latest1,000 창이 이동하면 EMA를 재계산한 신호가 달라질 수 있음을 명시한다.
- 실제 trade 필드는 `symbol,side,signal_ts,parent_entry_ts,entry_ts,exit_ts,entry,exit,reason,gross_bps,realized_cost_bps,net_bps,entry_delay_bars,intent_sha,parent_intent_sha,feature_sha,config_sha,policy_sha,cost_snapshot_sha,intent_geometry`다. geometry는 원 intent의 SL/TP/timeout 및 hashes를 제공하지만 feature body·risk size·intrabar path는 제공하지 않는다.
- source는 endpoint/interval/count/first/last만 저장한다. 원 OHLC hash나 prefix seed certificate가 없다. `generic_v2.source_quality_gate`는 count/recency를 검사하며 exact OHLC identity나 각 feature available_ts를 검증하지 않는다. 저장 PASS가 이것까지 증명하는 것은 아니다.
- 모든 현재 long-only entry label은 signal label +7,200,000ms다(원형 next-bar open+추가1bar). 따라서 1h 봉 open label을 실제 close-availability와 동일시하면 안 된다. exit의 SL/timeout timestamp도 bar label이며 결과 가용시각이 별도 기록되지 않는다.

## 5. lifecycle와 funding sourcebody의 실제 한계

| 항목 | 실행 원문 및 현재 artifact로 확인한 내용 | 허용되는 해석 |
| --- | --- | --- |
| parent → delayed → long-only | generic parent가 native signal을 만들고 delayed가 다시 bars를 fetch한다(`delayed.py:114`). long-only prospective는 다시 fetch한 count로 source를 rebase한다(`long_only.py:90`). | parent 가격/feature·delayed stop·rebased source metadata가 동일 원본 바이트였다는 보장은 없다. |
| stop | delayed는 original parent entry index−1의 close±1.5ATR를 fresh bars에서 재계산하고 이전 trade/geometry를 복사한다(`delayed.py:136–169`). | sealed geometry를 직접 실행 stop으로 읽는 경로가 아니다. |
| 실제 stop 불일치 | current255 SL193행 중 183행만 exit==sealed SL. ETH signal1789401600000의 sealed SL=2501.827659768126, exit=2501.8685565198675. later256은 SL194행 모두 일치. | 현재 artifact의 실측 차이이며 새 replay가 아니다. 원시자료가 없으므로 원인별 귀속·손익수선은 하지 않는다. |
| stop/gap/precedence | low/high가 stop에 닿으면 stop가격 체결. adverse gap-open branch가 없고 generic은 stop을 TP보다 먼저 검사한다. | gap을 정확히 모델링한 결과나 MFE/회복경로 증거가 아니다. |
| timeout/open | generic data-end 미결은 open_intents와 ownership을 남긴다. delayed는 last=min(data-end, delayed entry+48), stop 미도달이면 last close를 사용한다. | 데이터 끝의 강제 close와 진짜 full48bar timeout을 원본없이 새로 판정할 수 없다. long-only의 inherited open_intents도 새 long-only 전체 replay의 미결집합으로 보장되지 않는다. |
| partial/trailing/runner | policy는 partial=false, trailing/runner=true metadata를 만든다. generic/delayed loop는 고정 stop/TP/timeout만 처리한다. | 저장 winner tail을 실제 dynamic runner/partial 최적화 성과라고 주장하지 않는다. |
| ownership | 종목별 no-pyramiding, cooldown2bars, delayed transition consumption. long-only는 기존 delayed parent의 long 부분집합이다. | short 제거나 추가 차단 뒤 새로 열릴 기회를 기존 closed subset만으로 재생할 수 없다. |
| risk/account | policy risk0.005·cap0.15는 intent geometry 계산 metadata다. evaluator는 quantity/NAV 가중 없이 trade-bps를 합친다. | 계좌 수익률·계좌DD·실제 위험배정 한도로 읽지 않는다. |
| funding body | `generic_v1.py:97–137`에서 latest funding100rows를 받아 entry_ts < settlement_ts <= exit_ts의 절대율을 합산. snapshot_sha는 funding_rows 포함 본문에 생성되나 `:431` 출력에서 funding_rows 제거. | 저장 p95나 scalar cost만으로 snapshot 해시/실제 settlement를 재검산할 수 없다. |
| delayed funding | `delayed.py:156`은 parent realized_cost_bps를 그대로 사용한다. exit/entry가 달라도 funding window를 재계산하지 않는다. | stored-cost2x 스트레스와 exact delayed historical funding 검증은 별개다. |

## 6. H4/H5 링크와 R 의미

| 확인 | current255 | later256 |
| --- | --- | --- |
| top hardening receipt SHA | `5ef7885c0b7b82f3401f713a92244a125ad0c7aa8c83bd6902c5a20e4e6b83b0` | `c17d765708bb43acd9b7471736bce207084383642e2c8086ec46c13b8c729160` |
| top candidate_receipt_sha256 | native `00f499...`와 정확히 일치 | native `1b6fc2...`와 정확히 일치 |
| H4 candidate_source_receipt_sha256 | `7a5c7c099d475cf2a309d03a8be5e3e330550762f7a8dd87bc3548e47c2b4b14` | `e9e92b2cd20224892a3d34c693761e3cacf29f0de9abdfae59f176d5e632ef48` |
| H4/H5 상태 | NO_PROVEN_EDGE / HOLD_CONCENTRATION_FRAGILITY | NO_PROVEN_EDGE / HOLD_CONCENTRATION_FRAGILITY |

상단 native 링크와 H4 내부 링크가 다른 것은 그 자체로 mismatch가 아니다. `hardening.py:22–40,109–110`은 native net_bps를 **100으로 나눈 벡터**에서 `zel.deterministic_replay.result.v1` candidate summary를 새로 만든다. H4 verifier `zel_economic_hardening_gate_v1.py:436–536`는 그 embedded summary의 receipt SHA를 검증하고 H4에 해당 SHA를 남긴다. 상단 hardening `:192`는 native receipt SHA를 별도로 남긴다.

여기서 `net_R`는 **고정 100 trade-bps 단위**다. 종목별 initial stop-risk로 나눈 R이나 account risk-normalized return이 아니다. H5 각 dimension의 net_R 합계는 current255=11.84920392706944 부근, later256=13.66346983193825 부근으로 각 native trade-bps/100에 수치상 맞는다.

저장 artifact에는 normalized candidate v1 본문, control receipt v1 본문/벡터 및 `data_sha`를 만들었던 fresh-bar material 원문이 없다. H4 출력에는 source receipt 해시와 통계 요약만 남는다. 따라서 top native 링크는 확인했지만 그 내부 input들을 exact source에 결속해 다시 증명했다는 주장은 하지 않는다. H4 control_engine_pass=true는 receipt 검증 경로가 실행됐다는 뜻이며 superiority를 뜻하지 않는다. current255는 passed_control_count=0, same_windows_costs_trade_budget_verified=false다.

## 7. hardening 코드의 causal 해석 제한

- **VOL_HIGH/LOW는 future slice로 계산된다는 증거가 없다.** `hardening.py:158–159`는 각 trade.signal_ts의 index까지 `bars[:i+1]`의 ATR14/ATR50을 비교한다. 동일 방식이 `repair_batch._regime:87`에 있다. 다만 bars는 hardening 시점의 새 latest1,000 fetch이고 원래 feature_sha/available_ts에 결속되지 않았다. 저장물에는 행별 regime label/ATR원문도 없으며 최종 그룹집계만 있다. 이 label은 H5 집중도 진단용이고 native entry gate가 아니다. H5의 그룹 이익·leave-one-out 값은 결과가 나온 뒤의 성과진단이다. 이를 사전 인과 filter로 승격하지 않는다.
- **timestamp_shuffle 이름과 실제 구현이 다르다.** `hardening.py:113–115`는 timestamps가 아니라 sides배열을 섞고 원 entry/exit/cost를 사용한다. all-long current255에서는 동일 벡터가 되어 실제 receipt도 delta=0, CI=0, p=1이다. 새 time-permutation 음성대조를 실행한 것으로 설명하지 않는다.
- **one_bar_delay control의 frozen geometry 주석과 실제 읽는 값이 다르다.** `:81–90`은 sealed intent_geometry.sl을 사용하지 않고 candidate entry_i−1에서 ATR stop을 재계산한다. 이미 delayed된 long-only candidate에서는 이 위치가 원래 signal_i보다 한 봉 뒤다. control은 기존 scalar cost를 복사하며 gap branch도 없다. 이번 audit에서 control 재실행이나 gate 수정은 하지 않았다.
- same-count random-entry는 실제 trade의 entry/exit로 duration을 정하고 hindsight window에서 draw한다(`:124–130`). indicator-removal도 fresh bars와 대응 index의 candidate cost를 사용한다. 이는 지정된 기존 placebo 구현의 의미이며 새 causal strategy나 입증된 superiority가 아니다.
- retention 정의는 boundary+24h 이후 완료 trade 수 / 현재 전체 trade 수(`:182–193`)다. 현재 rolling window가 9월부터 시작하므로 표본에서의 100%가 과거 전체 winner 보존이나 새로운 child retention을 보장하지 않는다.
- observer `extract_hardening/build:69–100`는 입력 hardening의 candidate_receipt_sha256를 fresh receipt와 대조하지 않고 H4/H5 상태를 추출한다. 이번 두 실물 파일은 별도로 대조하여 top 링크가 맞음을 확인했다. observer PASS 문자열 `PASS_H4_PLACEBO_NEGATIVE_CONTROLS`와 producer `PASS_PLACEBO_NEGATIVE_CONTROLS`도 다르다. 현재 실제 상태는 NO_PROVEN_EDGE여서 이번 결론에는 영향 없으며 원본을 고치지 않았다.

## 8. native DD 정렬 의미

native `metrics.drawdown_bps`는 **exit시각 정렬 trade-close DD가 아니다**. `delayed.enforce_policy_execution:110`이 `(entry_ts,symbol)`로 accepted를 정렬한다. long-only transform은 그 순서를 보존하며 `repair_batch.metrics:55–79`가 입력순서 그대로 net_bps를 `generic_v1.max_drawdown`에 넣는다. current255와 later256 실제 배열은 entry순으로 정렬돼 있고 exit순으로는 정렬돼 있지 않다.

따라서 저장값19015.395694/19032.106870은 **native entry-order 누적 trade-PnL DD**로 표기한다. 별도 exit-order 진단은 별도 이름과 tie 처리 규칙을 가져야 하며 native 값을 덮어쓰지 않는다. exit label만으로 intrabar path/NAV/mark-to-market DD를 만들 수 없다. 이번 source audit은 새 DD 경제평가를 실행하지 않았다.

## 9. 신규 archive 전체 목록과 재조회 근거

current255: `a1_trend_rider_prospective_observer_v1.json`, `delayed_prospective.json`, `delayed_prospective.parent.json`, `long_only_prospective.json`, `long_only_prospective_hardening.json`.

later256: `long_only_development.json`, `long_only_development_hardening.json`, `long_only_prospective.json`, `long_only_prospective_hardening.json`, `long_only_summary.json`, `parent_development.json`, `parent_development.parent.json`, `parent_prospective.json`, `parent_prospective.parent.json`.

`SOURCE_ARTIFACT_INVENTORY.json`에 14개 파일 각각의 byte SHA256·내부 receipt SHA·size·fields·full-body 존재검사·signal/entry 범위와 정렬 여부를 저장했다. 14개 내부 receipt SHA 모두 원문 JSON의 canonical 본문(자신의 receipt_sha256 제외)을 해시한 값과 일치했다. source bytes는 Git blob 해시 검증 후 저장했고 두 ref의19개파일을 byte comparison했다.

## 10. 원문 → 새 D guard → 실제 시험 이름

다음 시험은 새 work_d의 `test_guard.py`에 실제 존재하는 `CurrentReceiptGuardTests` 메서드다. source audit 담당자는 해당 코드를 읽어 mapping했으며 시험 실행·최종 통과 수는 상위 담당자의 새 D 검증 기록을 따른다. 과거 D256 시험 통과를 대신 기입하지 않는다.

| raw source가 드러낸 계약/반례 | 새 D 보호 함수 | test_guard.py의 exact test method |
| --- | --- | --- |
| hardening.py:192 top native link와 observer.py:69–100의 link 미검증 | receipt_guard.validate_bundle | test_later256_hardening_cannot_attach_to_current255_even_same_strategy; test_unrelated47_hardening_same_strategy_name_is_rejected; test_original_observer_accepts_one_forged_pass_mixture_new_guard_rejects |
| long_only.transform의 frozen boundary / parent subset | receipt_guard.validate_bundle | test_development_record_cannot_be_relabelled_fresh; test_hardening_boundary_mismatch_survives_self_rehash_but_is_rejected; test_different_true_parent_cannot_be_substituted |
| artifact 원문 byte pin과 내부 canonical receipt는 별도 검증층 | receipt_guard.load_pinned_bundle; verified_receipt | test_stale_self_hash_is_rejected; test_self_rehashed_raw_tamper_fails_archive_and_member_pins |
| generic_v1.py:414,418,431 cost scalar 및 snapshot/authority join | receipt_guard.validate_bundle | test_hardening_cost_authority_mismatch_is_rejected; test_trade_cost_snapshot_mismatch_is_rejected; test_malformed_trade_economics_and_time_are_rejected |
| trend_policy._snapshot hash 본문과 generic_v1 출력의 body 누락 | receipt_guard.validate_bundle source_feature_gate | test_feature_digests_do_not_substitute_for_entry_time_feature_bodies; test_true_archived_cohorts_validate_separately_without_child_or_authority |
| 서로 다른 TrendRider 이름은 lane/실행 권한 증거가 아님 | receipt_guard.blocked_authority; validate_bundle | test_wr80_and_unified_zero_are_separate_lanes; test_economic_authority_cannot_be_opened_by_valid_self_hash |

stop geometry 10건 차이, historical funding body, completed-bar availability 및 native DD 순서는 위 시험이 수선하거나 인증한 영역이 아니다. guard의 `stored_SL_exit_not_equal_sealed_SL_count`는 저장값 diagnostic이고, `SL_geometry_qualification`은 raw-bar causal proof 부재를 명시한다. `attribution.build_attribution`의 `native_drawdown_basis`도 original entry-order 의미를 별도 기록한다. 이 report의 source audit와 새 guard는 raw input 없는 lifecycle을 PASS로 바꾸지 않는다.

**수행 범위:** 기존 artifact의 JSON/해시/field 정합성 및 원문 정적검토, GitHub read-only source fetch. 시장 API0, native import0, native replay0, 경제 FULL0, H4/H5재실행0, Actions dispatch0, remote/runtime/owner/STARTED 변경0. 과거 D256/K117 결과를 현재 표본 성적으로 재사용하지 않았다. Source 결손이 해소되기 전 새 causal threshold/child를 만들지 않는다.

