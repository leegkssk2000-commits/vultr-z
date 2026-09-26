# 원래 25개 구현 범위와 남은 공백

범위는 `G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1`이다. 원래 25개 ID를 유지하며 MR/Micro 또는 옛 Active5·G5 결과로 분모를 바꾸지 않는다.

이번 증분에는 수량·주문 수명·무효화·청산·계좌 연결을 갖춘 **연구 모델 7개**가 있다. 이는 6개 전략 행에 걸치며 `trend_rider`와 `session_bias`는 같은 Noise 모델이다. 독립적으로 셈하는 모델은 ST 2개, SR 2개, Noise 1개, Anti 1개, Soup 1개다.

ST/SR/Noise의 5개는 코드·자료·비용·기간을 최종 동결하여 최소 신규 FULL 제안으로 묶었다. Anti/Soup는 역사 tick 증거가 없어 포함하지 않았다. 나머지 19개 행은 부품·자료·명세·caller 공백이 남는다. **25개 전체 구현, G4 전체 완료, 원형 완전 재현 또는 수익성 검증을 뜻하지 않는다.** 원형 완전 재현 인증 0개, 이번 신규 FULL 0회다.

아래의 원문 개념·기존 동결 코드·독자 가설 구분은 각 행의 감사 경로와 모델 코드에 결속된다. 숫자와 청산을 선언 가설로 보완한 모델을 원저자 전체 시스템으로 표시하지 않는다. 실행 준비와 실행 권한도 구분한다.

| 원래 ID | 현재 상태 | 이번에 닫거나 보존한 공백 | 남은 작업·증거 |
|---|---|---|---|
| alpha_combo | 융합 조건 미충족; 배정 회계 부품 유지 | 기존 유효 신호만 배정하고 빈 sleeve를 현금으로 남기는 자본 부품을 완결 전략과 구분했다. 신규 융합 모델은 만들지 않았다. | 독립적으로 fresh 검증된 B 재료 최소 2개가 없고, 조합 구성·상관/행동 중복·위험 이전 정책과 실제 포트폴리오 caller가 미완성이다. |
| anchor_vwap_trend | 자료 근거 부족 및 자동 anchor·관리 구현 미완료 | 실제 quote/base 누적 VWAP 부품과 가격 reclaim을 분리한 상태를 유지하고, 알 수 없는 volume 단위를 임의로 BASE로 지정하지 않도록 경계를 명시했다. | 고정 anchor를 자동으로 선택하는 인과적 사건 규칙, 수량·주문 수명·전체 청산이 아직 없다. canonical volume 단위와 실제 quote/base 누적자료도 미확인이다. |
| bb_revert | BBIII 부품 유지; 거래량 근거와 전체 관리 미완료 | 기존 알림→이후 가격 확인 경로를 보존했다. PR1343의 시험용 수량·청산 profile을 실제 기준 전략으로 승격하지 않았다. | Intraday Intensity에 사용하는 volume 단위·자료 근거, 선택한 확인/만료 해석, 독립 전략 또는 host 역할, 위험·전체 청산의 연구 명세가 미완성이다. |
| break_and_continue | Gajjala/ORB 부품 유지; 실행 가능한 전체 후보 미완료 | 이미 완료된 flag/Rider 실험을 반복하지 않고 Gajjala 계보와 native ORB 경로를 구분했다. | Gajjala 15m flag의 원 선정·관리 중 어떤 부분을 재현하거나 선언 가설로 보완할지 미정이며, 수량·전체 lifecycle caller가 미완성이다. native ORB에는 당시 미국 종목군·주식 단위·세션 자료가 없다. |
| ema_ribbon_scalp | Kell 구조 부품; 상위 문맥·단계별 관리 구현 미완료 | EMA 교차 이후 지지·수축·확정 pivot 관찰 부품을 보존했다. 임의 공통 TP/hold를 붙여 완결 전략으로 세지 않았다. | Kell의 어떤 phase와 상위 timeframe을 적용할지, 단계 전환의 수치화, 부분 청산·수량·조건부 주문 수명 및 전체 관리 연결이 미완성이다. |
| fvg_revert | FVG 인과 순서 부품; limit 체결 근거와 전체 청산 미완료 | 3봉 확정·sweep→MSS→미래 zone 재방문을 유지하고 OHLC touch를 체결로 간주하지 않는 실행 경계를 명시했다. | 실제 resting-limit 체결 자료 또는 별도로 명시된 체결 모델이 없고, 선택한 목표·부분 청산 및 전체 위험 관리가 미완성이다. |
| grid_rebalance | DGT 원 코드 연결·재설정 구현과 native spot 자료 미완료 | 유한 현금·현물 재고·원가·fill별 비용 회계와 grid 주문 생산자를 구분했다. perpetual 봉을 원 spot inventory 실행 증거로 사용하지 않았다. | 동결 DGT runner/callee 호출 정합, grid 수준·주문·재설정·현금 유입 처리 및 경로 의존성 구현을 끝내지 못했다. native spot 체결·재고 입력도 없다. |
| keltner_trend | 양수 parent와 별도 fresh 후보 보존; 신규 수선 모델 없음 | 현재 parent와 preregistered TREND_DISPERSED +0.75R BE 후보의 신원을 유지했다. 완료된 historical 청산 retune을 반복하지 않았다. | HG 1997/2004 중 선택 원 모드의 재자격·조건부 주문·원 trailing·수량을 갖춘 별도 전체 수선 모델은 미완성이다. 기존 fresh 후보의 새 rolling/fresh 경제 검증도 아직 없다. |
| liquidity_sweep | Soup 완결 연구 모델 구현; 역사 tick 증거 미확보 | 실제 20일/극값 나이4일 Soup 생산자를 15m 조건부 주문·수량·인식 시점 stop·가격 회복 실패/후행 청산·세션 종료에 연결했다. lifecycle 보완은 독자 가설로 표시했다. | 기간·심볼에 대응하는 PIT tick 원자료의 진위·유효기간 검증이 없다. OFI는 별도 실제 BBO 부품이며 이 가격 모델에 합성하지 않았다. 새 경제성은 미측정이다. |
| mfi_rsi_div | 같은 price pivot divergence 관찰 부품; host 조치 미구현 | 관찰 신호를 매매 진입으로 오인하지 않도록 역할을 유지했다. 새 host 투표나 임의 청산을 만들지 않았다. | RSI/MFI divergence 이후 어떤 가격 확인으로 어떤 host 행동을 바꿀지 미정이다. MFI에는 거래량 근거도 부족하며 진입/관리 대조군·위험·청산이 미완성이다. |
| obv_trend | 참여량 관찰 부품; host 역할·자료 단위 미완료 | 부호 있는 volume 누적을 독립 매매 전략으로 세지 않고 기존 계산을 보존했다. | host에서 진입·보유·위험 중 무엇을 바꾸는지와 대조군이 미정이다. 역사 volume의 원 단위가 미확인으로 원 거래량 주장에 제한이 있다. |
| pivot_reversal | 확정 지지/pivot 부품; 전체 reversal 모델 구현 미완료 | 반전 관찰→지지·수축→right-bar 확정 pivot을 유지하며 HLC pivot이나 Soup와 같은 전략으로 취급하지 않았다. | 어떤 reversal phase를 거래할지, 재량 지지의 수치화·주문 수명·구조 stop·목표·규모/청산이 미완성이다. |
| range_fade | Anti 지속형 완결 연구 모델 구현; tick 근거 미확보 | 이름에 따른 범위 역매매를 배제하고 선행 impulse→작은 flag→동일 방향 재개를 실제 producer·수량·minute 주문·진입 후 확정 반대 pivot stop·계좌에 연결했다. | 역사 instrument tick receipt가 없어 실제 자료 실행 준비는 조건부다. 독립 baseline 하나이므로 같은 진입의 청산 개선 효과나 기존 range-fade 실패 반전을 주장할 수 없다. |
| rbreaker_like | 원 1m 주문·포지션/OCO·trail/EOD caller 구현 미완료 | 이전 세션 수준과 native 30×1m qualification 부품을 보존했고, 이를 30×15m 또는 30×30m로 몰래 바꾸지 않았다. | 실제 native position/OCO 의미, 체결 이후 trailing·세션 종료·수량을 갖춘 caller가 아직 없다. 15m/30m 최종 의사결정에 결속하는 방식을 별도로 정의해야 한다. |
| rsi_swing_fail | 완료된 실패 유지; 새 역할·전체 후보 미완료 | PR1340 oscillator entry 결과와 기존 RSI/8bar adaptation을 보존하고 동일 비교나 R2 이름 교체를 반복하지 않았다. | 기존 실패를 넘는 독립 인과 축 또는 host 역할을 선정하지 않았으며 그에 맞는 위험/전체 관리 구현도 없다. |
| scalp_snap | Gajjala 공유 계보 부품; 독립 관리 구현 미완료 | break_and_continue와 같은 flag 계보를 독립 B로 중복 계산하지 않고, 1m Short Skirt를 15m 기회로 복원하지 않았다. | 15m flag의 선정·다음 시장가 진입·위험·수량·관리 중 채택할 명세와 실제 완결 caller가 없다. native Short Skirt는 현재 최종 시간축과 맞지 않는다. |
| session_bias | 최종 동결 Noise의 같은 후보 별칭; 독립 재료 아님 | 14일 same-slot Noise base의 반대 band 반전·고정 session 수량·ack 이후 반전·EOD·동일 초기 자본 sleeve를 연결했다. trend_rider와 동일 identity를 공유한다. | 동일 Noise 후보의 자료·비용·기간 결속은 완료됐다. 신규 FULL 배정과 경제성 검증이 남고, 별도 native stock ORB는 PIT 미국 종목군·주식/세션 입력과 실행 계좌가 없다. |
| squeeze_break | parent/BE1R/High2 완료 신원과 결과 보존; 새 축 없음 | 이미 완료된 High2 비교와 owner/false-fire 실패를 반복하지 않았고 parent와 BE1R의 frozen identity를 유지했다. | BE1R의 새로운 fresh/rolling 증거가 없으며 독립 causal axis를 갖춘 추가 개선 후보를 구현하지 않았다. Carter의 options payoff·원 daily/weekly 관리도 전체 복제되지 않았다. |
| sr_levels | 동일 조건 SR 대조군/child 최종 동결; 신규 FULL 승인 대기 | 직전 완전 UTC-day box를 고정하고 첫 breakout 진입과 이후 retest 진입을 동일 stop·실패 청산·세션 종료·수량 조건으로 연결했다. 실제 producer→fill→청산→계좌 경로를 시험했다. | 원문·코드·자료·비용·기간 결속 완료. 신규 FULL 배정과 실제 경제 비교는 미실행이며 역사 funding은 미확인이다. |
| supertrend_pullback | 새 entry sequence와 청산 대조군/child 최종 동결; 신규 FULL 승인 대기 | direction flip→추진 확인→눌림→재개를 진입으로 만들고 초기 구조 stop 고정 대조군과 완료 band 추적 child를 같은 수량·시간·실패/EOD 조건으로 연결했다. | 최종 2개 identity 결속 완료. 신규 FULL 배정·전체 경제 비교·fresh 검증이 없고 원형 전체 인증은 아니다. |
| trend_ma_macd | 독립 계산 부품 유지; host 경제 역할 미구현 | Raschke SMA3−SMA10/SMA16, GMMA, EMA-MACD를 서로 다른 모드로 유지하며 임의 다수결 신호나 PR1341 재진입을 만들지 않았다. | 어느 계산이 어느 host의 어떤 조치를 바꾸는지, 단일 축 대조군과 위험·관리 연결을 아직 선정·구현하지 않았다. |
| trend_rider | Noise 6심볼 고정 sleeve 최종 동결; 신규 FULL 승인 대기 | 14일 같은 slot base mode, 완료30m 결정, 반대 band 반전, acknowledged close 이후 재진입, session 수량·현금·EOD 및 고정 동일 자본 sleeve를 연결했다. | 코드·자료·비용·기간 결속 완료. 신규 FULL 배정·실제 경제 평가가 없으며 funding 미확인·native SPY 재현 제한을 유지한다. |
| turtle_trend | native daily 부품 유지; 전체 pyramiding·포트폴리오 caller 미완료 | 실제 20/55일·10/20일 channel/N20 및 filled-unit 부품을 보존하고 일 단위를 intraday 봉 수로 바꾸지 않았다. | System2의 실제 unit 추가·체결·계좌 및 다시장 상관/위험 한도 caller가 미완성이다. System1은 별도의 virtual 마지막 승리 ledger도 없다. 어떤 시스템을 Scalp7에 어떻게 이식할지도 명시적으로 마쳐야 한다. |
| vol_spike_fade | parabolic price-retest 부품; 선정·short 관리 구현 미완료 | 다일 확장→첫 crack→약한 rebound→가격 실패 관찰 부품을 유지하며 coin UTC 자료를 원 주식 short 전체로 취급하지 않았다. | native stock 또는 crypto 이식 역할, 실제 선정·borrow/perp 위험, 분할 청산·규모·전체 lifecycle 연결이 미완성이다. VWAP 경로를 택하면 추가 volume 근거도 필요하다. |
| vwap_revert | VWAP failed-retest 부품; 원자료·선정·관리 미완료 | VWAP 이탈→이후 failed retest를 단순 가격 거리 진입과 구분했다. 없는 quote/base 자료를 proxy로 대체해 진짜 VWAP라고 하지 않았다. | 실제 VWAP 자료와 causal anchor, 원 parabolic 선정/확장·crack 문맥 및 위험·규모·전체 청산을 아직 결속하지 못했다. |

전체 행별 모델 ID·다음 증거·감사 파일은 [DRAFT_ROWS.json](DRAFT_ROWS.json)에 있다. 이 파일명의 DRAFT는 최종 보고 조립 단계의 이름이며, 이미 승인된 구현을 중지하는 사유가 아니다.

[RECOVERY_20260926.json](audits/RECOVERY_20260926.json)은 25개 ID와 실제 코드 catalog의 일치, 이전 완료 후보의 보존과 기존 예산 소진을 독립 확인했다. 모델의 실제 함수·코드·자료·비용·기간 결속은 [PREPARED_EXECUTION_REQUEST.json](PREPARED_EXECUTION_REQUEST.json) 및 `freezes/`를 따른다. 최종 코드 검증은 [VALIDATION.json](VALIDATION.json)을 따른다.

새 경제 결과가 없으므로 실제 T·WR·Net·DD 변화, 승리 훼손, C→B·B→A 성과는 이번 구현 증분에서 판정하지 않는다. 기존 실패를 취소하지 않았고 독립 fresh B 2개가 없어 B×B도 시작할 수 없다.

이번 최종 상태는 5개 freeze 생성 후의 상태다. DRAFT_ROWS와 과거 감사에 남은 결속 대기 문구는 단계별 이력으로 보존하며 MODEL_CLOSURE.json의 final_binding 및 실제 freezes/가 이를 대체한다. 구간 경계에서도 자본·포지션 점유는 연속한다. 이전 캠페인의 FLAT_INDEPENDENT_WINDOW와 같다고 해석하지 않는다.
