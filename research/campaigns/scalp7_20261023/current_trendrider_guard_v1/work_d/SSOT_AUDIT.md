# CURRENT TrendRider SSOT / candidate-admission audit

2026-10-23. `upload/ZEL_D_DOWNLOAD(1).txt` 전체를 읽고 GitHub plugin의 읽기 기능으로 master 및 #566/#1334/#1358 최신 영수증을 확인했다. 저장된 새 current255/later256 JSON만 읽었다. 경제·native replay·시장 API·Actions 실행·원격 변경0. 기존 D historical256 및 K117 재시험0.

## 판정

**`CURRENT_TRENDRIDER_NO_CAUSAL_CHILD`가 현재 증거에 맞는다.** 지정 observer255를 보존하면서 같은 native identity의 더 늦은 유효256 영수증을 별도로 연결해야 한다. 두 코호트 모두 exact-run hardening 연결은 가능하지만, 원형 entry-time FeatureSnapshot 본문·OHLCV prefix·완성봉 가용시각은 새 archive에도 없다. 이 입력이 첫 실제 차단이다. 이 상태에서 추세/변동성/chase 조건을 과거 손익으로 재구성하거나 새 한 축을 만들어서는 안 된다.

이 결론은 old D256 종결을 복사한 것이 아니다. **새 run39918582893의5개 JSON과 run39930858426의9개 JSON을 직접 읽었고**, 각각 OHLC 객체0, FeatureSnapshot 본문0, observed/available/closed-at 계열 가용시각0임을 확인했다. hash만 존재하는 native feature를 역산하지 않았다. 현재 H4/H5 종결과 source proof를 검증하는 guard·반례시험은 독립적으로 완성할 수 있다.

## 현재 우선순위와 정확한 lane 분리

읽은 master: `dd59cdb4fa5d6347cb40f55c8e014ef790c0fe63` (2026-10-23T15:32:46Z). #1358 comment6368234497이 새 D latest255 작업을 명시하고, #1334 comment6348225710의 old256 종결·K117 동결을 보존한다. 후속 #566 comment6368541576(15:32:48Z)은 같은 long-only identity의 더 늦은 **새256** 실행이다.

| Lane | 정확한 코호트 / 저장 출처 | 상태 |
|---|---|---|
| 지정 A1 native observer | `trend_rider_delayed_fill_long_only_v1`, 12종목1h long, run39918582893, #566 comment6365872161(13:21:43Z); observer blob `73c369d85cf7d188be3eefc137acb1f97a6a8739`, signed `e64ced402223eab12d1d18624292769a2170a14b8514f5e2a2c6f3199249fbf4` |255T; Net1 +1184.9203927069432 trade-bps, Net/T +4.6467466380664435, PF1.0348880195428167, WR0.2196078431372549. H4 NO_PROVEN_EDGE/H5 HOLD.|
| 더 늦은 동일 native identity | run39930858426, #566 comment6368541576; `a1_trend_rider_long_only_exact_parent_latest.json` blob `74e7998e80e3a85854b31de65ef2314e719c6c76`, signed summary `e3d5c65319b0dff08718484a20cad05af54d12c5606a184a579879eeeaacb804` |256T; Net1 +1366.3469831938278, Net/T +5.33729290310089, PF1.0403441548290502, WR0.22265625; HOLD_HARDENING, survivor_ready=false. old D256과 다른 입력.|
| WR80/chase cooling | `trend_rider_wr80_us_chase_cooling_v1`; `a1_trend_rider_wr80_us_chase_cooling_forward_latest.json`; signed `1084034fb671d56a9d10677746e66b07bc79df928462dfd11bb063c831cf5578`; BTC/ETH, boundary2026-08-23T13:00:00Z |42T; Net1 −744.959679269319, PF0.7764960535922436, WR0.19047619047619047. 역사 이름WR80은 현재 승률이 아니다.|
| G5 Unified | `TREND_RIDER_UNIFIED_V1_CAUSAL_POLICY`; `research/g5/TOP5_G5A_PHASE1_STATUS_V1.json` blob `4ea2a275518ef728ee05985a9266cfedc0583c34`; state SHA `80fbdaffae4fe08b245883a44cfe44055669b52bc10f1dd32e7c2ab46cffaa8e` |fresh closed0/open0/signal32; boundary1789221600000, last scanned1792756800000; FRESH_SOURCE_ACTIVE_NO_CLOSED_T; integrity PENDING_EXPLICIT_FIELDS; formal_pass_authority=false.|

K117 `CLOSED_FROZEN`, D historical256 commit`3e6733762bfcdc0db299589d2dab462021f074b7`, K117/Squeeze capacity commit`aaa4ac30a3b53020d878b3fe3f6bbac1a2590a30`은 보존한다. 이들의 거래·비용·가용시각을 새 TrendRider 입력에 이식하지 않는다. 경제 owner는 `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`; D guard PASS는 경제실행·Shadow·승격 권한을 만들지 않는다.

## 지정255와 최신256의 exact-run 연결

두 코호트 모두 boundary `2026-08-22T09:55:34Z`, policy blob`5212f92a0b181e523c235dc546b64ea2852045e7`, transformed config`0770c62569a05e1a2caf6335f2554b9403453e8653a89565f2d9f4c90e49e50d`, cost authority`9a397e21412e2ab739f55953dc8fda6e4a66d8ac022d1de105876a2fb95debec`이다. 같다는 이유로 raw/hardening은 교환할 수 없다.

| 입력 | 지정255 | 최신256 |
|---|---|---|
| 실제 checkout (primary-source reviewer의 기존 job log 확인) |`bfcf40a34c73d3b98ac6256fac47997dc6f0f230`|`749bc9f771b8340c3bebc30bab10c3cbda6dd1ce`|
| run event head — checkout으로 대체 금지 |`ac9464f4baa21e7266c6c1ae0804544653102f0e`|`ba193d16807bd3f20a27ce25a0fc6d2fbe83b625`|
| `long_only_prospective.json` bytes SHA256 |`e35f3916525be25aff707cc45b37e010dfb27d08bb25c58dba896c9b9f0ab593`|`cdabca6842c76a4b4bd2ed5ac05f543094abd8175fb140fa62d3d79caf2d5c57`|
| fresh signed receipt |`00f4995935325317c2d50f5d6b17bd0cb549e0b1a66f3a24a8a9f5939b0a14a2`|`1b6fc24f41377bcef83f2935b7e113a4fc9fdc869ac337d60681b76fb18c6533`|
| `long_only_prospective_hardening.json` bytes SHA256 |`895fc1a21a48da780636bd4f0130400eed00f12aedbc9466011618844525f59f`|`133358c23861c872b2773bf83026438df073062dcc023c94b0b6588c1498324a`|
| hardening signed receipt |`5ef7885c0b7b82f3401f713a92244a125ad0c7aa8c83bd6902c5a20e4e6b83b0`|`c17d765708bb43acd9b7471736bce207084383642e2c8086ec46c13b8c729160`|
| hardening candidate receipt/count/boundary |위 fresh와 정확 일치/255/동일 boundary|위 fresh와 정확 일치/256/동일 boundary|
| 기록된1000봉 source 범위 |2026-09-11T22:00Z–2026-10-23T13:00Z|2026-09-12T00:00Z–2026-10-23T15:00Z|

master의 별도 `trend_rider_hardening_latest.json`은 **47T / boundary2026-08-16T18:45:01Z**이다. candidate`86c521f277af26820ba39d29bb7cc94b6b8728784cb139f18c7ca0b33b8a550d`, signed`434cc3b7eab39444d2d79eb587a7d7b31b05da3eb6a2e5a279d28298665da0d8`이며 현재255/256에 합치면 잘못된 검증이다. 관측 builder blob`97316511ce25e466c55a131768cab4fe3617620a`의 `extract_hardening()`은 상태를 읽을 뿐 candidate hash/count/boundary를 직접 검증하지 않는다. 따라서 새 guard에서 이 다른 코호트와255↔256 hardening 교환을 거부하는 것은 실제 무결성 문제를 해결한다.

## 255→256은 append-only forward 원장 증분이 아니다

저장 원장 두 개를 `(symbol, side, signal_ts)`로 비교했다. 공통249, 이전만6, 이후만7이다. 공통249의 전체 trade dict가 모두 달라졌으며 feature_sha190, intent_sha226, exit 가격61, realized_cost149, net_bps177이 달랐다. 공통행의 entry 가격·entry_ts·exit_ts는 모두 같다. 이 결과는 저장된 값 비교이고 native 재생이 아니다.

원천 rolling1000봉 시작이2시간 이동했다. 따라서 단순히255에서 새 거래1건이 추가됐다고 하거나, 두 summary Net 차이를 승리보존·새로운 forward 수익·개선 효과로 해석하면 안 된다. 잃은9월 fat-tail의 원인도 rolling window 누락/재계산과 실제 전략 회피를 분리해야 한다. 단일 rowcount 또는 strategy_id만으로 코호트를 고르는 guard는 불충분하다.

## H4/H5가 실제 말하는 것

같은 실행의 두 hardening 모두 H4 `NO_PROVEN_EDGE`, passed0/required5, `same_windows_costs_trade_budget_verified=false`이다. 공통 정책 source를 읽었으며 새 음성대조를 실행하지 않았다.

| Control |255 candidate−control net_R / p|256 candidate−control net_R / p|저장 판정|
|---|---:|---:|---|
|direction_inversion|116.6868554 /0.2043898|117.0632718 /0.2055397|둘 다CI_LOW_NOT_POSITIVE 및p 실패|
|indicator_removal|−361.5774616 /0.9997500|−477.5479263 /1.0|둘 다Net/expectancy/CI/p 실패|
|one_bar_delay|−14.1390686 /0.5974701|−15.2088975 /0.6000700|둘 다Net/expectancy/CI/p 실패|
|same_count_random_entry|−53.9625723 /0.7240638|7.3424839 /0.4672266|둘 다CI/p 실패;255는Net/expectancy도 실패|
|timestamp_shuffle|0 /1.0|0 /1.0|둘 다실패; 이long-only에서는항등 대조|

`timestamp_shuffle`라는 이름과 달리 실행 source는 side 배열을 섞어 같은 entry/exit를 평가한다. 모두long인 입력에서는 결과가 같고 delta0,p1인 것이 코드와 일치한다. 이것을 timestamp 무작위화 성공 또는 독립성 증명으로 쓰지 않는다. `same_count_random_entry`는 저장된 보유기간을 참조하는 사후 음성대조이며 runtime 진입정보가 아니다. `one_bar_delay`의 수익 우위도 승인된 새후보를 자동 생성하지 않는다. H4의 고정 정책 판정을 그대로 유지하고 이번 D에서 정책/임계값/음성대조를 고치거나 다시 경제계산하지 않는다.

같은 실행의 H5는 모두 `HOLD_CONCENTRATION_FRAGILITY`, blocker=`LEAVE_ONE_GROUP_OUT_NON_POSITIVE` 하나이다. top10 positive-net share는 255=0.45604049075088937, 256=0.4555959488450487이다. 이 수치가 0.5 미만이어도 H5 PASS가 아니다. 최신256에서 2026-09-17 entry-date group 제외 −85.83343204455376R, VOL_HIGH 제외 −33.124590637475144R 등은 원문이 이미 기록한 민감도이며 손실 필터나 account R가 아니다. long-only side 그룹 전부 제외0은 구조적 항목으로 별도 해석한다. 계좌 DD를 재생성하지 않는다. summary drawdown의 원본 순서는 별도 확인하고 saved-close/cohort 순으로 계산한 DD와 같은 이름으로 섞지 않는다.

WR80의 별도42T hardening도 H4 0/5 및 H5 LOGO·SINGLE_REGIME·TOP10 HOLD이다. 그것의 원문 receipt `81cea7b8eedc325eba764d9d4a8344abad8a14ad6ea3c12e6d0710d272598a7c`를 255/256 H4/H5로 대체하지 않는다. Unified G5 closed0은 이 A1 H4/H5의 다른 이름도, 현재 A1 원장의 실제 G5 closedT도 아니다.

## 새 한 축의 중복 검토

현재 pinned master에서 재조회한 prior evidence:

- BTC↔ETH peer trend-core: `a1_trend_rider_wr8125_peer_consensus_latest.json` blob `94327d5ba58261f21d8967d6cb0070a6d3042b77`, signed `ca47713e33884258e31abc213f530477e2bb0635d3b3d092ba06ee8546e9bf33`, `NO_STRICT_PEER_CONSENSUS_FUSION`, 추가7 중1승6패, formal_credit0. 이전 WR81.25 계보이며 current255/256의 새 축이 아니다.
- Structural US re-enable: blob `5b85b3fc0c84d557a28e4e6d9e5f9850385ce0f1`, `NO_STRICT_STRUCTURAL_CONSENSUS_FUSION`, 추가2 모두 손실. 역시 이름을 바꿔 재사용하지 않는다.
- current/prior completed-bar chase_atr 비교는 이미 WR80 chase 정책의 본체이고 42T 최신 음수가 있다.
- Transition-freshness 정책의 최신 router blob `27e0ef675940072b15957a66240e4e1d5d5d962d`, signed `b81f8582d3b7a0231c3e5305627c282830db04a6a6f8d5ac929d52a387a57302`: 44T, Net −1302.026412096113, PF0.6423878876, H4/H5 HOLD. state-transition를 새 축으로 주장하지 않는다.
- #566 comment6363066669/run39909551402: exact delayed-parent295에서 liquidity-regime169, multispeed67, relative-volume114, long-only255, short-only40을 이미 시험했다. 모든 ready=false, next=None. 해당 long-only255 Net/T5.9330489는 observer255의 4.6467466과 다르다. **같은255 수량도 같은 코호트 증거가 아니다.**
- #566의 갱신 comment5372877741/run39912215198: 별도 transition-repair203T, hard-control2 PASS지만 Net −25.3686324744, PF0.99835836, tier A1_REJECT, A2/A3 NOT_RUN. 이 control PASS를 current long-only의 H4 PASS로 전용할 수 없다.

이전에 완료된 momentum/multiscale/EMA-slope/sizing 결과를 이번에 다시 시험하지 않았다. 정책 main blob `5212f92a...`, delayed evaluator blob `82821e69159b685944f41ab43231cb98b92e8ed3`, long-only evaluator blob `f776611535c99a6abadc9de616f5ffdd0d06a6e4`는 current master에서 동일함을 읽기로 확인했다. 코드 존재만으로 원천 feature body 확보를 대신할 수 없다.

## guard에서 닫아야 하는 첫 문제와 인계

새 guard의 실질적인 역할은 (1) exact bytes+signed receipt+run/checkout/cohort를 결속하고, (2) 255/최신256/old256/WR80/Unified/47hardening의 잘못된 조합을 거부하며, (3) 원형 전행 및 실제로 계산한 비용2x/집중도/승리보존 진단을 보존하고, (4) source feature가 없는 상태에서 필터 생성을 거부하는 것이다. 대기 보고만 남길 필요가 없다.

현재 첫 입력 blocker: **원래 entry decision에서 사용한 per-trade native FeatureSnapshot 본문 및 그것을 재현하는 정확한12종목1h OHLCV prefix/seed와 closed-bar availability가 없다.** 기존 feature_sha·geometry·저장 P&L은 이를 복원하지 못한다. 추가로 delayed-period 실제 funding/fill/path 자료도 없으므로 회복승리/SL gap/MTM/NAV는 증명 불가다. 독립적으로 source를 확보하기 전 새 child수0, 경제효과 NOT_RUN/null, 현재 H4/H5 불변으로 인계한다. 현재 guard 검증 명령은 저장 증거 검증이며 A의 새 경제실행 명령이 아니다.
