# Supertrend Momentum 4h — H12 이후 추세 보유 준비

판정은 **CODE_PREPARATION_FROZEN / HOLD_SOURCE_FEATURE_NOT_BOUND**다. 실제 정책·반례시험·A 결과 비교 코드를 작성했지만, 경제 적격 후보는 0개다. 원본 OHLC와 실제 가용시각을 확보한 것처럼 표시하지 않는다. Stage1~3 및 `e1097b32faf54bf27935044f9226a32296621909` 결과는 재실행하지 않았다.

## 변경한 한 축

조건부 정책 identity는 `supertrend_momentum_h12_ema_persistence_intent_v1`, 부모는 `supertrend_replacement_highvol_mom_long_4h_h12_v2`다. 정책 사전 동결은 `FROZEN_RULE.json`에 있다. 기본 OFF이며 실전 실행·체결·포지션 해제 권한이 없다.

- 부모의 long 진입식, 7종목, native EMA20/50 계산을 유지한다. EMA는 일반적인 전체기간 EWM이 아니라 각각 최근 80/200봉의 첫 종가로 시작한다. 실제 의존 모듈의 경로·객체·SHA도 검증한다.
- 원래 보유 12봉(48시간) 전에는 EMA가 깨져도 조기청산하지 않는다. H12 이후 완료봉에서 EMA20>EMA50이면 연장 의도, 아니면 체결 증거가 필요한 청산 의도를 반환한다.
- H12 종가에서 계산한 EMA는 그 종가가 수신된 뒤 알 수 있다. 조건부 child는 시간청산을 보류하고 수신을 기다리므로, EMA가 깨진 경우에도 원래 종가보다 늦은 체결 비용이 생길 수 있다. 같은 종가나 같은 경계의 다음 시가를 소급 체결하지 않는다.
- 추가 만료·SL/TP·ATR 규칙은 만들지 않았다. 자료 종료 시 보유분은 censored이며, 유리한 가상 청산으로 닫지 않는다. 이전 추세 이탈이 미해결이면 재연장하지 않는다. 실제 실행 전에는 A의 유한 연구 범위·위험 계약·미결 처리가 필요하다.
- 원래 signal identity와 OPEN reservation을 결속한다. 보유 연장이 이후 진입을 막는 효과까지 A가 시간순으로 재생해야 한다. 기존 26개 거래에 child 결과만 덧붙여 합산하는 방식은 허용되지 않는다.

`OBSERVED_COHORT.json`에는 BCH·1000PEPE·BTC·ETH·HYPE·SOL의 기존 동일 진입 6행을 원문 그대로 보존했다. 손실 3행도 포함된다. LINK를 포함한 원래 7종목 universe는 그대로다. 이 파일은 관측 근거이며 정책 입력이 아니다. 승리 종목·월·MFE·미래 결과 필드는 정책에서 거부한다.

## 실제 복구와 첫 결손

원본 거래 snapshot SHA256은 `32ef0f850d546dea909094bebdf4e4df0d0b5980a66ec2db912859e7503e4d4d`, Git blob은 `70f5f6829d860a67f7df8e4ff1994965218c042c`다. 이것은 거래 요약의 해시이며 시장 OHLC 입력 해시가 아니다. 원문 계약·native wrapper·EMA 의존성도 정확한 bytes/hash로 결속했다. `SOURCE_MANIFEST.json`의 10개 Git 객체를 대조했다.

첫 결손은 `/home/z/g5_supertrend_immutable_original_4h_asof_receipt_20261023.json`의 원본 native 4h OHLC prefix·원본 raw SHA·실제 `available_at_ms`/`received_at_ms`다. 해당 경로가 없고, 확인한 원본 수집기는 raw 응답과 봉별 수신시각을 보존하지 않는다. 거래 요약의 `observed_at`을 과거 각 봉의 수신시각으로 바꾸지 않았다.

기존 인증 경로 `/home/z/z/runtime/economic7_campaign_20260915`의 manifest들과 실제 요청/응답 1건도 해시로 확인했다. 이 자료는 BCH·1000PEPE·HYPE가 없고, 1분 원본 및 15/30/60분 집계이며, 원본 4시간봉 관측 기간보다 먼저 끝난다. 9월에 과거 자료를 받은 시각은 그 과거 봉에서 거래할 수 있었던 시각이 아니다. 따라서 이번 원본과 별도 DEV 입력을 대신하지 못한다. 확인 범위와 실제 경로·해시는 `ARCHIVE_AUDIT.json`에 있다. 모든 가능한 아카이브가 없다는 주장은 아니다.

작업 초기 조회 master `a69d7fd3dd19fee0fb598f65312e8cc921f4acd7`의 수집기는 40건이나 Stage3의 고정 원본은 39건/검토 26건이다. 이를 최신 파일로 몰래 교체하지 않았다. 기존 26건은 새 OOS로 사용할 수 없다. 별도 DEV 계약 지원 코드는 있지만 실제 적격 DEV 구간·입력 SHA는 null이다.

## 검증과 정확한 실행 명령

새 시험 **36개 PASS**: 정책 21개, 비교기 12개, 인계 무결성 3개. 합성자료만 사용했고, 기존 6행은 bytes 보존 여부만 확인했다. 로그와 환경은 `TEST_LOG.txt`, `TEST_RECEIPT.json`에 있다. 새 시장자료 T·Net1/2·PF·DD·연패·승리 보존은 모두 null/NOT_RUN이다.

저장소 root에서:

```bash
python -B -m unittest discover -s research/campaigns/scalp7_20261023/supertrend_momentum_stage4_v1 -p 'test_*.py' -v
python -B research/campaigns/scalp7_20261023/supertrend_momentum_stage4_v1/policy_adapter.py
python -B research/campaigns/scalp7_20261023/supertrend_momentum_stage4_v1/handoff_gate.py --binding research/campaigns/scalp7_20261023/supertrend_momentum_stage4_v1/INPUT_BINDING.json --sha256 182f2e5107bd1132a56ddd99f3f00cab0cafb354a080df0a3fb3a745de0c84c8
```

첫 명령은 합성시험, 둘째는 `DISABLED`, 셋째는 저장 인계의 무결성 검사다. 셋째는 실제 실행하여 `HOLD_SOURCE_FEATURE_NOT_BOUND`, 종료 코드 2를 확인했다. `182f…84c8`은 **준비 인계 파일의 SHA**이며 존재하지 않는 시장 입력 SHA가 아니다. 경제 FULL 명령은 발급하지 않았다.

## A의 비교 연결

`comparison_report.compare(parent_rows, child_rows, manifest, unresolved_parent=..., unresolved_child=..., censored_parent=..., censored_child=...)`는 A가 만든 결과만 소비한다. 함수의 정확한 입력 schema는 모듈 docstring에 있다. 별도 수집기나 경제 engine은 만들지 않았다.

동일 원본 신호·진입시각, child의 H12 이전 청산 금지, 7종목·6종목 묶음, 입력 SHA·시간범위, 같은 종목 점유 중첩, 미결·검열, 단위 진입 notional을 검사한다. 새 진입·사라진 진입의 손익 변화도 분리한다. Net1/2·PF·동시 청산 묶음 DD·연패·순서 의존 거래 연패·일반/큰 승리의 실제 양수 유지 건수와 금액을 보고한다. 단순히 대응 거래가 존재하는 건수는 승리 보존 건수와 구분한다.

20/40bps는 원래 고정 비용 모델이며 실제 fee/funding/slippage가 아니다. 미측정 실제 비용·NAV·계좌 DD는 null이다. 미결이 있으면 HOLD, Net2 개선이 없으면 기각, 개선돼도 PF/DD/연패/큰 승리 훼손을 A가 검토해야 하며 자동 PASS하지 않는다.

연패·동시손실을 줄이는 두 번째 조건은 아직 선택하지 않았다. 첫 축의 실제 결과가 없으므로 서로 다른 축을 합치거나 경제 기각을 선언하지 않는다. 첫 축을 A가 해결한 뒤에만 다음 독립 기전을 결정한다.

A에는 이 **자료 결손이 명시된 준비물**만 인계한다. 경제 owner `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` / `910f998b1d60ddec30a76366ba49253a4afaa8dd`를 보존한다. FULL·Actions dispatch·시장 API·collector 시작·실주문·owner/원장/워크플로/master 변경은 0이다. 별도 메시지나 claim을 보내지 않았다. 배포는 필요하지 않으며, 이 게시 커밋만 정상 revert하면 추가 준비물을 제거할 수 있다.
