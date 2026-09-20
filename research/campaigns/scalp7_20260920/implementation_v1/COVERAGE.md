# Exact25 원문→코드 구현 현황

**25개 ID에 호출 가능한 수치·이벤트·회계 부품을 연결했다. 원형 전체 전략 인증 0개, 동결된 완결 연구 후보 0개, 새 경제실행 0회다.**

이 문서는 구현 대응표다. T·WR·Net·DD 변화는 새 경제실행이 없어 미측정이며, 기존 실패 판단을 뒤집지 않는다. MR/Micro를 포함해 27개로 확대하지 않는다.

원문 규칙·기존 동결 수식·선언 가설을 구분했다. `EXACT25_IMPLEMENTATION.json`에는 각 실제 모듈/함수 SHA, mode/rule ID, 테스트 및 검수 파일을 결속했다. 아래 “구현”은 해당 부품 범위의 구현이며 원형 전체 복제나 수익성 준비 완료를 뜻하지 않는다.

| # | ID | 실제 닫은 구현 결손 | 남은 원문·모드·자료·lifecycle 결손 | 다음 필수 결속 |
|---:|---|---|---|---|
| 1 | `alpha_combo` | 고정 가중치·이미 유효한 신호만 위험 배정, 빈 sleeve는 현금 | 독립 구성전략 경제성·구성 승인·동률/위험 정책이 미확정 | 검증된 구성원과 현금/동률/손실 정책을 선정·동결한 뒤 계좌 caller 연결 |
| 2 | `anchor_vwap_trend` | 고정 anchor의 실제 quote/base 누적과 인지시각, reclaim 생산자 | 자동 anchor 선정·수량·전체 청산 미정; HLC3는 trade VWAP 아님 | anchor 선정·모드·volume 자료를 고정하고 진입 만료/위험/청산 연결 |
| 3 | `bb_revert` | 실제 BB·Intraday Intensity 알림과 이후 동일일 가격확인 | 선택한 II/확인 해석·TradeStation 일치 미인증, 전체 주문/위험/청산 없음 | II 버전·확인/만료와 standalone 또는 host 역할 및 위험/청산 동결 |
| 4 | `break_and_continue` | Gajjala 원시 flag 순서; 별도 ORB PIT·RVOL·완성 range/방향 | Gajjala 재량 관리 미정; ORB 미국 당시 종목군·실제 체결 기준 stop/size 미결속 | flag와 ORB 중 원 모드 선택, native 자료·위험/관리/수량 동결 |
| 5 | `ema_ribbon_scalp` | EMA 교차 관찰 이후 지지·수축·확정 pivot과 조건부 trigger | Kell 전체 6단계·상위 TF 선정·부분청산/규모 미정 | Kell 선택 모드와 phase 수치·상위 문맥·조건부 주문 관리 동결 |
| 6 | `fvg_revert` | 실제 3봉 FVG, 과거 sweep→MSS→3번째 완료→미래 재접촉 | pivot/displacement/expiry/stop은 선언 가설, 전체 목표/부분청산 없음 | swing·displacement·zone 만료·risk/target 선택과 limit 체결 근거 결속 |
| 7 | `grid_rebalance` | 실제 fill의 유한 현금/현물 재고·원가·수수료 회계 | DGT 호출 불일치·grid 재설정/주문·경로 미결속, 현물과 perpetual 다름 | 고정 DGT 버전 호출/재설정/자본흐름 명세와 실제 fill 경로 해결 |
| 8 | `keltner_trend` | 원시 ADX14/EMA20 자격→첫 touch→조건부 가격, 1997/2004 분리 | 재자격/expiry 일부는 가설, 원 trailing/크기/주문수명 미완성 | 양수 parent 보존, 선택 원 버전의 조건부 체결·관리 차이 명세 동결 |
| 9 | `liquidity_sweep` | 실제20일/극값 나이4일 Soup·5~10tick·당일 만료; 별도 실제 BBO OFI | PlusOne/전체 trail·size 미정; 지원 달력 제한; OFI는 단독 전략 아님 | Soup 달력/관리 또는 genuine BBO 호스트 역할 중 하나를 고정 |
| 10 | `mfi_rsi_div` | RSI/MFI 실제 수치와 동일한 두 price pivot의 인과적 divergence | pivot 수치 선택은 가설, 후속 가격확인·host 역할·위험/청산 미정 | oscillator/pivot 정의 및 가격확인·호스트 조치·risk/exit 동결 |
| 11 | `obv_trend` | 종가 방향별 실제 volume 누적, 동일 종가 변화0·참여량 분리 | OBV만으로 정당한 단독 진입 없음; 호스트 기여 미검증 | OBV 수치의 구체적 host 역할과 진입/관리 대조군 선정 |
| 12 | `pivot_reversal` | 반전 관찰→지지/수축→right-bar 확정 price pivot, HLC pivot과 분리 | 재량 지지/pivot 수치·원모드 목표/규모/청산 불완전 | 관찰용 또는 반전 진입 역할과 구조 무효화·목표·주문관리 동결 |
| 13 | `range_fade` | C02 Anti의 선행 impulse→작은 flag→같은 방향 재개 | Anti 수치화는 가설; Soup/BBIII 경계 반전은 별도, 전체 관리 없음 | Anti 지속 또는 별도 범위반전 모드를 명시해 source·risk/exit 고정 |
| 14 | `rbreaker_like` | vn.py 고정 버전 실제 계수·이전 session 수준과 native1m 주문 계획 | 15/30 평가에서 원1m/30bar callback을 대체하지 않음; 체결·포지션/EOD 미연결 | native clock·실제 position/OCO 의미·trail/EOD caller·size 결속 |
| 15 | `rsi_swing_fail` | 원시 RSI와 기존 동결 oscillator 순서 함수만 재사용 | RSI seed/8bar adaptation 명시, standalone risk/exit 없음; R2는 별도 | 기존 실패를 보존하고 선택 oscillator host 역할·진입/청산 동결 |
| 16 | `scalp_snap` | 15m Gajjala impulse·낮은 volume 눌림·가격재개, ShortSkirt 시간축 차단 | 원 종목선정/재량 관리 미정; 1m/2~10분 기회를15m로 복원 불가 | 15m 적합 flag의 선정·시장가 지연·위험/수량/청산만 동결 |
| 17 | `session_bias` | DST/session ordinal·과거14 같은 slot·ORB와 Noise-Area 분리 | 휴장/조기종료 달력 책임·ORB PIT 전체 종목군·유한계좌 미결속 | 원 session 공급자와 모드 선택, 실제 당시 종목군·자본 caller 결속 |
| 18 | `squeeze_break` | 기존 동결 TTM 수치 함수를 직접 호출, 실제 fire/갭/가용시각 | proprietary 정확식 인증 아님; Carter 옵션 payoff/일·주 ATR/3거래일 관리 미복제 | 기존 parent/BE1R/High2 결과 보존, 별도 충분한 causal axis와 적용 lifecycle 선정 |
| 19 | `sr_levels` | breakout 이전 고정 box와 미래 retest/reclaim/failure, 현재봉 제외 | box 선택 자체 가설·Carter 전체 관리 불완전 | reference 선정/유효성·실패/재접촉 모드와 전체 위험/청산 동결 |
| 20 | `supertrend_pullback` | ATR seed·이전 band/direction 재귀와 완료 이후 가용시각 | 수치 Supertrend 부품일 뿐 pullback 진입·독립 edge 없음 | flip/pullback 역할·setup/lifecycle·대조군 고정; 현재 실패 보존 |
| 21 | `trend_ma_macd` | Raschke SMA3−SMA10/SMA16, GMMA와 EMA-MACD를 독립 모드로 계산 | 지표 산식은 전략 아님; host·entry/risk/exit·경제 기여 없음 | 한 계산의 실제 host 역할을 고정하고 완료된 PR1341 구조는 반복 금지 |
| 22 | `trend_rider` | Noise-Area 과거14 same-slot·gap band·완료30m 목표·lagged exposure/EOD | SPY native fills·size/계좌 미결속; HLC3 VWAP는 candle proxy | 원SPY 또는 명시 코인 adaptation, execution·risk/계좌·비교경계 동결 |
| 23 | `turtle_trend` | 일 단위20/55·10/20채널/N20·실제filled unit의0.5N/2N/max4 | System1 virtual breakout ledger 미구현; 다시장/상관·자본한도 및 전체 fill 미완성 | System2 또는 System1 선택 후 가상 breakout·실제 unit·포트폴리오 한도 결속 |
| 24 | `vol_spike_fade` | 실제 다일 확장→첫 crack→약한 rebound→후속 price failure | UTC24h는 코인 adaptation; 원주식 borrow/선정/전체 split exit와VWAP모드 미복제 | price-retest 모드·native/adapted 자료·보수적 short risk/exit 동결 |
| 25 | `vwap_revert` | 고정 실제 VWAP의 breakdown→미래 failed retest, 단순 거리진입 배제 | 원 Qulla 선택/확장/crack 전체와 청산 미결속; 범용평균회귀 전략 아님 | 고정 anchor/price failure의 host 또는 독립 역할과 risk/exit 명시 |

## 단계별 판정

| 구분 | 결과 | 의미 |
|---|---:|---|
| exact25 부품/이벤트/회계 호출 경로 | 25 | 각 표의 한정된 구현 범위 |
| 원형 전체 전략 인증 | 0 | 미확보 원문·모드·관리·자료 결손이 남음 |
| 동결된 완결 신규 연구 baseline | 0 | 실제 후보 선정·전체 규칙·자료·실행 결속이 아직 없음 |
| 현재 동결 집합에 필요한 신규 대조군/FULL | 0 / 0 | 현재 집합이 비어 있음; 향후 필요 실행수가0이라는 뜻 아님 |
| 새 경제실행/공식 승격 | 0 / 0 | 이번 범위는 신규 FULL 예산 없음 |

향후 FULL 필요량은 **미정**이다. 실제 완결 후보와 재사용 가능한 대조군을 확인한 뒤 산정해야 하며, 임의의 25회/50회 상한을 부여하지 않는다. 테스트 개수나 모듈 존재만으로 경제실행 준비를 판정하지 않는다.

## 공통 caller 및 경제 경계

- 공통 dispatcher 25개 등록과 BBIII 인공시세 1개 경로의 source→model→snapshot 통합만 입증했다. 나머지24개 전체 경로의 통합 입증으로 확대하지 않으며, BBIII도 명시적 시험용 보완 profile이므로 동결된 원형 전체 전략이나 경제실행 준비 완료가 아니다.
- 부분 intent의 수량·만료·위험·전체 청산 결손을 caller가 임의 기본값으로 채우면 다른 모델이다. 선택한 보완 규칙은 선언 가설로 명시해 동결해야 한다.
- `session_bias`와 `trend_rider`의 Noise-Area, `break_and_continue`와 `scalp_snap`의 Gajjala 계보는 이름이 달라도 독립 재료로 중복 계산하지 않는다. behavior cosine은 미측정이며 B×B는 차단 상태다.
- Short Skirt의 native 시간축은 15m로 복원하지 않는다. Turtle/Soup의 일 단위, R-Breaker의 native1m, 원 옵션 payoff와 미국 종목군을 코인 봉으로 묵시 변환하지 않는다.
- 구조 모듈 내부의 inclusive/exclusive close 허용과 주문 어댑터의 canonical exclusive close는 caller에서 명시적으로 결속해야 하며, 1ms 이전 체결을 추론하지 않는다.

## 보존 및 권한

PR1340/1341의 실제 비교와 실패·승리 훼손 결과는 유지한다. 이번 코드 구현으로 기존 Top7·재료20 등급이나 경제 수치를 변경하지 않았다. 새 T·WR·Net·DD·fresh 성과는 `null / NOT_RUN`이며 0수익으로 표현하지 않는다.

주문·LIVE·승격은 BLOCKED다. 유료 지출·서비스 변경·배포는 없으며, 배포할 필요도 없다. 롤백은 이번 추가 구현/검수 파일에 한정하며 기존 동결 연구 결과를 되돌리지 않는다.


## 원문 결손과 설정된 실행 경로의 구분

모든 ID가 공통 dispatcher에 등록되는 것과 25개 전체의 주문·계좌 통합 입증은 다르다. OBV·divergence·Supertrend·MACD 등은 부품 출력이며 자동 완결 매매 신호로 세지 않는다.

| ID | 남은 원문/전략 결손 | 현재 실행 경로의 범위 |
|---|---|---|
| `alpha_combo` | 독립 구성전략 경제성·구성 승인·동률/위험 정책이 미확정 | 배정 회계만 구현; 기존 valid signals 외 신규 진입 생성 없음 |
| `anchor_vwap_trend` | 자동 anchor 선정·수량·전체 청산 미정; HLC3는 trade VWAP 아님 | reclaim 부분 intent; anchor·수량·만료·전체 청산 완성 필요 |
| `bb_revert` | 선택한 II/확인 해석·TradeStation 일치 미인증, 전체 주문/위험/청산 없음 | BBIII 부분 intent; 명시적 인공시험 profile로만 source→model→snapshot 통합 입증 |
| `break_and_continue` | Gajjala 재량 관리 미정; ORB 미국 당시 종목군·실제 체결 기준 stop/size 미결속 | flag/ORB intent; 원 종목군·체결 기준 risk·수량/관리 결속 필요 |
| `ema_ribbon_scalp` | Kell 전체 6단계·상위 TF 선정·부분청산/규모 미정 | 확정 pivot의 부분 stop intent; 수량·주문수명·전체 관리 미정 |
| `fvg_revert` | pivot/displacement/expiry/stop은 선언 가설, 전체 목표/부분청산 없음 | zone/재방문 부분 limit intent; touch는 fill 아님, 수량/전체 관리 미정 |
| `grid_rebalance` | DGT 호출 불일치·grid 재설정/주문·경로 미결속, 현물과 perpetual 다름 | 실제 fill 현물 회계만 구현; grid 주문/재설정 생산자 없음 |
| `keltner_trend` | 재자격/expiry 일부는 가설, 원 trailing/크기/주문수명 미완성 | 부분 조건부 stop intent; 미래 체결·수량·만료/전체 관리 미정 |
| `liquidity_sweep` | PlusOne/전체 trail·size 미정; 지원 달력 제한; OFI는 단독 전략 아님 | Soup 부분 stop intent 또는 OFI 수치; OFI 자체 주문 없음 |
| `mfi_rsi_div` | pivot 수치 선택은 가설, 후속 가격확인·host 역할·위험/청산 미정 | divergence 관찰 부품; 가격확인·진입 주문 없음 |
| `obv_trend` | OBV만으로 정당한 단독 진입 없음; 호스트 기여 미검증 | OBV 수치/참여량 관찰만; 진입 신호 없음 |
| `pivot_reversal` | 재량 지지/pivot 수치·원모드 목표/규모/청산 불완전 | 관찰 후 pivot 부분 stop intent; 전체 risk/lifecycle 미정 |
| `range_fade` | Anti 수치화는 가설; Soup/BBIII 경계 반전은 별도, 전체 관리 없음 | Anti 부분 next-open intent; 관리·수량·만료 미정 |
| `rbreaker_like` | 15/30 평가에서 원1m/30bar callback을 대체하지 않음; 체결·포지션/EOD 미연결 | 15/30 고정 수준 및 별도 native1m 주문 계획; 포지션/체결 연결 미완성 |
| `rsi_swing_fail` | RSI seed/8bar adaptation 명시, standalone risk/exit 없음; R2는 별도 | oscillator failure 관찰 부품; standalone 주문/관리 없음 |
| `scalp_snap` | 원 종목선정/재량 관리 미정; 1m/2~10분 기회를15m로 복원 불가 | 15m flag 부분 intent; native ShortSkirt 모드는 명시 차단 |
| `session_bias` | 휴장/조기종료 달력 책임·ORB PIT 전체 종목군·유한계좌 미결속 | 모드별 노출 목표/ORB intent; 실제 당시 종목군·체결/계좌 결속 필요 |
| `squeeze_break` | proprietary 정확식 인증 아님; Carter 옵션 payoff/일·주 ATR/3거래일 관리 미복제 | 동결 TTM 수치/fire 관찰; Carter 원 옵션 주문/관리 없음 |
| `sr_levels` | box 선택 자체 가설·Carter 전체 관리 불완전 | 고정 수준의 retest/reclaim 부분 intent; 전체 관리 미정 |
| `supertrend_pullback` | 수치 Supertrend 부품일 뿐 pullback 진입·독립 edge 없음 | 방향/band 관찰만; pullback 진입 생산자 아님 |
| `trend_ma_macd` | 지표 산식은 전략 아님; host·entry/risk/exit·경제 기여 없음 | SMA/GMMA/EMA 지표 관찰만; 독립 진입 없음 |
| `trend_rider` | SPY native fills·size/계좌 미결속; HLC3 VWAP는 candle proxy | Noise-Area 목표 노출/청산 관찰; 실제 fill·수량/유한계좌 미결속 |
| `turtle_trend` | System1 virtual breakout ledger 미구현; 다시장/상관·자본한도 및 전체 fill 미완성 | 일봉 reference/실제 filled-unit 상태; 완결된 거래/가상원장 미구현 |
| `vol_spike_fade` | UTC24h는 코인 adaptation; 원주식 borrow/선정/전체 split exit와VWAP모드 미복제 | price-retest 부분 short intent; 선정·수량/전체 관리 미정 |
| `vwap_revert` | 원 Qulla 선택/확장/crack 전체와 청산 미결속; 범용평균회귀 전략 아님 | fixed VWAP failed-retest 부분 intent; 완결 전략 아님 |
