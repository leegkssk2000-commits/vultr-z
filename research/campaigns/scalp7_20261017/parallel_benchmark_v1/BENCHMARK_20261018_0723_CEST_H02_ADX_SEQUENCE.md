# H02 원저자 선행 ADX 시각·ZEL 원형 차이 — 2026-10-18 07:23 CEST

범위: SOURCE_FACT 및 CODE_OBSERVATION만. 기존 2026-10-17 P11 로컬 조사의 원격 최초 보존으로, 새로운 독립 발견으로 중복 집계하지 않는다. 경제 owner, 원형, 권한, 기존 FULL 승인/소비원장 변경 없음.

## 1차 출처
- Mark Etzkorn / Linda Bradford Raschke, Active Trader 2004년 3월호, 인쇄 pp.76–79, 전체 PDF https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf . 인쇄 p.78 Figure 1: 2003년 12월 SPX 30분봉에서 14-bar ADX>30의 선행 상승 → 모멘텀 고점 → 20-EMA 눌림이 별개 사건이다. p.79의 5/15→30→60→120분 순차 접촉은 사례이며, 각 시간봉마다 접촉 전에 자체 ADX>30 필요하다고 설명한다.
- 원저자는 같은 인터뷰 인쇄 p.77에서 완전 기계식 진입·청산·stop 시스템보다 통계적인 시장 경향을 거래 판단 참고로 사용한다고 설명한다. 따라서 자동 상태기계의 세부 lifecycle을 저자와 완전 동일한 것으로 단정할 수 없다.
- 최초 HG 인터뷰: https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf . 최초 ADX의 상승, 눌림 중 정상 ADX 둔화, 이전 봉 고점 위 buy-stop, 신규 swing-low stop을 구분한다. ZEL 종가반전·다음시가 모델은 체결 번역이며 저자 원형 buy-stop과 동일하지 않다.
- 출처 시장/TF는 미국 SPX 30m 및 전통 주식/선물; BingX 30m 비용·순익·T·PF·DD·회복 승리는 미보고.

## 원형 코드 차이
- 동결 코드 backend/research/rebuild/scalp7_positive_lanes_v2.py, Git blob 79b9934b471cbe0f4342b265c90b2c9c8884f52c. _hg_event의 강추세 판정은 그 봉의 방향, adx14>=30, EMA20 기울기다. 접촉 이전의 첫 ADX>30 상승 시각이 있어야 한다는 시간순 계약은 없다.
- strong=False인 동안 adx14<25 또는 방향 상실이면 reset하지만, ADX 25–30·방향 유지이면 기존 touch/stage 상태를 보존한다. 따라서 최초 touch 이전의 선행 강추세 누락 가능성과, weak 구간을 지난 오래된 touch 재사용 가능성이 공존한다.
- 기존 observer ops/scalp7_benchmark_observer_v1.py blob a51a3d52c438ebf143d2d850bb8406c288ba226d는 touch/weak 상태를 관측하지만, first_adx_gt30_up_ts < first_touch_ts 명시 검증은 하지 않는다. 기존 fresh-touch-after-reject는 거절 후 reset으로, 그 이전의 선행조건 질문과 중복 규칙이 아니다.

## 분석용 선택 필드·반증
비교 중 있을 경우 원래 관측을 방해하지 않는 부가 필드: symbol, segment_id, first_adx_gt30_up_ts, first_touch_ts, first_turn_ts, adx_asof, adx_delta_asof, event_available_at, raw_state_before/after, original_admission/rejection, source_sha. 의사결정 당시 완료된 30m 봉만 사용한다. 원래 거래와 회복 승리를 모두 포함하고, 실제 OHLC 경로 결손은 UNKNOWN으로 둔다.
반례 A: ADX 31 상승 → EMA 첫 접촉에서 28 → 반전에서 31은 저자 선행조건이 성립하지만 기존 state0 터치가 누락될 수 있다. 반례 B: 과거 touch가 ADX25–30 구간에 남아 강추세 복귀 때 사용될 수 있다. 모두 인공 경로이며 경제 우위의 증명이 아니다.

## 네 축의 다음 상태
Keltner/H02: 위 시각 필드만 의미 있게 보완. Squeeze/H01: 음수 모멘텀 전환과 원 stop/max-hold/signal-low 선후·회복승리는 실제 가격경로가 없어서 미측정. 청산/승리보존: 비용후 거래 원장 없는 개선 주장 금지. 차트·HTF: 다른 TF의 최종봉/미래 성과를 30m 판단 시점에 제공하지 않는다.

결론: 신규 전략, 임계치, 관측기 개발, 시장 API, FULL, shadow, Paper/Live, 경제 claim/owner/master/workflow 변경 0. ACTUAL_ECONOMIC_RESULT=NOT_MEASURED. 인계가 기존 승인된 Keltner→Squeeze 비교를 지연시키지 않는다.
