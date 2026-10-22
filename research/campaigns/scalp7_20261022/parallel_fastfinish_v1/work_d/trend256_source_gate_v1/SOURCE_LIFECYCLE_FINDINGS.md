# Trend Rider 256T source/feature/lifecycle 결속 검토

판정: **SOURCE_FEATURE_BLOCKED → NO_CAUSAL_CHILD**. 실행 정책 원본은 실제 run까지 연결했다. 그러나 256건 당시의 전체 OHLC prefix와 FeatureSnapshot 본문·가용시각이 저장되지 않아 prior BTC/ETH trend/volatility 또는 entry-chase를 전256건 의사결정 시각에 검산할 수 없다. 최종 손익·종목·월 또는 현재 재조회 시세로 그 빈칸을 대체하지 않는다.

## 실제 실행 provenance

- run `37989679810`, job `114020351819`, artifact `11646670634`.
- workflow는 `actions/checkout`에서 `ref: master`를 사용하지만, 실제 job log의 `2026-10-09T20:51:04.5923651Z git log -1 --format=%H` 다음 출력은 **`758fde9213032ef0211e5d8d3ffc914f6dad5ca2`**다. 따라서 단순 workflow run head 추정이 아닌 실제 checkout 증거로 아래 파일을 결속했다.
- artifact SHA256 `412e3f7456c53dd79869f7b6c9934fc3d3247d01250166cc165076e64fe3a819`, 로컬 ZIP 983,610bytes가 GitHub metadata digest와 일치한다.
- `long_only_prospective.json` 원문 바이트 SHA256: `686c5574c2554867b8cdb38fcb23f2de50fa9c3837dd9406d0be4a168b976fb9`.
- 그 파일의 내부 receipt SHA256: `4515dfa653d0ebf25029ee6b1eb0a9a54f81c8c4f65d3fbaecc30f9efc334c70`. 원문 바이트 SHA와 내부 canonical receipt SHA는 다른 식별자다.
- exact child=`trend_rider_delayed_fill_long_only_v1`, delayed parent=`trend_rider_one_bar_delayed_fill_v1`, strategy=`trend_rider`. delayed parent 301건의 long 부분집합 256건이며 Liquid6 123건과 합치지 않았다.
- job은 build 단계와 artifact 업로드를 완료했지만 prospective hardening 단계에서 `BINGX_API_ERROR:100410`으로 실패했다. 이 실패를 신규 실행으로 복구하거나 hardening PASS로 바꾸지 않았다.

## 실제 checkout 원본 해시

모든 경로는 `backend/research/rebuild/` 아래이며 아래 내용은 실제 checkout ref에서 fetch한 바이트다. Git blob SHA1은 `blob <bytes>\0 + content`로 로컬에서도 재검산했다.

| 파일 | Git blob SHA1 | 원문 SHA256 |
| --- | --- | --- |
| `trend_policy_batch_v1.py` | `5212f92a0b181e523c235dc546b64ea2852045e7` | `f58792c31d9b358894c6626ea8aa273aef3ba086366d023913003eeb8e576b1e` |
| `policy_kernel_v1.py` | `28875a0bfd16b07f3686f128cb2f6943f8364006` | `e6b21d2d3ae6a4e6af6a3c2039dcf8e8ebf4caa51d29a82a5285e4059c82759e` |
| `a1_exact25_generic_evaluator_v1.py` | `5da6ed21eab6d5482602bc1b856537f74f268a15` | `074ccb2a0bec3454e7900d86deb365b47c652dc5f024884124692496a4ffcf5d` |
| `a1_exact25_generic_evaluator_v2.py` | `b8fbf673287270925fb32536449d5f9ada352f10` | `e615f2a4300f671bd0af0dd9fc2c6fdefb5a5c8ff0b2f57901c33704bc965a5f` |
| `a1_exact25_policy_adapter_v1.py` | `8f41a6855be575b458df21df07fa1f22c038bade` | `0a8b817f1e301b5c79d05840805af42c4b5dfd03ced034e9751b9a70923869b3` |
| `a1_trend_rider_delayed_fill_evaluator_v1.py` | `82821e69159b685944f41ab43231cb98b92e8ed3` | `44a682e474ca73eb2b2fa5bb1860f40a2c332c36d42eb9590aba617848df62f8` |
| `a1_trend_rider_long_only_exact_parent_evaluator_v1.py` | `f776611535c99a6abadc9de616f5ffdd0d06a6e4` | `eed4e08d951d8a5c0720fe2a69a5edefa6bd0b270f9614f45e75f4b3e3327648` |
| `a1_rebuilt_bb_revert_cost_authority_v1.json` | `61bba3439dc7f41cabb73d8aa047b87cb0f7eb35` | `576107a30bb9c949f5fb6df296bc130e750dc7f74224402296fc4d09d138c90c` |

256건 모두의 `policy_sha`는 위 policy blob과 같다. `TrendPolicyConfig` 필드를 AST 상수만 읽어 canonical JSON으로 해시한 값 `ac462a17bf7c607cd0d3e97fa37bd33c5cc0672b7a81ecf37bd9e586d91fd2c4`도 256건의 config SHA와 일치한다. 코드를 import하거나 계산기를 실행하지 않았다. 비용 authority canonical SHA `9a397e21412e2ab739f55953dc8fda6e4a66d8ac022d1de105876a2fb95debec`도 저장 receipt와 일치한다.

## 당시 feature가 실제로 필요한 경로

`generic_v2.main → generic_v1.main → compute_trend_rider_feature → _snapshot → build_trend_rider_intent/_build`가 실제 신호 경로다. generic evaluator는 종목별 1h 최신 1,000봉을 받고, `bars[:i+1]` 전체 prefix를 compute에 준다. `compute_trend_rider_feature`는 ATR14, EMA50의 현재/이전값, Supertrend(10,3), 이전 봉 색, close와 trend/line의 관계를 계산한다. `st_gap_atr`, `chase_atr`, long/short confirmation은 FeatureSnapshot.values 안에 있다. 기존 원형 gate는 st_gap>=0.10와 chase<=2.0이며 이 수치를 이번에 새로 정하거나 조정하지 않았다.

`_snapshot`의 feature hash 입력은 `{strategy_id,symbol,signal_ts,close,atr,values}`다. 저장행에는 그 **해시만** 남는다. 256건 모두 feature_sha가 있고 실제 feature body가 있는 행은 **0건**이다. sealed intent geometry도 `symbol/side/signal_ts/sl/tp/timeout` 및 hashes까지만 저장한다. close·ATR·EMA50·Supertrend 값·prior trend·volatility·chase는 없다. 해시는 본문을 역산하는 자료가 아니다.

BTC/ETH 외 종목의 각 신호 시각에 결속할 BTC/ETH 공통 snapshot도 없다. 기존 policy는 한 종목 prefix만 입력받으므로 cross-asset 기준 상태를 암묵적으로 포함한 것으로 해석할 수 없다. BTC/ETH 본인 거래행의 feature_sha 역시 다른 시각/다른 종목의 공통 시장상태를 제공하지 않는다.

## 원시 입력 archive를 확인한 범위와 실제 결손

해당 run의 artifact 목록은 1개다. ZIP의 7개 파일을 전부 읽고 재귀적으로 OHLC 객체와 전체 FeatureSnapshot 객체를 점검했다:

`long_only_development.json`, `parent_development.json`, `long_only_prospective.json`, `long_only_development_hardening.json`, `parent_development.parent.json`, `parent_prospective.json`, `parent_prospective.parent.json`.

7개 파일 모두 OHLC 객체 **0개**, 전체 FeatureSnapshot 객체 **0개**다. workflow의 업로드 범위는 `out`이고, 살펴본 evaluator는 최종 receipt를 쓰지만 bars나 feature body를 별도 파일에 저장하지 않는다. source에는 endpoint/interval/개수/첫·끝 timestamp만 있다. original OHLC byte hash, 원시 bar archive 경로, 전체 prefix start/seed certificate는 없다. `generic_v1.sealed_intent_geometry`의 주석도 시간이 지난 최신1,000봉으로 EMA 신호를 재계산하면 동일하지 않을 수 있음을 명시한다.

이 결론은 **해당 run 전체 artifact·동결 receipt·실행 workflow·실제 dependency 경로에서 원본 archive 결속을 찾지 못했다**는 뜻이다. 저장소·VPS 전체 어디에도 시세가 없다고 단정하지 않는다. 다른 원본이 있더라도 이 run의 exact prefix/seed 및 256 feature_sha와 맞는다는 검증 없이 대체자료로 채택할 수 없다.

저장 source의 1,000봉 범위는 12종목 공통 `1787983200000`–`1791579600000`이다. 실제 256행의 signal timestamp는 `2026-08-31T22:00:00Z`–`2026-10-09T17:00:00Z`, delayed entry는 `2026-09-01T00:00:00Z`–`2026-10-09T19:00:00Z`다. 모든 entry는 저장 signal label보다 2h 뒤다. 이는 원형 next-bar open에 추가 1bar delay를 준 결과다. timestamp는 명시적인 feature available_ts가 아니므로 모든 signal을 그 label 순간에 이미 알았다고 처리하지 않는다.

## 실제 lifecycle과 이름만 있는 lifecycle의 구분

| 항목 | 실행 코드에서 확인한 실제 의미 | 감사/인계 한계 |
| --- | --- | --- |
| 신호·entry | generic parent는 신호 prefix 다음 봉 open, delayed transform은 한 봉 더 뒤 open | latest1,000봉을 parent·delay·long-only source rebase가 각각 재조회한다. 원시 바이트가 없어 호출 간 동일성을 증명할 수 없다. |
| 초기 stop | 신호 close ±1.5×ATR14로 재계산한 고정 stop | delayed entry로 넘어간 시점의 stop validity를 별도 재검사하지 않는다. 원래 sealed SL과 저장 SL 체결189건은 수치가 일치하지만 손실갭의 실제 경로는 없다. |
| stop/gap | delayed transform은 봉 low/high가 stop에 닿으면 **stop 가격**으로 종료 | gap-open adverse fill 분기가 없다. 따라서 gap/slippage 보호가 검증된 일반 엔진이라고 주장할 수 없다. 가격경로 없이 그 낙관성을 금액으로 환산하지 않는다. |
| target/timeout | `tp=None`, timeout48; stop이 없으면 선택된 마지막 봉 close | 256건 reason은 SL189/TIMEOUT67. TIMEOUT에 저장한 exit_ts는 해당 bar의 ts_ms label이다. 실제 close 가용시각과 별도 binding이 없다. |
| partial/trailing/runner | policy는 partial disabled, trailing/runner enabled 메타를 만든다. generic/delayed 실행 loop는 고정 SL/TP/timeout만 처리 | 큰 승리를 dynamic runner/partial이 보존했다고 표현할 근거가 없다. 여기서는 고정 stop과 시간 보유의 결과다. |
| 미결 | generic parent는 마지막 horizon에서 미결이면 open_intents에 보유권을 남긴다 | delayed는 last를 데이터 끝으로 자르고 close를 사용할 수 있다. 종결/자료끝을 정확히 구분한 새 평가에는 원본 prefix와 lifecycle 계약이 필요하다. |
| 점유·재진입 | 종목별 no-pyramiding과 기존 cooldown2bars; delayed의 연속 signal/side transition 중복 거부 | long-only는 이미 생성된 delayed parent의 long 부분집합만 고른다. short를 제거한 뒤 새로운 기회를 다시 재생하지 않는다. 차단 변경의 후속 기회를 저장256행에서 재구성할 수 없다. |
| risk size | policy config에는 risk0.005, exposure cap0.15와 위험거리 기반 notional 계산이 있다 | evaluator 손익은 trade-bps이며 actual quantity·account NAV를 가중하지 않는다. 이 값을 계좌성과 또는 새 배정 한도로 수입하지 않는다. |
| 비용 | 고정 authority의 taker양방향 fee + 당시 current depth spread/impact + parent 보유구간 funding 합계 | delayed transform은 parent의 realized_cost_bps를 그대로 복사한다. delayed 보유구간의 funding을 다시 계산하지 않는다. funding_rows는 receipt에서 제거되어 원래 settlement 전체도 재검산할 수 없다. 비용2x는 저장비용 스트레스일 뿐 실제 역사체결·펀딩 보장이 아니다. |

## 정확한 causal blocker

1. 당시 완성된 각 종목 원본 OHLC prefix 바이트와 seed 시작점의 검증 가능한 binding이 필요하다.
2. 256건 feature body 및 signal bar close/available timestamp, BTC/ETH 공통 snapshot의 as-of 조인 증거가 필요하다. 값이 있는 snapshot은 native `feature_sha`와 일치해야 한다.
3. 보유 중 개선축에는 실제 bar prefix·현재 stop·대기 exit·부분실현/잔량 상태와 terminal precedence가 필요하다. 저장 final entry/exit/SL/timeout만으로 MFE·회복 경로를 생성할 수 없다.
4. 그 전까지 source 없는 trend/vol/chase 임계치 child는 만들지 않는다. `NO_CAUSAL_CHILD`는 이 exact256 source 검증 결손에 대한 종결이며, 기존 raw ledger의 손익/집중도 경량분석을 막는 별도 자금배정 게이트가 아니다.

읽기 전용 GitHub fetch·artifact/JSON/소스 AST 검토만 수행했다. 시장 API 호출0, native import/replay0, 경제 FULL0, workflow dispatch0, 원격 runtime 변경0. 기존 parent·256T·123T 결과와 실패를 변경하지 않았다.
