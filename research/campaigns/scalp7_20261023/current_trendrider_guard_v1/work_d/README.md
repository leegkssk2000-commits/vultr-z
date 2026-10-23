# Work D — current TrendRider receipt guard

**Terminal: `CURRENT_TRENDRIDER_NO_CAUSAL_CHILD`.** 지정255와 이후 새256의 원문·저장 거래·동일 실행 hardening을 결속하는 오프라인 코드와 반례시험을 완성했다. 신규 전략 child는0이다. 첫 차단은 원래 signal의 `feature_sha`에 맞는 full FeatureSnapshot, 정확한 OHLC prefix/seed, completed-bar availability의 부재다. 손익이나 SL에서 feature를 역산하지 않았다.

이 디렉터리만 기존 D 브랜치에 추가한다. K117 CLOSED_FROZEN, historical D256 `3e6733762bfcdc0db299589d2dab462021f074b7`, capacity `aaa4ac30a3b53020d878b3fe3f6bbac1a2590a30` 및 이전 A/B/C/D 완료물은 보존한다. 과거 집계/48tests/native replay는 반복하지 않았다. 경제 FULL·경제 guard·Actions dispatch·시장 API·주문·owner/STARTED/관측기 변경0이다.

## 정확한 입력

| 별도 코호트 | 실행 / artifact | 실제 source checkout | native receipt |
| --- | --- | --- | --- |
| 지정255 | 39918582893 / 12505110231 | `bfcf40a34c73d3b98ac6256fac47997dc6f0f230` | `00f4995935325317c2d50f5d6b17bd0cb549e0b1a66f3a24a8a9f5939b0a14a2` |
| 이후 새256 | 39930858426 / 12513095636 | `749bc9f771b8340c3bebc30bab10c3cbda6dd1ce` | `1b6fc24f41377bcef83f2935b7e113a4fc9fdc869ac337d60681b76fb18c6533` |

`PINNED_INPUTS.json`에 원 ZIP·모든 member·native receipt·boundary·source metadata·policy/config/cost 해시가 고정돼 있다. 두 표본의 child boundary는 `2026-08-22T09:55:34Z`, delayed/native parent boundary는 `2026-08-21T11:15:00Z`다. actual checkout은 job 로그를 재조회했으며 event head와 다르다. 별도 WR80 42T, G5 Unified closed0, 다른47T hardening은 독립 입력으로 남기고 현재 원장에 합치지 않는다.

## 실제 저장 거래 진단

금액 단위는 **개별 거래 bps의 합**이다. 계좌 수익률/NAV/DD나 실제 브로커 체결실적이 아니다. Decimal은 원문 숫자의 문자열 값을 사용하므로 native float 합계와 약1e-11 수준 차이가 난다.

| 지표 | 지정255 | 이후 새256 |
| --- | ---: | ---: |
| Net1x | +1184.920393 | +1366.346983 |
| Net2x | −3464.501983 | −3120.469622 |
| Net1x/T | +4.646747 | +5.337293 |
| PF1x / PF2x | 1.034888 / 0.907419 | 1.040344 / 0.916149 |
| WR1x / WR2x | 21.9608% / 21.5686% | 22.2656% / 21.8750% |
| native 진입순 DD1x | 19015.395694 | 19032.106870 |
| 종료봉 동시집단 DD1x | 18735.026432 | 18751.748036 |
| 종료봉 개별 tie-break 최대 연패 | 40 | 40 |
| 종료봉 집단 최대 연속 음수 | 24 | 24 |
| 9월 진입 T / Net1x | 114 / +13686.436584 | 113 / +13935.299483 |
| 10월 진입 T / Net1x | 141 / −12501.516192 | 143 / −12568.952500 |
| 최대 승자1건 제외 후 Net1x | −2154.665676 | −1973.239086 |
| closed-row label 최대 동시 점유 | 12 | 12 |

2x는 `gross − 2 × saved realized_cost`이며 기존 funding 포함 scalar에 한 번만 추가 비용을 부과한다. funding settlement 원문이 없어 수수료·펀딩의 정확한 시간별 재검증/재평가는 null이다. 9월 이익의 대부분을 10월 손실이 소진했고, 최대 승자만 제외해도 음수다. 전체 row와 baseline winner identity, symbol/session/day LOOG, top1/3/5/10 drop, 10월 손실집단, exit순·동시집단 DD, 점유 timeline을 `results/OUTPUT.zip`의 `RESULT.json`에 보존했다. 이 사후 집단들은 실행 필터가 아니다.

점유는 `[entry_ts,exit_ts)`로 같은 시각 exit를 먼저 처리한다. 지정255의21건, 새256의20건은 label span0이다. 실제 intrabar 점유0을 뜻하지 않는다. 미결 parent intent·자본제약은 이 closed-row 진단에 포함되지 않는다. 가장 나쁜 동시집단은10건의 최종 손익 합으로 지정255 −2583.077620, 새256 −2575.165108이다. 그 시점의 MTM이나 가용한 정보로 해석하지 않는다.

255→새256은 **공통249 / 제거6 / 신규7**이고 모든 공통행의 저장 dict가 달라졌다. 공통행 Net1 변화 +180.134836은 gross +0.554994와 stored cost −179.579842에서 나온다. 전체 Net1 변화 +181.426590을 신규1건의 수익·알파 개선으로 볼 수 없다. 지정255의9월 진입 승자34건은 새256에도 모두 승자로 남았으며11건은 순이익이 낮아졌다. 대승/일반승의 동결 정의, MFE/MAE·회복경로는 입력에 없어 null이다. 임의로 top10을 대승의 사전 정의로 바꾸지 않는다.

과거 published top10은 재계산하지 않고 이미 저장된 identity 목록과 원행만 참조한다. 현재 두 표본에8건이 대응한다. 누락된 rank3 ETHFI와 rank7 LINK는 현재 visible source window 이전이다. 당시 최대 BCH 승자는 현재에도 남는다. 이는 범위 밖 부재와 결과 대조이며, 전략이 그 승자를 회피했다는 인과 증거가 아니다. 자세한 source pin과10건 대조는 `results/HISTORICAL_WINNER_REFERENCE.json`이다.

## 코드와 반례

`receipt_guard.py`는 raw ZIP/member/canonical 해시, 정확한 부모 subset, original→delayed intent·source·cost 연결, row 산술, hardening receipt/count/boundary/config/cost/window, 같은 archive summary를 검증한다. PASS의 범위는 저장 bytes 및 구조적 연결이다. current255의 SL193건 중10건은 sealed SL과 저장 exit가 다르다는 진단을 그대로 남긴다. 원시가격 없이 가격/비용을 수선하지 않는다.

`test_guard.py`는255↔256·47T·WR80·Unified 혼합, 재봉인된 잘못된 부모/경계/비용/산술, raw pin 변조, feature digest의 한계를 시험한다. 정확한 원문 observer의 순수 함수5개를 AST로 추출한 새 반례는 **합성 PASS가 붙은 다른 코호트 hardening을 기존 builder가 받아들이는 현상**과 새 코드의 거부를 재현한다. 실제 두 H4/H5가 PASS였다는 주장은 아니다. native module/main/시장 재생은 실행하지 않는다.

`attribution.py`는 저장 손익/시간만 계산한다. tie 순서·비용2배·point span0·중복 proxy·재계산 snapshot delta·winner 보존의 반례를 `test_attribution.py`로 검증한다. `historical_winner_reference.py`는 published top10 참조만 대조하며 과거 전체 표본을 재평가하지 않는다. 원문→코드→시험 mapping은 `SOURCE_AUDIT.md`, 독립 검토는 `REVIEW.md`에 있다.

동일 실행 H4는 양쪽 모두 `NO_PROVEN_EDGE`,0/5, same_windows_costs_trade_budget_verified=false다. H5는 `HOLD_CONCENTRATION_FRAGILITY / LEAVE_ONE_GROUP_OUT_NON_POSITIVE`다. H4 내부 R는 net-bps/100이며 risk R가 아니다. 내부 control vectors/source bodies는 미보관이다. 현재 판정·원본 정책·비용·검사·기대 해시는 그대로 보존했다.

## A의 정확한 검증 명령

A owner는 `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`이다. 이 인계는 저장자료 검증이며 경제 실행/승격/추가 claim 권한이 아니다. 게시 후 #1358 인계 comment에 commit SHA와 다음 명령을 확정해서 남긴다. 저장소 checkout에서:

```bash
D_DIR=research/campaigns/scalp7_20261023/current_trendrider_guard_v1/work_d
PYTHONDONTWRITEBYTECODE=1 python -B "$D_DIR/run_verification.py" --out /tmp/work_d_current_trendrider_verify
```

출력 디렉터리는 새 경로여야 한다. 실행 시 isolated 현재 시험, pinned 두 archive의 JSON 집계, published top10 대조와 합성 observer 반례만 수행한다. 입력 원문 또는 expected hashes가 다르면 거부한다. `RUN_RECEIPT.json`은 정확한 명령·환경·source/input/output SHA·시험 수·금지작업0을 기록한다. `RESULT.json`의 예상 SHA256은 `a691d8cc1ed0a87a3d7c82f932f47c35d4803969609e14ab6e310ec8dda66caa`다.

GitHub master/issue/owner/active/queued를 읽은 시점과 최신 동일 입력 재조회는 `SSOT_AT_ENTRY.json`, `SSOT_RECHECK.json`에 보존한다. 공개 범위는 이 새 D 경로의 파일 추가뿐이다.
