# Top5 원자료 → 거래 구조 → 현재 코드 대조

**이번 조사의 결론은 수익성 개선이 아니라, 다음에 무엇을 실제로 비교해야 하는지가 달라졌다는 것입니다.** 현재 Keltner·Supertrend 이름만으로 원전 구현을 시험했다고 볼 수 없습니다. 공식 Supertrend 계산 부품과 전환 주문 처리 코드는 이미 존재하므로 새 지표·새 엔진을 만들기보다 정확한 부품과 비용·데이터 경계를 연결하는 편이 타당합니다.

기준 master: `cfb27b90cfa43c2df80297797b75b5c4ff95e350`. PR #1187 이후 변경은 기존 수집·상태 기록 5파일이며 후속 PR은 확인되지 않았습니다. 이 문서 작성 시점의 고정 기준이고 계속 움직이는 master 전체의 영구 상태를 뜻하지 않습니다.

**경제 실측·신호 계산·개발 OHLCV 로드·유료 AI 호출은 모두 0회입니다. 기존 실험은 누적 20건, 신규 배정은 0건입니다.** 실험 제안 2건은 승인이나 사전등록 완료가 아닙니다. 기존 G5B·open intent·boundary·운영본·실패 기록은 보존합니다.

## 1. 원문 확인 수준

| 자료 | 이번에 실제 확인한 범위 | 원문 위치 | 한계 |
|---|---|---|---|
| S1 Hudson–Urquhart | 출판사 공개 본문·PDF, Appendix 이미지 | §2–4·6.3; 인쇄215–218 / PDF index24–27 | 카탈로그 표기·개수 오류가 있어 전체 규칙을 임의 복원하지 않음 |
| S2 Raschke | 공식 PDF 전체 텍스트, 인쇄2·3·4·6 이미지 | Holy Grail 규칙 p.2/index1, 일봉 사례 p.3/index2 | 완전한 주문·swing·trailing 알고리즘은 미정 |
| S3 TradingView | 공식 계산·전략·ATR·엔진 설명, Inputs 이미지 | Calculations / Definition / Inputs / Orders and trades | 공식 지표·엔진 설명과 특정 내장 전략의 실제 설정은 구분 |
| S4 Moskowitz–Ooi–Pedersen | 저자 대학 페이지의 출판 PDF·핵심 페이지 | p.233/index5, 식5 p.236/index8, Fig2 p.237/index9 | 전통 선물·월 단위; 현재 코인 단기 순수익 증거 아님 |
| S5 Shen–Urquhart–Wang | 출판사 초록·대학 저장소 등록 | Wiley abstract, Reading 100181 | 본문 접근 실패. 30분 구조를 1h/4h로 복원 불가 |
| S6 Wen 외 | 저자 Yahua Xu 공개 원고 본문 | §2 pp.7–9, §5 pp.18–20 식8 | 출판본 동일성 미확인; 원고 내부 표본기간 충돌 |

원문 링크·PDF checksum·확인 범위는 [SOURCES.json](SOURCES.json)에 있습니다. S7 펀드/S8 대회 성과는 현재 코드와 동일한 성과가 아니므로 새 후보 선정·수익 주장에 사용하지 않았습니다. S9 Gemini 실제 영상은 `NOT_RUN`입니다. 영상 목록 발견이나 기존 자막 사용을 새 영상 분석으로 표시하지 않습니다.

## 2. 눌림: ADX 필터 하나와 Holy Grail 과정은 다르다

| 항목 | S2에서 확인된 구조 | 현재 Keltner V2 / 이식 시 남는 결정 |
|---|---|---|
| 시장·시간 | 미국 주식 일봉 사례, 숏은 반대 규칙 | 코인 4h 롱은 ZEL 변형 |
| 순서 | ADX14>30·상승 → EMA20 접촉 | 부모는 EMA20>EMA50와 종가 회복만 판단 |
| 주문 | EMA 접촉 후 직전 봉 고가 위 buy-stop | 부모는 다음 봉 시가 진입; stop 가산폭·봉내 순서 미정 |
| 손절 | 체결 후 새 swing low 보호 | 부모 명세에는 별도 SL 없음; swing 확정법 미정 |
| 청산 | 이익 증가에 따라 stop 추적 | 부모는 12봉 종료; trailing 식·최대보유 미정 |
| 무효화·만료 | 정체·상대약세 실패 사례와 재량 설명 | 수치화된 주문 취소·만료·재활성 규칙 미정 |
| sizing·비용 | 완결된 수치 규칙 확인 못함 | 기존 ZEL 비용을 쓰면 ADAPTATION이라고 표시 |

근거: [Raschke 공식 PDF](https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf), 인쇄2–4·6. ADX 하락은 눌림에서 나타나는 설명이며 필수 gate로 추가하지 않습니다. 다른 gap 패턴의 1tick·3일 만료를 가져오지 않습니다. 성공확률 발언을 검증 성과로 사용하지 않습니다.

현재 부모의 전체 진입은 `ema20 > ema50 and lag('close',1) <= lag('ema20',1) and close > ema20`입니다. ADX 상태 확인, stop 주문, swing 보호, trailing을 함께 도입하면 여러 규칙을 바꾸는 구조 이식입니다. **S2만으로 완결된 REFERENCE_SPEC를 선언하지 않고, 확인된 과정과 빈칸을 남깁니다.** Keltner 전체의 개선 가능성을 종료한다는 결론도 아닙니다.

## 3. Supertrend: 계산 부품·전환 전략·현재 부모를 분리

| 항목 | 공식 자료 | 현재 Supertrend V2 / ZEL 선택 |
|---|---|---|
| 계산 | HL2±ATR×배수, 이전 band·이전 종가에 따른 재귀 갱신, 초기 하락 | 현재 부모는 ATR 밴드가 아닌 ret1·retstd20·EMA20/50 |
| 진입·무효화 | 종가 기준 밴드 방향 전환 | 부모는 큰 양의 1봉 수익률; 전환 사건이 아님 |
| 포지션 | 전략 문서는 상승 전환 롱·하락 전환 숏 | 롱→현금은 숏·반전을 생략한 변형 |
| 체결 | 일반 Pine 엔진 기본 시장가 주문은 다음 tick/봉 시가 | 특정 내장 전략 설정 확인과 구분; ZEL은 다음 시가로 명시 가능 |
| 청산·보유 | 반대 전환이 방향 변경의 근거 | 부모의 12봉 time stop은 별도 ZEL 선택 |
| 위험·비용 | sizing·수수료·funding·보호주문·끝부분 처리는 도움말만으로 확정 불가 | DEV 비용·표본 경계·점유는 별도 명세 필요 |

근거: [공식 Calculations](https://www.tradingview.com/support/solutions/43000634738-supertrend/), [Strategy Definition/Inputs](https://www.tradingview.com/support/solutions/43000645068-supertrend-strategy/), [ATR Calculation](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/), [Pine 주문·반전 설명](https://www.tradingview.com/pine-script-docs/concepts/strategies/). Inputs 이미지의 ATR10·배수3은 원문 예시값이며 최적값·운영 위험 임계치가 아닙니다.

실제 V2 규칙은 `abs(ret1) >= 1.5 * retstd20 and ret1 > 0 and ema20 > ema50`입니다. **volume 조건이 없습니다.** 과거 문서 일부의 “high-volume momentum” 표현은 수식과 불일치하며, 해당 과거 문서를 덮어쓰지 않고 이 대조에서 정정합니다.

## 4. Break·TrendRider: 지표 이름보다 신호·포지션의 수명을 비교

| 자료·항목 | 확인된 원형 | 현재 부모와 차이·실행 제한 |
|---|---|---|
| S1 시장·주문·비용 | 일별 암호화폐 자료, 전일 신호로 이후 수익에 −1/0/+1 포지션 적용; 손익분기 비용 평가 | 특정 거래소의 next-open·SL·funding 포함 순수익을 재현한 것은 아님 |
| S1 SR1/SR2 | 이전 종가 극값 돌파·유지 조건, SR2는 k일 뒤 평탄화 | Break는 이전 high50 돌파+EMA+volume, 롱6봉 고정 |
| S1 CB1/CB2 | 좁은 채널이 먼저 형성된 뒤 돌파·유지, CB2는 k기간 종료 | 단순 고점 돌파와 다른 준비 상태. 개수·파라미터 오기를 임의 보정하거나 전체 sweep하지 않음 |
| S1 기타 | MA·filter·oscillator 계열도 구조가 다름 | oscillator의 과매도 후 회복을 단순 수준 veto로 치환하지 않음 |
| S4 신호·포지션 | 12개월 초과수익 부호, 1개월 보유·월별 갱신, 롱/숏 | 현재 1h/4h·단기 보유의 근거로 축약할 수 없음 |
| S4 sizing·비용 | 사전 연율변동성 역비례, 원문 40% 변동성 목표; Fig2 gross Sharpe | ZEL 위험 승인이 아님. 24/7 연율화·체결·funding·net 비용 별도 |

S1 근거: [출판본](https://link.springer.com/article/10.1007/s10479-019-03357-1), Appendix 인쇄215–218. 본문은 filter 세 규칙이라 쓰지만 F1/F2만 제시하며 일부 개수·값에도 불일치가 있습니다. 없는 F3를 만들지 않았습니다. §6.3의 BTC 후속 표본 실패도 보존합니다.

S4 근거: [저자 보관 출판 PDF](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf), §2.4·3.2·4/식5. 58개 전통 선물·선도 시장의 1985–2009 연구입니다. 기존 DEV 약375일은 12개월 준비기간 뒤 충분한 평가기간을 제공하지 않습니다. 기간을 임의 축소하면 새 가설이며 원형 재현이 아닙니다.

현재 Primary/Broad는 native Supertrend·EMA 지속 조건, 비용·위험·점유 정책을 사용하고 Primary에는 전환 freshness와 미국 시간대 추격 완화 조건이 더해집니다. **정책에 trailing 플래그가 있다는 것과 실제 replay가 trailing을 실행한다는 것은 다릅니다.** 현재 `primary_trades()`의 손익 루프는 SL/TP/timeout을 처리합니다. S4 결과나 intent 선언을 현재 실행 성과로 대신하지 않습니다.

## 5. 아직 실행 후보로 바꾸지 않은 자료

- S5: [Wiley](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290)의 full 경로는 초록으로 이동하고 [Reading 원문 등록](https://centaur.reading.ac.uk/100181/)은 접근 제한입니다. 세션 시각·체결·비용을 확인하지 못했습니다. 30분 가격 구조는 현재 1h/4h에서 복원할 수 없습니다.
- S6: [저자 공개 원고](https://www.researchgate.net/publication/361202793_Intraday_return_predictability_in_the_cryptocurrency_markets_momentum_reversal_or_both)는 Bitstamp 5분→GMT 시간별 수익, 선행 수익·추정계수 부호에 따른 다음 시간대 롱/숏과 그 시간 끝 청산을 설명합니다. 명시적 거래비용 차감은 확인 못했습니다. 초록 기간2013-03-03~2020-05-31과 본문/table 기간2013-04-01~2021-05-01이 충돌합니다. 출판본·추정창·시간쌍 선택을 고정하기 전에 조건을 만들지 않습니다.

## 6. 이미 있는 코드와 이미 수행한 실험

| 재사용 대상 | 확인 수준 | 그대로 재사용하면 안 되는 부분 |
|---|---|---|
| `top5_external_features_v1.supertrend/rma` | 공식식에 맞춘 재귀 계산 부품, seed·종가전환·prefix fixture 존재 | TradingView 실제 엔진 전체와 수치 동등성 검증으로 확대 금지 |
| 같은 파일의 `directional_movement` | 기존 ADX 부품 | Holy Grail 주문 상태기계가 아님 |
| `strategy11_supertrend_authentic_child_v1.replay_window` | 전환→예약→다음 시가 반전 처리 구현 | 초기 상승 seed, 15m 자료, 편도 고정비용, WINDOW_END 청산은 현재 원전/DEV와 다름 |
| `top5_development_native_v1.native_replay` | 현재 native 소유권·위험 로직 재사용 | 원 owner 직접 호출은 데이터 확장 가능; DEV 입력 facade 필요 |
| `evaluate_development_events` | 현재 승인 DEV의 고정보유·진입 지연·무결성·점유 계산 | stop-entry나 임의 전환 청산 기능은 없음 |
| `top5_external_repair_v1.load_inputs`와 `top5_development_repair_v1.charge` | 기존 DEV loader·비용/funding·원장 | 신규 슬롯 없이 실행하지 않음; 논문 비용으로 교체하지 않음 |
| 기존 attribution·diagnostics·bootstrap | 공통/제외/새 거래·이익 보존·동시 손실·불확실성 | 계좌수익·독립 표본·개별 조건의 인과효과 주장 금지 |

경로·함수·파일 SHA는 [CODE_MAP.json](CODE_MAP.json)에 있습니다. 같은 모듈의 구형 `evaluate_candidate()`는 별도 자료 fetcher·비용·청산 규칙을 쓰므로 승인 DEV의 공용 진입점으로 혼동하면 안 됩니다.

PR #1181은 공식 ST의 **이전 상승 상태를 Keltner veto**로 이미 실측했습니다. 이것은 현재 Supertrend V2를 flip 전략으로 바꾼 시험이 아닙니다. 당시 Supertrend child는 ADX 상승 조건이었습니다. 기존 외부 자료 활용을 없었다고 지우지 않습니다.

과거 native-line trailing의 87거래 receipt는 다른 부모·세대이며 기존 terminal 결론을 보존합니다. authentic 구현·fixture는 있으나 이번에 조사한 tracked 경로에서 완료 receipt는 찾지 못했습니다. **존재하는 코드, 실행된 코드, 현재 부모에 적용된 코드, 검증된 성과를 따로 표시합니다.** PR #370의 과거 15m 실행과 미병합 PR #556의 계보는 기존 `TOP5_DIVERSITY_PREPARATION_20260906_V1/lineage.json`을 재사용했습니다.

## 7. 다음 실측을 요청한다면: Supertrend 두 단계 한 묶음

**현재 미승인 제안: 2건. 현재 누계20·신규 배정0은 그대로입니다.** 원문에 없는 결정을 숨기지 않은 ZEL ADAPTATION_SPEC입니다. 완결된 원전 전략을 그대로 복제했다는 이름을 붙이지 않습니다.

| 제안 | 고정할 변경 | 비교의 목적 | 요청 실측 |
|---|---|---|---:|
| A: ST flip 진입·기존 hold12 | 현재 급등+EMA 진입을 공식 하락→상승 전환 사건으로 교체, 다음 시가 롱·12봉 종료 유지 | 부모→A: 진입 메커니즘 교체 효과 | 1 |
| B: 같은 flip 진입·반대 flip 청산 | A의 진입 유지, 12봉 종료를 상승→하락 전환 후 다음 시가 청산으로 변경, 숏 없이 현금 | A→B: 청산·보유 구조 효과; 부모→B: 전체 구조 효과 | 1 |

두 cell이 여러 거래 규칙을 바꾸는 전체 구조를 단계적으로 비교합니다. 같은 지표의 threshold를 돌리는 배치가 아닙니다. A는 기여 분리를 위한 중간 비교이지 원전 전체가 아닙니다. B도 4h·롱/현금·ZEL 비용 때문에 원전의 양방향 전략과 다릅니다.

사전 검토 명세는 [EXPERIMENT_BUNDLE.json](EXPERIMENT_BUNDLE.json)입니다. A/B 모두 원래 hold12 거래가 DEV 안에서 끝날 수 있는 동일한 시간 기준으로 신호를 등록합니다. 실제 B의 보유기간이나 미래 가격으로 진입 적격성을 정하지 않습니다. 시간봉 결측은 무결성 실패이며, 정상 시계열의 가격 갭은 관측 시가에 체결합니다.

B가 DEV 끝까지 미완결이면 청산을 만들어내지 않고 검열 표본·평가손익·노출로 따로 보고합니다. 경과한 funding은 기존 모델로 계산하지만, 왕복 비용 바인딩에서 분리되지 않은 진입 비용을 임의로 반으로 나누지 않습니다. 전체 왕복 비용을 뺀 가상 청산 평가액은 실제 누적비용·완결 손익과 별도입니다. 미완결을 숨긴 완결 거래 평균만으로 채택하지 않습니다. 고정 원신호 비교는 모든 A 거래의 B 완결/미완결을 함께 제시하는 반사실 진단이며, 전체 순서 재생은 점유 효과를 포함합니다.

승인 뒤에도 실제 계산 전에 코드·설정·데이터·비용 SHA를 원격에서 고정해야 합니다. source band 계산과 기존 순서 처리 코드를 최소 연결하고, 기존 loader/charge/metrics를 씁니다. 새 로드맵·새 검증기·새 Alpha Factory를 만들지 않습니다. 자동 추가 후보·재시도 확대·결과 후 조건 변경은 없습니다.

Keltner는 S2의 미정 실행 규칙, Break는 S1의 구체적 parameter cell 미선정, Primary/Broad는 S4의 시간 지평·데이터 부족, S5/S6는 자료·버전·추정 규칙 공백으로 이 묶음에 넣지 않았습니다. 이는 해당 lane의 폐기나 연구 전체 종료가 아닙니다.

## 8. 산출물·권한

| 층위 | 이번 상태 |
|---|---|
| 원문 조사·현재 코드 대조 | 완료, 위치·파일 SHA 기록 |
| 원전 전체의 실행 명세 | 미완결 항목 명시; 완전 재현 주장 없음 |
| ZEL 변형 제안 | A/B 두 cell 작성, 미배정·미구현 |
| 새 구현·합성 시험 | 0; 기존 fixture 존재를 확인했으며 이번 재실행하지 않음 |
| 새 경제 실측·모의체결 | NOT_RUN_UNALLOCATED |
| 실제 체결·공식 검증·승격 | 없음; execution=NONE, order/live=BLOCKED |

추가 파일은 이 연구 폴더의 조사·제안 문서뿐입니다. 앱 validate와 JSON·경로·해시 확인은 문서 무결성 검사이며 경제 PASS가 아닙니다. 배포할 앱 변경이 없으므로 GitHub Actions 배포를 실행하지 않습니다. 이 문서는 기존 부모·실패 기록·운영본을 덮어쓰지 않아 연구 문서 변경만 철회할 수 있습니다.
