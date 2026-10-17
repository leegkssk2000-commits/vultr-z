# ZEL 병렬 벤치마킹 — 2026-10-17 13:20 CEST (4회차)

상태: **PUBLIC_RESEARCH_ONLY / NO_ECONOMIC_RUN / NO_RULE_OR_BUDGET_CHANGE / NO_PAID_API**. 네 축의 새 원문·재현·반대 근거를 동시 검색하되, 별도 경제실험 에이전트나 연구 플랫폼을 생성하지 않았다.

선행 증거: 같은 branch의 `RESEARCH.md` blob `4453106d4dee89e0eb2a9e3808d459b51df6665d`; `BENCHMARK_20261017_1222_CEST.md` blob `77a2afcd6beb0b1d9a52e4ce5ebf824370235e35`. 이전의 Raschke Holy Grail 원문, StockCharts TTM, ADX 상태 보존, QuantConnect gap, 시간당 비용/합성 결측 논문은 재등록하지 않았다. 경제 owner `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` 보존. 연구는 경제 claim·소비원장·OWNER/CHECKPOINT·원형 전략·workflow/주문을 수정하지 않았다.

## 실제 새 검토 자료 4건

### P05 — Jia, Wu, Yan & Liu (2023), *A seesaw effect in the cryptocurrency market*
- **SOURCE_FACT(논문 초록·서지까지):** *Journal of Empirical Finance* 74(C), DOI 10.1016/j.jempfin.2023.101428. 원저자·출판사 초록의 RePEc 색인 https://ideas.repec.org/a/eee/empfin/v74y2023ics0927539823000956.html ; 출판사 https://www.sciencedirect.com/science/article/pii/S0927539823000956 (본문 접근 실패). 구버전 SSRN 2019 존재하나 수정 전 원고와 2023 최종본의 저자·실험 세부 동일성을 추정하지 않는다.
- **AUTHOR_PERFORMANCE_CLAIM:** 단기 암호화폐 수익률에서 대형 코인 움직임이 소형 코인 뒤 수익률에 **음의 예측관계**를 보인다고 보고. LASSO 기반 전략이 거래비용 후 경제적 수익을 보였다는 것은 저자 주장으로만 기록한다. 정확한 ZEL 30m 거래수·bps·PF/DD·BingX 비용 결과는 이번 접근 가능한 초록에 없음.
- **H03에 주는 새 반증:** “BTC 강세 → 다른 코인의 이후 강세”라는 일방향 **양의 선행관계**를 자동 가정하면 안 된다. 동시간 양의 상관계수와 미래 수익률의 방향예측은 다른 통계량이다. **출처 시장/소형 코인 구성·신호 시간봉/현 ZEL 6종목/30m은 동일하지 않다.**
- **진단용 비경제 질문(새 후보 아님):** 모든 코인·모든 상태에 대해, BTC의 직전 *완료된* 30m 로그수익률과 해당 코인의 이후 결과 레이블의 관계를 따로 기록. 다른 축으로 현재까지의 상대진행도를 같은 as-of 시각에 맞춰 계산. BTC 자기 자신과의 상대비교 금지; 유효하지 않은 cross-symbol availability 및 결측은 fail-closed. 승리/손실 모두 보존하며 임계치·상관 방향을 결과 뒤 선택하지 않는다. 당장 “역추종” 전략을 열지 않는다.

### P06 — Azimli (2024), *Time-varying spillovers in high-order moments among cryptocurrencies*
- **SOURCE_FACT(HTML 전문; PDF 불필요):** *Financial Innovation* 10:96, 2024-03-04, https://link.springer.com/article/10.1186/s40854-024-00612-8 ; 2020-02-10~2022-08-20의 1분 자료로 BTC·ETH·BNB·ADA·LTC·XRP 6개 종목의 **일별** 실현 변동성·왜도·첨도 전이 네트워크(TVP-VAR) 추정. 데이터는 주로 Binance 현물 계열이라 현재 BingX USDT-M 및 ZEL 30m 보유전략과 동일하지 않음.
- **AUTHOR_FINDING:** 충격 전달/수신 역할이 시기·고차 모멘트에 따라 바뀜. 해당 표본/모형에서 BNB는 변동성 주 송신자였고 BTC·ETH는 수신자 성격도 보임. 충격의 **전달 방향과 수익률 선행방향을 동일 개념으로 취급하지 않는다.**
- **H03/H01 실질 의미:** BTC 단독 ‘리더’ 가정이나 6종목 손실 독립 가정에 반례. 폭락 시 공통 손실·fat-tail 위험과 상대강도 신호를 구분해야 한다. 손실 묶음이 동시 발생한 경우 장중 변화로 분류할 수 있어야 하며, 나중의 충격송신자 순위를 과거 진입 feature로 사용하면 lookahead.
- **반증/제약:** BTC 동반 하락 또는 특정 외부 충격에서 과거 상대강도가 손실/큰 승리를 구분하지 못하면 H03 포기. 본 연구는 계좌 PnL과 수익 필터 PASS를 보고하지 않는다.

### P07 — VectorBT PRO, *Stop loss and take profit* (공식 구현 설명)
- **SOURCE_FACT(공식 문서 읽음):** https://vectorbt.pro/features/backtesting/stop-loss-and-take-profit/ . stop/TP 동봉 충돌은 stop 우선; 새 고점으로 trailing을 올리기 전에 현재 봉 기존 stop을 검사; 갭은 stop 가격이 아니라 불리한 시가를 쓰는 모델을 설명. **의미 있는 별도 모델 차이:** 이 문서는 일반 신호 체결의 애매함 때문에 *entry bar*의 stop을 다음 봉부터 검사한다고 명시함.
- **CODE_OBSERVATION(ZEL master 원형 조회):** `backend/research/rebuild/scalp7_execution_v2.py` blob `11f7d9e632741dedb536035966f6c7a68befa38f`의 `_single`은 신호 다음 실제 시가에 진입하고, **그 진입 봉부터** 현 stop과 OHLC를 검사함. stop/target 동시일 때 stop 먼저; adverse open-gap이면 open fill; stop 뒤 callback/partial/next-stop 갱신; `hold_bars >= max_hold_bars`가 되면 다음 시가 pending exit. VectorBT PRO의 보수적 entry-bar 미검사와는 **재현 의미가 다르다.** 이는 model convention 차이이며 ZEL 코드 버그 판정 아님: ZEL은 시가 체결을 전제로 현재 봉 high/low가 이후 발생한 것으로 모델링할 수 있으나 실제 체결 지연·분할·bid-ask 증거는 아직 없음.
- **기존 승인 K/S 평가의 기록 요건:** `ENTRY_BAR_STOP_FIRST` 구분, `STOP_VS_TARGET_SAME_BAR`, `GAP_OPEN_BELOW_STOP`, `EXIT_NEXT_OPEN_PENDING`, `RECOVERY_WINNER_CUT`의 반례·인과 trace를 바꾸지 않고 수집. 새 도구 설치·손절 튜닝/경제실행 없음. 벤치마크 수익률 비교 시 entry-bar 처리 차이를 숨기지 않는다.

### V03 업데이트 — TraderLion / Linda Raschke, *The Reality of Relative Strength Based Trading*
- **SOURCE_METADATA_ONLY / NOT_FULL_VIEWED:** 공식 YouTube https://www.youtube.com/watch?v=jD4nynuWfEU ; 공개 일자 2023-12-09. 이번 공개 검색 반환 정보에서 **96,638 views**라는 조회 스냅샷과 영상의 설명 내 챕터 타임코드를 확보함. 실제 현행 실시간 조회수와 자막·전편 재생을 독립 재확인한 것은 아니므로 `VIEWS_AT_RETRIEVAL_SNAPSHOT`, `CHAPTER_METADATA_ONLY`로 기록. 이전 V03의 “조회수·타임코드 모두 미확인” 중 **표시 스냅샷·타임코드만 일부 해소**.
- **원문 영상 설명 상의 챕터(시청/내용 보증 아님):** 06:37 시장상태별 momentum vs mean reversion, 18:37 leader/laggard 격차, 20:37 상대강도 스프레드, 23:12 회귀장에서 모멘텀 실패, 31:12 futures에서의 상대강도, 46:48 횡보장에서 모멘텀 실패. 영상 제목·태그·설명은 저자 정량 실험원장 아님.
- **H03 연결:** 같은 강도신호를 추세장/평균회귀장에서 똑같이 해석하면 안 된다는 검증 질문을 강화한다. 다만 영상의 6개월 룩백 홍보 문구를 ZEL 30m 매매 설정으로 이식하지 않음.

## 네 축별 변화와 우선순위
1. **Keltner/HG:** 기존 ADX 단계·상태 누적 문제 H02 유지. 이번엔 전략 원문에서 새로운 확정 버그/임계치를 찾지 않았고 새로운 후보를 만들지 않음. P07은 HG 5봉 청산·3R 러너의 *same-bar/entry-bar* 체결 재현 기준으로만 채택.
2. **Squeeze:** H01 음수 모멘텀 전환은 여전히 가설. P07의 entry-bar/stop-first/next-open 분리 없이는 ‘손실 회피’ 경제치를 낼 수 없다는 구체적 반례 강화. 이미 승인된 signal-low 후속안의 우선순위 불변.
3. **청산·큰 승리:** P07의 stop-first가 보수적이더라도 실제 1분 경로·지연 체결·funding 비용은 불명. 패배한 경우만 조기청산하는 사후 표본 선택 금지. 최대 승리와 회복 승리 보존은 후속 비용후 비교에서 확인.
4. **차트/HTF/공개봇:** V03 영상 챕터 구분과 P05/P06은 **BTC가 언제나 알트코인을 같은 방향으로 선도한다는 단순화의 반대 근거**. 상대강도 스크리닝을 확정 매매신호로 승격하지 않음. 피보나치 수치/캔들 형태만으로 우위를 주장하지 않음.

## 인계 가능 형태 (계획이 아닌 원문-관측 연결)
- **H03 반증 표:** `symbol, market, signal_close_ts, signal_available_ts, btc_close_available_ts, symbol_close_available_ts, last_completed_btc_return, symbol_relative_return, segment/gap, outcome_label(posthoc only), source_hash`. 각 필드는 **신호 당시 사용 가능**한 시각 검증이 선행해야 함. 과거 미래 label은 개별 코인 매매 판단 feature가 아니다.
- **H01/P07 간섭 표:** `entry_ts, entry_bar_stop_witness, first_signal_low_invalidation_ts, first_negative_momentum_available_ts, original_exit_ts, next_open_fill_ts, open_gap, first_precedence_reason, subsequent_occupancy, recovered_winner_flag (posthoc)`. 이것은 **실제 경제실행 결과가 아니라** 원장 확보 후 확인할 관측 요구사항.
- CF/GS 연결 계좌 데이터를 열람하지 않았고, 이 문서로 실주문 또는 자금위험 결정을 하지 않는다. [UNSURE]+HOLD.

## 결론 / 보존
새로운 출처 3건(P05–P07) 및 기존 영상 1건(V03)의 *검증 수준 변경*만 기록. 추가 연구 가설/정식 경제 후보0, 새 native 경제비교0, 실제 수익개선0 **(정확히는 미측정)**. 실제 사용되는 결과 receipt가 없으므로 `ACTUAL_ECONOMIC_RESULT=NOT_RUN`. 후속 예정 Keltner fresh-touch, Squeeze signal-low 순서는 변경하지 않는다. 외부 AI/API/시장데이터 호출·주문/배포·과금0. 경제 owner·claim/consumption/원형 전략·workflow/비용 원장 불변. 현재 연구 브랜치 외 저장소 변이 없음.
