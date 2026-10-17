# ZEL 공개 벤치마킹 — 2026-10-17 16:21 CEST

상태: RESEARCH_ONLY / 경제실험 0 / 유료 API 0 / 기존 경제 단일 owner·원형·claim·workflow·주문 불변.

## 재개·중복 판정
GitHub 연구 브랜치 `research/parallel-benchmark-20261017`의 `RESEARCH.md`(blob `4453106d4dee89e0eb2a9e3808d459b51df6665d`), `BENCHMARK_20261017_1222_CEST.md`(blob `77a2afcd6beb0b1d9a52e4ce5ebf824370235e35`), `BENCHMARK_20261017_1320_CEST.md`(blob `4bd96ffea919aadee64a66f53bc12bb1b7208a08`)를 먼저 읽었다. 14:18/15:20 로컬 조사도 대조했으며 Mark/Last/Index, Guaranteed SL, 펀딩, AutoBE, trailing, slippage-limit 내용을 새 발견으로 반복 등록하지 않았다. 확인 코드: `scalp7_positive_lanes_v2.py` blob `79b9934b471cbe0f4342b265c90b2c9c8884f52c`, `scalp7_source_data_v2.py` blob `9e793d943a079e477772565f05b8fa456b97ef6e`; 확인 commit `c9ad2bdee6c607660a05494fad9acdf4e2351ad2`.

## P08: BingX Kline 가격계열 구분을 공식 API 표로 확인
**SOURCE_FACT**: BingX의 2025-10-16 API 공지(https://bingx.com/en/support/articles/31103871611289, 본문 2025-10-14 업데이트)는 `/openApi/swap/v3/quote/klines`를 Candlestick Chart Data, `/openApi/swap/v1/market/markPriceKlines`를 Mark Price in Candlestick Chart, `/openApi/swap/v2/quote/premiumIndex`를 Last mark price/funding으로 **별도 열거**한다. 따라서 일반 차트 캔들과 Mark 캔들을 같은 원천이라고 가정하는 것은 금지.
**CODE_OBSERVATION**: ZEL `scalp7_source_data_v2.py`의 `SOURCE`는 `quote/klines`이며 `markPriceKlines`가 아니다. 이것만으로 quote/klines가 정확히 Last-traded OHLC인지, 실제 Mark 가격과 얼마나 달랐는지는 아직 미확인이다.
**검증 가치**: Squeeze `signal-low` 및 Keltner 모델 Stop은 `MODEL_QUOTE_KLINE_OHLC`로 출처를 밝혀야 하며 BingX Mark 기준 TP/SL과 완전 동일하다고 보고하면 안 된다. 필요한 증거: `raw_sha, event_ts, available_at, price_basis, native_trigger_basis, market, contract_type`. 신규 시장데이터 API 호출 없이 원문과 원형만 비교했다. 실제 손실 영향은 미측정.

## P09: Squeeze 저자 버전 분리 — Carter 정통 TTM ≠ LazyBear ≠ ZEL
**SOURCE_FACT**: LazyBear 공개 TradingView 2014 indicator의 제작자 설명(https://www.tradingview.com/script/nqQ1DT5a-Squeeze-Momentum-Indicator-LazyBear/)은 John Carter의 **단순 momentum**과 자신의 **linear-regression histogram**이 다르다고 명시한다. 또한 2014-09-29 정정에서 페이지 구버전의 BB multiplier가 1.5에 고정되었던 오류를 알리고 수정 소스를 별도 링크한다. 수정된 전체 스크립트 본문은 이번에 검증하지 않았으며 ZEL에 해당 오류가 존재한다는 뜻이 아니다.
**CODE_OBSERVATION**: ZEL `_last_momenta`는 41개 완성봉 범위에서 20봉 high/low/SMA20 기반 delta를 계산한 뒤 20봉 선형회귀 종점을 사용한다. 같은 **linreg 계열**이지만 전체 신호, BB/KC 경계, 세그먼트, entry와 exit가 LazyBear와 동등하다는 증거는 없다.
**H01 영향**: LazyBear의 색상 변화나 Carter의 Squeeze 설명을 ZEL `momenta[2]>0 && momenta[1]>0 && descending`의 두 양수 약화 청산과 동등시하지 않는다. 최초 음수 전환이 손실을 키웠는지는 원래 stop/next-open과 회복 승리까지 관측해야 한다. 신규 청산 후보나 경제 재실행을 시작하지 않았다.

## P10: HTF 실시간·과거 누출의 원저자 기술적 반례
**SOURCE_FACT**: TradingView Pine 공식 문서(https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)는 `request.security()` HTF 미확정 값이 실시간에는 변동하고 재시작 후 역사 구간에서 repaint될 수 있음을 설명한다. Pine에서는 `expression[1]`과 `lookahead=barmerge.lookahead_on` 조합을 확정 HTF 참조의 방법으로 제시한다. **Pine 구현 방법을 ZEL Python 코드에 직접 적용하라는 뜻이 아니다.**
**H03 영향**: BTC/상위봉의 최종 high/low/close를 해당 HTF가 아직 닫히지 않은 30분 진입판단에 붙이면 미래 유출이다. 검증 필드 `HTF_window_end, HTF_closed_at, HTF_available_at, signal_decision_at, latest_confirmed_HTF_id, segment/gap`. BTC의 미래 성과 또는 당일 최종 스윙을 사후 선택하면 H03은 무효. H03은 여전히 미동결 관측 질문이다.

## 4개 축 점검
- Keltner/HG: 초기 강추세/ADX 눌림·재무장 문제에 대한 새로운 확정 경제 우위는 없음. P08은 Stop의 자료가격·trigger 가격 분리 근거.
- Squeeze: linreg 계열·Carter/LazyBear/ZEL 비동등을 구분. 기존 H01 승인 signal-low와 중복 변경 금지.
- 청산·승리 보존: Stop 종류와 실제 청산 시가 및 후속 점유, 정상 회복승리·큰 승리 훼손은 별도로 추적해야 함. 외부 지표 설명으로 청산 이익 주장 금지.
- 차트/MTF/공개 구현: P10에서 상위봉 시각 반례를 확인. 피보나치/캔들/영상 신규 수익 우위·현 조회수는 미확인. 신규 영상 전편 시청·대본 확인 0건.

## 판정·보존
세 가지 자료는 모두 공개 HTML 본문과 원형 코드만 확인했다. 외부 숫자 최적화·실험·새 경제후보·시장 API·유료 모델·주문·배포 0건. 신규 경제 run/receipt 없으므로 `ACTUAL_ECONOMIC_RESULT=NOT_RUN`, 비용 후 이익·WR·PF·DD 개선은 **미측정**. owner `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` 그대로. 기존 우선순위 Keltner fresh-touch → Squeeze signal-low 불변. CF/GS 실주문 MinData 미확인, 거래결정 [UNSURE]+HOLD.

**저장 결과:** 전용 연구 브랜치 새 파일 작성을 시도했지만 GitHub 연결 쓰기 안전검사에서 차단됐으며 원격 저장·커밋은 이루어지지 않았다. 이 로컬 보고서만 보존. Issue1414/1334 댓글도 작성하지 않았다.
