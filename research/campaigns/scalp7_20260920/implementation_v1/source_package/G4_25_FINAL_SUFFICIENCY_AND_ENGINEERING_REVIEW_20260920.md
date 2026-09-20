# G4 원래 25개 — 최종 충분성 재검토·경제/구현 보강

기준일: **2026-09-20**  
검토 대상: R1/R2/R3 통합자료의 원래 **25개**, **19개 원 모드 카드**, 공개 성과의 귀속·한계.  
현재 프로젝트 코드·CF/GS·서비스를 새로 감사하거나 경제실험한 결과는 아니다.

## 1. 최종 판단

**R3는 원자료 대조와 제한된 기준 구현을 시작할 근거로 사용할 수 있다. 하지만 그 파일만으로 25개 모두의 완성된 원형, 동일한 트레이더 수익 구조, 현재 코인15m/30m 경제성을 인증할 수는 없다.**

이 결론은 같은 자료를 무한히 더 모으자는 뜻이 아니다. 원래25개 각각에서
(1) 지금 사용할 수 있는 근거, (2) 실행 전 반드시 정할 선택, (3) 공개되지 않은 성과,
(4) 실제 자료·체결 지원이 있어야만 가능한 비교를 분리했다.
한 항목이 막혀도 나머지의 근거 있는 검수를 막지 않는다.

이번에는 **R3 문구·연결 범위 2건을 직접 정정**했고, 표현 정리 및 예방 항목을 포함한 6개 검토 기록을 남겼다.
추가 자료는 **26개 URL**이며 R3와 겹치는 2개를 제외하면 **24개 추가 URL**이다.
이 숫자는 검증된 전략·수익률·코드 통과 수가 아니다.

문서의 ‘충분’은 아래 구체적 사용 범위에 한정된다.
**자료가 있는 것 / 구현이 원문과 맞는 것 / 현재 시장에서 수익이 나는 것 / 합성재료로 기여하는 것**은 별개다.
트레이더의 완전한 비공개 거래원장 미확보가 모든 유용한 연구를 막지는 않지만, 그런 원장 없이 특정 패턴의 검증수익을 주장하지 않는다.

### 전체25개 분류 — 연구 준비상태, SSOT 등급 아님

| 연구 사용 범위 | 개수 | 의미 |
| --- | --- | --- |
| 사례 명세 검사 | 13 | 원 사례·규칙을 코드와 대조할 수 있음; 정성적 선택·위험·청산 공백은 별도 |
| 기술부품 검사 | 5 | 산식·상태·역할을 검수할 수 있음; standalone 수익 인증 아님 |
| 알고리즘 기준 검사 | 3 | 명시된 원 알고리즘과 대조; Rider의 Noise-Area는 대체 모델, Turtle은 원 daily 범위 |
| 제약 선검수 | 3 | FVG의 사례/성과 한계, R-Breaker의 원형 한계, Grid의 코드·상품 제약 |
| 구성 선검증 | 1 | alpha_combo: 각 구성부터 검증하고 기여를 비교 |


## 2. R3에서 정정하거나 미리 막아야 할 것

아래는 문서의 실제 문구 정정과 새로운 예방 항목을 구별한 표다. 현재 프로그램에 동일 결함이 있다는 판정은 아니다.

| ID·유형 | 대상 | 정정·최종 기준 | 왜 | 근거 |
| --- | --- | --- | --- | --- |
| C01 R3 문구 정정 | bb_revert · Q13 · R3 trigger | 알림 이후 실제 가격 확인이 필요하다. 일괄적인 ‘당일 거래 금지’는 삭제한다. 완료봉으로 확인한다면 해당 확인봉 종료 이전 체결을 소급하지 않는다. | 원 매뉴얼은 alert와 후속 확인을 구분하지만 하루 전체 대기를 요구하지 않는다. | [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) |
| C02 R3 연결 범위 정정 | range_fade · Raschke Anti | Anti는 범위 안 또는 추세 전환 뒤에도 생기지만 선행 단기 추진과 작은 flag를 필요로 한다. 추진의 재개를 거래하는 모드로 분리하고 Soup·Bollinger III와 섞지 않는다. | ‘횡보 구간에 존재’와 ‘범위 경계에서 무조건 역매매’는 다르다. | [S402](https://lindaraschke.net/faq/) |
| C03 R3 표현 명료화 | alpha_combo | 검증할 구성 모델의 역할 비교. 공개 성과가 있다는 사실과 현재 코인·공통비용에서 그 구성의 경제성이 확인된 것은 별개다. | R3 자체도 구성 성과 미실행이라고 명시하므로 준비 완료로 오독되지 않도록 한다. | R3 자체 미실행·계승 기록 |
| C04 추가 자료 단위 검수 | OI / flow / derivatives context | Quarter-Hour 논문의 OI는 order imbalance 비율이다. 선물 open interest 계약수와 별도 필드로 둔다. | 약자가 같아도 생성 데이터와 단위·해석이 다르다. | [S420](https://arxiv.org/html/2607.09426v2) [S424](https://www.cmegroup.com/education/courses/introduction-to-futures/open-interest) |
| C05 추가 체결 계약 | 조건부 진입 및 15m/30m 의미 | 의사결정 TF는 유지하면서 관측 가능한 세부 체결 자료를 사용한다. 주문 활성화 이전 저가로 손절시키지 않으며, 단순 touch를 전량체결로 간주하지 않는다. | 원 주문의 의미와 공통 엔진의 보수적 가정이 다르면 원형이 아닌 실행 변형이다. | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) |
| C06 기존 한계 보존 | R3 75+10개 검수 사례·19개 카드 | 85개는 설계 사례, 19개는 자료 카드다. 현재 실제 통과·경제실행·재료 채택 여부는 별도 증거로 판정한다. | R3가 명시한 미실행 상태를 유지한다. | R3 자체 미실행·계승 기록 |


### 두 가지 중요한 정정의 의미

**Bollinger III:** 저자 매뉴얼은 알림과 후속 가격 확인을 구분한다. R3가 추가한 ‘알림 당일 거래 금지’는 삭제해야 한다. 그렇다고 아직 완료되지 않은 가격 확인을 과거에 알고 있었던 것처럼 거래하면 안 된다. ‘확인 이후’라는 인과 순서를 코드로 보존한다. [S401]

**Anti:** 저자의 설명에는 범위 안 또는 추세 전환 직후의 작은 flag가 포함되지만, 그 전에 단기 추진이 필요하다. 따라서 이를 범위 경계의 단순 역매매로 축약하지 않는다. Soup와 Bollinger 반전은 다른 모드로 둔다. [S402]

## 3. 벤치마킹 외에 확보한 16개 적용 항목

‘필수’라는 표기는 이번 자료 검토의 구현·측정 권고이며, 새 G 승격 임계치나 새 런타임 정책을 발급한다는 뜻이 아니다.
E07·E08·E15는 **선택형 개선 가설**이다. 모든 전략에 일괄 적용하는 추가 필터가 아니다.

### E01. 원 주문의 의미와 실행 시계 — 구현 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 25개 공통; 특히 HG·Break·FVG·AVWAP |
| 왜 필요한가 | 원문 조건부 가격 도달 주문을 일괄 종가확인/다음 시가로 바꾸면 다른 진입을 평가한다. |
| 프로그램에 넣을 내용 | setup_ts / feature_available_ts / order_submit_ts / ack_ts / fill_ts를 구별. 15m·30m 의사결정은 유지하되 필요한 원 주문의 체결은 관측된 세부봉·틱으로 확인. |
| 실제로 비교할 것 | 원문-compatible 경로와 기존 next-open 경로를 별도 identity로 비교. 관측 부족 봉은 여러 가능한 경로의 불확실성을 표시. |
| 넘으면 안 되는 해석 | 1m 상세봉도 틱 선후를 완전히 알지 못한다. 현재 엔진이 지원하는지부터 확인; 무승인 engine 변경·FULL 재실행 없음. |
| 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) |

### E02. 지정가·미체결·가격 충격 — 구현 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 눌림·FVG·AVWAP·grid·scalp |
| 왜 필요한가 | 가격 접촉=전량 maker 체결 가정은 유리한 허구를 만든다. |
| 프로그램에 넣을 내용 | order_type / post_only / maker_taker / remaining_qty / queue_model / spread / fill_price를 기록. 시장성 limit, 취소, 부분체결을 분리. |
| 실제로 비교할 것 | 실측 또는 명시한 보수적 체결 가정 vs 가격접촉 단순모델의 결과 차이와 미체결 승리/손실을 함께 보고. |
| 넘으면 안 되는 해석 | 실측 호가가 없으면 queue를 사실처럼 복원하지 않는다. 지정가 변경으로 수수료만 낮추고 체결률은 그대로 두지 않음. |
| 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) |

### E03. 수수료·슬리피지·펀딩의 단위 원장 — 구현 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 25개 공통 |
| 왜 필요한가 | 원 트레이더의 주당 비용·옵션 수익·현물 재고를 같은 선물 bps로 취급하면 경제비교가 달라진다. |
| 프로그램에 넣을 내용 | 체결별 명목과 실제 요율, 가격오차, 정산별 signed funding, 계약승수·반올림을 원장에 결속. gross_ref−execution_drag−fees−funding=net을 검산. |
| 실제로 비교할 것 | 기존 bound 비용과 새 실제 비용의 차이를 공개; cost/initial-risk 연속값을 진단하되 임의 문턱으로 신호를 지우지 않음. |
| 넘으면 안 되는 해석 | 체결가 기반 gross에 슬리피지를 다시 차감하지 않는다. 일반 공개 요율은 사용자 과거 요율이 아님. |
| 근거 | [S403](https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule) [S404](https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S406](https://bingx.com/en/support/articles/11263299657103) |

### E04. 거래원천·가격종류·거래량 단위 — 구현 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | volume·VWAP·MFI·OBV·sweep·모든 perp |
| 왜 필요한가 | volume 이름이 같아도 base·quote·contracts·실제 체결량이 다를 수 있다. last·mark·index도 서로 다르다. |
| 프로그램에 넣을 내용 | venue / instrument / contract_size / volume_unit / price_type / raw_ts / receive_ts / revision_hash를 저장. VWAP의 거래가중 원본과 HLC3 근사는 구분. |
| 실제로 비교할 것 | 단위 변환 후 불변성·구간합·원 응답 대조. 데이터 수정 버전이 다르면 결과 재사용 동일성 여부를 표시. |
| 넘으면 안 되는 해석 | 조작성 논문의 숫자를 BingX에 적용하지 않는다. synthetic gap fill로 거래를 만들지 않음. |
| 근거 | [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) |

### E05. 초기화·누적기준·비미래 지표 — 구현 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | HG·GMMA·BB·RSI·MFI·MACD·Supertrend |
| 왜 필요한가 | 같은 이름의 EMA/ATR/RSI도 seed·평활·결측 처리·시작봉 수에 따라 조건이 달라질 수 있다. |
| 프로그램에 넣을 내용 | 원식과 라이브러리의 alpha/seed/adjust/min_periods를 분리. 길이가 다른 동일 prefix 및 갭 전후에서 값뿐 아니라 실제 신호 시각 차이를 검사. |
| 실제로 비교할 것 | 수치 오차와 판정 뒤집힘 개수를 따로 확인. 미발동 분기는 별도 사례로 강제해 검사 범위를 기록. |
| 넘으면 안 되는 해석 | 도구의 마지막 행 비교 또는 no-bias 표시는 전체 경로 인증이 아니다. 현재 설치 버전 검증은 구현 시 수행. |
| 근거 | [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) |

### E06. 정성 패턴의 사건화 — 명세 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | VCP·flag·Kell·FVG·Soup·range |
| 왜 필요한가 | ‘좋은 눌림·유기적 거래량·강한 봉’의 빈칸을 임의 숫자로 채워 원형이라고 부르는 문제가 재발할 수 있다. |
| 프로그램에 넣을 내용 | 선정·추진·수축·trigger·무효화의 관측 순서를 작성. 되돌림/추진 크기·단위시간 참여·기준선 위치는 연속 특징으로 저장하고, source 수치와 해석 수치를 분리. |
| 실제로 비교할 것 | 같은 원문 사례에서 진입·비진입·무효화를 먼저 비교. 모드별 최소 가설만 동결하고 결과 후 기준을 고르지 않음. |
| 넘으면 안 되는 해석 | ‘원저자 전체 계좌가 없다’는 이유로 모든 연구를 막지도 않음. 자체 해석은 명명된 가설이지 완료된 정확 재현이 아님. |
| 근거 | [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) |

### E07. 당시 알 수 있는 종목 선정·시장 상태 — 개선 가설


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | Break·Rider·ribbon·session·volume |
| 왜 필요한가 | 오늘의 승자만 선택하거나 주식 scanner 조건을 고정6코인에 그대로 복사하면 원 전략과 다른 선택효과가 된다. |
| 프로그램에 넣을 내용 | 현재 승인 universe 안에서 당시 유동성·가격추진·동시간 참여를 계산. 상장/폐지·종목정보 기준일을 남기고 원형 scanner의 관측불가 조건은 분리. |
| 실제로 비교할 것 | 기존 고정선정 vs 사전 고정 선정부품; 기회 소실·추가 비용·같은 크기에서의 증분성과를 비교. |
| 넘으면 안 되는 해석 | 새 코인 universe 확대 권한 아님. 과거 전체 결과를 보고 종목/달을 제거하지 않음. |
| 근거 | [S407](https://docs.ccxt.com/docs/manual) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S418](https://www.nber.org/papers/w30783) [S419](https://arxiv.org/abs/2109.12142) |

### E08. 코인 고유 시각·참여 기준 — 개선 가설


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | session·squeeze·Break·vol_spike·OBV |
| 왜 필요한가 | 15분 경계 또는 특정 시간대의 통상적 volume 증가를 새로운 개별 신호로 오인할 수 있다. |
| 프로그램에 넣을 내용 | weekday / hour / minute_phase / funding_event_distance와 과거 같은 시각의 기준량을 저장. 현재 봉을 기준통계에 포함하지 않음. |
| 실제로 비교할 것 | 동일 전략의 phase별 비용·미끄러짐·성과, true phase vs 사전 placebo phase를 진단. 새 필터로 채택할 경우 별도 동결. |
| 넘으면 안 되는 해석 | 2026 논문의 첫10초 예측을 15m 보유 수익으로 바꾸지 않는다. ML-Light를 지금 도입하라는 제안 아님. |
| 근거 | [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) |

### E09. 판단 정확도보다 비용 후 기대값 — 평가 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 25개 공통 |
| 왜 필요한가 | WR가 높아져도 평균 이익 크기가 비용보다 작거나 큰 손실 하나가 크면 순손익은 나빠진다. |
| 프로그램에 넣을 내용 | 완료 episode 기준 WR, gross/T, fee/T, execution_drag/T, funding/T, win/loss 크기, net/T를 함께 산출. |
| 실제로 비교할 것 | 승률 개선·수익 개선·위험 개선을 분리. 종결 거래가 적으면 구간과 집중도도 보고. |
| 넘으면 안 되는 해석 | 양수 기대값을 미리 가정하지 않는다. 비용 전 방향 예측 성과를 실제 전략 수익으로 부르지 않음. |
| 근거 | [S420](https://arxiv.org/html/2607.09426v2) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S408](https://www.freqtrade.io/en/stable/backtesting/) |

### E10. 자본·부분청산·MTM 위험 — 평가 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | Turtle·Kell·grid·alpha 및 부분청산 전략 |
| 왜 필요한가 | 거래 bps 합은 계좌수익이 아니며 부분청산 수를 승리 건수로 세면 WR가 달라진다. |
| 프로그램에 넣을 내용 | decision_id→opportunity_id→position_episode_id→fill_id 계층을 유지. 고정 명목 진단과 같은 초기 위험 비교를 나누고 외부입금 제외 NAV/MTM DD를 별도 계산. |
| 실제로 비교할 것 | 진입·청산 고정 후 size 정책만 별도 비교; 같은 위험·유한 자본·원장의 미완결 손익을 유지. |
| 넘으면 안 되는 해석 | 새 레버리지·켈리·피라미딩 최적화 승인이 아님. 사후 잘된 size만 선택하지 않음. |
| 근거 | [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S422](https://www.nber.org/papers/w22208) [S423](https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/) |

### E11. 신호 품질과 청산 손상을 분해 — 평가 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | HG·Rider·Break·Squeeze·반전 |
| 왜 필요한가 | stop 종료가 많다는 통계만으로 진입이 나쁘다거나 stop을 넓혀야 한다고 결정할 수 없다. |
| 프로그램에 넣을 내용 | 기회별 주문 전제·초기 위험·시간별 진행·실제 stop ratchet·청산 이유를 연결. 신호 이후 가격 경로 분석은 정답표로만 보관. |
| 실제로 비교할 것 | 같은 진입의 관리 비교와 전체 구조 비교를 구분. MFE·회복을 그대로 실현수익으로 계산하지 않음. |
| 넘으면 안 되는 해석 | 손절 정책 논문은 적용 과정에 따라 효과가 다르다는 근거이지 손절을 해제할 이유가 아니다. |
| 근거 | [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) [S408](https://www.freqtrade.io/en/stable/backtesting/) |

### E12. 표본 불확실성·동시손실 군집 — 평가 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 25개 및 모든 결합 |
| 왜 필요한가 | 수백 번의 동시 코인 거래가 수백 개의 독립 사건인 것은 아니다. |
| 프로그램에 넣을 내용 | 시간으로 정렬한 전체 후보 수익 패널을 저장. 동일 시간 블록을 종목 전체에 공동 적용하는 재표본화를 검토하고 WR의 작은 표본 구간은 별도 표시. |
| 실제로 비교할 것 | 원형-child의 paired 차이와 block 민감도를 보고. 단일 winner 제거는 stress이지 관측 삭제가 아님. |
| 넘으면 안 되는 해석 | 공통요인 논문이 지금의 독립표본수를 계산해 주지는 않는다. IID Wilson은 설명용이며 실제 군집 보정의 대체물이 아님. |
| 근거 | [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S420](https://arxiv.org/html/2607.09426v2) |

### E13. 누적 시도·반복 holdout·선택편향 — 평가 필수


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 25개 전체 G4 선별 |
| 왜 필요한가 | 직전4회만 세고 이전 실패·검토 후 규칙 변경을 잊으면 성공 확률을 과장한다. |
| 프로그램에 넣을 내용 | 기존 trial registry에 전체 identity/기간/검토일·source-derived vs 수정형을 연결. 다중시도용 수익 패널과 skew/kurtosis·실질 시도 의존 정보를 준비. |
| 실제로 비교할 것 | 필요 자료가 있으면 DSR/PBO를 보조 진단. 과거에 본 validation/rolling은 계속 개발 이력. |
| 넘으면 안 되는 해석 | 단순 모든25를 독립 N=25로 가정하지 않는다. 새 gate·예산·경제실행을 만들지 않음. |
| 근거 | [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) [S414](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) |

### E14. 재료의 기여·공통요인·점유 — 역할 평가


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | alpha·재료20·공유 추세 신호 |
| 왜 필요한가 | 독립 음수전략이 부품으로도 무가치하다는 뜻은 아니지만 이름만 재료로 남겨도 검증이 아니다. |
| 프로그램에 넣을 내용 | 허용된 P/P+component의 같은시각 입력·자본·비용·점유·부품발동 원인을 보존. 진입 수 감소·cash노출·시장 beta 변화와 증분기여를 구분. |
| 실제로 비교할 것 | 동일 기회 비교 + 전체 시간순 비교 + 동등 노출 참고. 같은시장 방향을 여러 독립 alpha로 중복 집계하지 않음. |
| 넘으면 안 되는 해석 | B×B·host 주입·승격 제한 우회 금지. scope 충돌은 해당 실험만 명시해 분리. |
| 근거 | [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) |

### E15. OI·호가·외부 문맥의 제한적 사용 — 선택 조사


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | liquidity·scalp·vol_spike·Break |
| 왜 필요한가 | OI·체결 방향·호가 사건·청산집계는 같은 정보가 아니다. |
| 프로그램에 넣을 내용 | 실제 provider의 interval·sequence·quantity 의미와 수신시각을 먼저 결속. OI는 가격방향/포지션군을 단독 식별하지 않음. open_interest_contracts와 trade_imbalance_ratio(-1~1)는 별도 키·단위로 저장한다. |
| 실제로 비교할 것 | 데이터가 실제 확보된 동일 사건에서만 부품의 추가정보·지연·비용을 비교. |
| 넘으면 안 되는 해석 | 새 피드 설치·거래소 전환 승인 아님. 미확인 청산총량·합성 L2·사후뉴스 입력 금지. |
| 근거 | [S424](https://www.cmegroup.com/education/courses/introduction-to-futures/open-interest) [S425](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly) [S407](https://docs.ccxt.com/docs/manual) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S420](https://arxiv.org/html/2607.09426v2) |

### E16. 작은 검증·캐시 재사용·범위 통제 — 작업 방식


| 항목 | 내용 |
| --- | --- |
| 적용 대상 | 25개 공통 |
| 왜 필요한가 | 검수 비용을 줄이겠다고 결과를 재활용만 하거나, 반대로 전체 동일 실험을 매번 반복하면 판단이 흐려진다. |
| 프로그램에 넣을 내용 | 유효 원문/규칙/함수/feature/data hash를 결속. 작은 인과·단위·상태 테스트 후 경제실행; 완료 결과는 exact 조건일 때만 재사용. |
| 실제로 비교할 것 | 기존 증거 재사용/정정/미실행을 각25행에 표시. 차이 없는 원장을 새 개선으로 세지 않음. |
| 넘으면 안 되는 해석 | 새 대형 프레임워크·AI 매매·무제한 grid search를 만들지 않는다. 이번은 조사·설계이며 배포/경제실행 미수행. |
| 근거 | [S408](https://www.freqtrade.io/en/stable/backtesting/) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) |


## 4. 추가 조사에서 경제적으로 중요한 발견

### 4.1 방향을 맞히는 것과 돈을 버는 것은 별개다

Kim·Hansen의 2026년 프리프린트는 Binance 6개 무기한계약의 15분 경계 **첫10초** 예측을 다룬다.
부록 A.3의 평균 방향 적중률은 **56.6%**, 평균 비용 전 방향수익은 **0.510bps**다.
이 수치는 실제 체결·호가 대기열·모든 비용을 반영한 순손익이 아니다. 전체 15분 보유 전략의 WR도 아니다.
우리 적용안은 새 ML 전략 추가가 아니라, 모든 후보에서
**방향 적중률 → 움직임 크기 → 실제 체결·비용 후 기대값**을 별도로 표시하는 것이다. [S420]

논문의 `OI`는 **order imbalance** 비율이다.
선물의 미결제약정(open interest)과 약자가 같지만 단위가 다르므로 두 필드를 합치지 않는다. [S420][S424]

### 4.2 신호 TF를 바꾸지 않고 원 주문의 의미를 검수한다

의사결정은15m/30m로 유지할 수 있다. 이미 확정된 조건부 주문의 체결을 검수할 때 실제1m·틱 자료를 쓰는 것은
‘새1분봉 스캘핑 전략’과 다른 문제다. 세부 데이터가 있어도 주문 발동·취소·슬리피지·호가조건을 처리하는 엔진이 있어야 한다.
Freqtrade의 세부TF 기능이나 다른 엔진의 기본 옵션이 원형 resting order를 자동 재현하는 것은 아니다. [S408][S412]

지정가 주문이라는 사실만으로 maker 수수료를 적용하지 않는다.
가격 접촉만으로 전량체결을 가정하지 않으며, 부분체결·잔량·미체결·취소를 보존한다.
hftbacktest도 시장충격을 바꾸지 못하는 replay의 한계와 대기열 모델 의존성을 명시한다. [S406][S411]

### 4.3 BingX 비용은 계정·상품·정산 이벤트와 결속해야 한다

공개 표준 요율을 예시로 사용해도 실제 비교는 당시의 계정·종목·maker/taker 체결별 요율을 사용해야 한다.
BingX는 일반적인8시간 외에 특정 종목의4시간 또는1시간 펀딩 주기를 설명한다.
정산 시각에 보유한 포지션에만 해당 이벤트가 적용된다.
`funding_8h%` 같은 환산 표시 필드가 있다고 모든 종목이8시간 정산인 것으로 계산하지 않는다. [S403][S404]

체결가 gross를 사용하는 원장과 참조가 gross를 사용하는 원장은 다음처럼 분리한다.

```text
방법 A: reference gross - execution drag - fees - signed funding = net
방법 B: actual-fill gross - fees - signed funding = net
```

방법 B의 gross에는 진입·청산 체결가격 차이가 이미 들어가므로,
방법 A의 execution drag를 다시 차감하면 이중계산이다.
이는 새 외부 전략이 아니라 원장의 산술 검수 기준이다.
손익의 mark/index/last/fill 가격도 용도를 나눈다. [S405]

### 4.4 지표 초기값·조회창은 ‘코드가 실행된다’만으로 해결되지 않는다

CCXT는 진행 중 봉과 OHLCV 지연·공백의 한계를 설명하며,
Freqtrade는 recursive-analysis와 lookahead-analysis를 별개로 제공한다.
pandas `ewm`도 adjust·ignore_na·최소관측·초기값 등 선택에 따라 같은 기간 표기라도 값이 달라질 수 있다.
우리 적용안은 **원 버전 수치 대조 + 미래데이터 불변 검사 + 서로 다른 warmup/조회창 검사**를 구분하는 것이다.
AVWAP의 고정 anchor는 조회창을 바꿔도 누적 시작이 같아야 한다. [S407][S409][S410][S426]

### 4.5 추가 지표보다 당시의 종목 선정과 시간·시장 상태가 중요할 수 있다

차트 패턴을 객관적 특징으로 다루는 Lo·Mamaysky·Wang 연구,
암호화폐의 시장·규모·모멘텀 공통요인 연구,
코인 시간대별 변동·거래량 연구는 각각 **정성 패턴의 수치화·공통 노출·시각 효과**를 검토할 근거다.
이 논문들이 현재 BingX 15m/30m의 수익을 입증한 것은 아니다. [S416][S417][S419]

과거 선정 시각의 universe·유동성·상대 참여를 저장하고,
사후 최고 종목을 원래부터 고른 것처럼 하지 않는다.
거래량 자료도 source와 단위가 중요하다. Crypto Wash Trading 연구는 일부 조사대상 거래소에서 보고 volume의 왜곡을 분석한다.
그 결과를 BingX 또는 특정 최신 종목에 확인 없이 적용하지 않는다. [S418]

### 4.6 큰 계좌 수익·낮은 DD를 그대로 전략의 진입 능력이라고 읽지 않는다

위험 정규화·포지션 비중·큰 winner 보유가 전체 계좌 결과에 영향을 줄 수 있다.
변동성 관리의 이점을 보고한 연구와, 다수 equity전략에서 일반적인 표본 밖 우위를 지지하지 않은 후속연구를 함께 확인했다.
따라서 vol sizing을 자동 추가하지 않고 **동일 명목 비교와 동일 초기위험 비교**를 별도로 보고한다. [S422][S423]

Stop-loss 연구도 효과가 원 가격 과정과 기제에 의존함을 다룬다.
이는 현재 stop을 없애라는 뜻이 아니며,
‘더 빠른 청산=개선’ 또는 ‘큰 MFE가 있었으니 그만큼 벌 수 있었다’라는 해석을 막는 근거다. [S421]

### 4.7 승률 표본과 누적 연구 시도를 숨기지 않는다

독립 Bernoulli라는 단순 가정에서12승/25거래의48% 승률에 대한 Wilson95% 구간은 약30.0~66.5%다.
이는 통계적 산술 예시이고, 실제 coin거래의 연속·동시 상관을 반영한 신뢰구간이나 승격 기준은 아니다.
실제 경제 차이는 동일 시장 사건을 묶은 paired/time-block 분석으로 확인할 제안이다. [S415]

DSR과 PBO 원 연구를 참고하되 전체 시도 수·수익 시계열·관련성 정보가 없으면 수치를 만들어 계산하지 않는다.
새 배치명으로 바꿔도 이미 본 기간과 실패한 probe의 기록은 남는다.
이러한 통계는 실제 fresh 결과를 대체하지 않는다. [S413][S414]

## 5. 원래25개 전부의 최종 충분성·프로그래밍 표


이 표의 원 수익 기제는 R3에 기록한 원자료 요약을 계승한다. 신규 적용·비교 질문은 이번 연구자의 설계이며 실측 효과가 아니다.


| ID | 근거 사용 범위 | 직접 보완·프로그래밍 | 같은 조건에서 비교할 것 | 실행 전 공백 |
| --- | --- | --- | --- | --- |
| alpha_combo | 구성 선검증: 개별 원 모델 및 결합 비교 설계 | 구성별 episode·실현/미실현 손익·동시 노출을 같은 시계로 결속. | 개별 구성 / 사전 고정 결합 / 한 구성 제거; 동일 자본과 cash 노출 확인. | 실제 구성 경제성·허용된 결합 범위 |
| anchor_vwap_trend | 사례 명세 검사: anchor·인식 시각·재접촉 사례 대조 | anchor_id,anchor_ts,recognized_ts와 base/quote volume 및 주문 제출시각을 저장. | 고정 anchor를 쓴 기준 / 기존 rolling 참조; 입력창 변경 불변성·미체결 포함. | 전체 anchor 선택·종료 규칙과 체결 단위 |
| bb_revert | 사례 명세 검사: 공식 Method III alert→confirmation | alert와 confirmation의 가용시각, 같은 플랫폼 BB·II 계산, 명시한 주문유형. | 알림만 즉시 매수와 source 확인 진입을 구분; 정상 추세 band-walk 승리 훼손. | 가격확인의 수치·SL/TP는 미공개 선택으로 동결 |
| break_and_continue | 사례 명세 검사: Gajjala flag / 별도 ORB 알고리즘 | 당시 선정 사유·추진/수축 구간·계획된 stop-entry 가격·실제 fill 지연. | 선정 효과 / 진입 효과 / 관리 효과를 구분; 같은 기회 및 전체 점유 비교. | 미국 scanner와 코인 universe·조건부 주문 재현 |
| ema_ribbon_scalp | 사례 명세 검사: Kell 단계별 EMA 눌림 | phase,confirmed_pivot_ts,EMA seed,warmup 및 partial-fill episode 연결. | 기존 EMA 정렬 / source 단계 대응; 부족한 size/exit는 별도 가설. | Kell 전체 관리 함수·원 시간축 |
| fvg_revert | 제약 선검수: FVG/MSS 정의·원 자막 | 세 번째 봉 feature_available_ts 뒤 zone 활성화; touch·미체결·부분체결·invalidation 분리. | 원 zone 기하/상태 검사 후 실행 가능 대조; 같은 봉내 진입/stop 순서는 구간으로 표시. | 모든 정성 사례의 대응·위험/종료·resting limit 체결 |
| grid_rebalance | 제약 선검수: DGT 논문·알려진 코드 결함 진단 | 현금·재고·external_flow·grid_level·fill별 fee·MTM을 독립 원장으로 연결. | 코드 논리/현물 source model부터; 유한 자본과 실제 경로 민감도 확인. | 원 코드 정합성·현물과 perp 구조 불일치 |
| keltner_trend | 사례 명세 검사: Raschke 실제 30m Grail 사례 | 최초 자격·이후 EMA 접촉·계획된 고가 stop·무효화·실제 주문 도달시각을 추적. | 원형 보존; source 조건부 진입과 기존 종가확인 차이만 먼저 진단. | 재진입·trailing 명세와 원 주문 지원 |
| liquidity_sweep | 사례 명세 검사: 가격은 Soup; flow는 별도 기술 부품 | 확정 과거 level→침범→복귀를 가격 사건으로; 실측 BBO는 sequence 검증 후 별도 경로. | 가격 단독 / 확보된 flow 부품의 증분정보·지연; 미확보 feed는 미실행. | BBO 단위·순서·실제 queue 및 source 시간축 |
| mfi_rsi_div | 기술부품 검사: 공식 지표·동일 가격 pivot divergence | 동일 pivot_ts의 가격·MFI/RSI,confirmed_at 및 실제 quote/base volume 정규화. | 값 일치 / 신호 변경 / host 위험 부품 기여를 나누어 확인. | 복합부품의 원형 SL/TP·경제 기여 |
| obv_trend | 기술부품 검사: OBV 산식·단계별 volume 역할 | OBV 재귀값과 추진/눌림/재개의 거래량·시각별 참여를 별개 열로 저장. | host / host+OBV; 같은 방향 가격 모멘텀·노출의 중복을 비교. | OBV-only 실수익 근거와 host 기여 |
| pivot_reversal | 사례 명세 검사: Kell 관찰 상태 / 별도 Soup | watch_id·pivot_known_ts·reference_type·실제 trigger/order/fill 상태를 분리. | 실제 source 사례에서 관찰만/진입/실패를 구분; 미래 pivot 확인을 소급하지 않음. | 원형별 위험·목표·정성 pivot 확정 규칙 |
| range_fade | 사례 명세 검사: Soup·Bollinger 반전 / Anti는 별도 | mode=range_reversal와impulse_continuation을 명세상 분리하고 각 reference·목표를 결속. | 원형 모드별 독립 비교; 레인지/추세 라벨을 사후 수익으로 정하지 않음. | 범위 판정·각 모드 실행/관리 가설 |
| rbreaker_like | 제약 선검수: 지정된 community implementation | trading_date/session/DST·전일HLC·고정 level·break/reversal state·EOD를 분리. | 정확히 지정한 구현 검수와 현재 rolling 모델 비교; 경제성과는 새로 필요. | 원저자 전체 위험 규칙·전일 경계·코드 버전 |
| rsi_swing_fail | 기술부품 검사: RSI14 failure swing; R2는 대체 | RSI seed·두 저점/중간 고점·확정시각을 연결; R2를 쓸 경우 일봉 수명 별도. | 기존 oscillator 결과 재사용; host 청산/거절 기여는 source 역할이 있을 때만. | RSI14만으로 미정인 exit·재료 실제 기여 |
| scalp_snap | 사례 명세 검사: flag / Short Skirt 시간축 구분 | setup 지속시간·feature 공개·최초 주문 가능시각·spread/latency를 저장. | 현재15m/30m 범위에서 관측 가능한 사건만 비교; 원1m 모드는 TF부적합으로 별도. | 짧은 원 시간축·실체결자료의 호환성 |
| session_bias | 알고리즘 기준 검사: Noise-Area / ORB source clock | 원시 session/DST와 crypto phase를 따로 정의. 같은시각 기준 통계·펀딩 실제 일정을 결속. | 세션 없는 고정 기준 / source clock / 별도 crypto clock; 실제 추가 기여와 비용. | 코인 clock의 새경제효과·당시 펀딩/선정 |
| squeeze_break | 사례 명세 검사: Carter/TTM의 명시적으로 다른 모드 | compression vs fire source_mode·원 ATR기간·선행문맥·주문 유형·사건 수명을 저장. | 보존 원형 / 명확한 한 모드; 비용 전 확장 규모·늦은 동일 기회·미체결을 분해. | 원 모드별 위험/관리·옵션 payoff와 perp 차이 |
| sr_levels | 사례 명세 검사: Shannon 사건선 / Carter box | reference_type·known_ts·생성 당시 정보·원 box 폭·실패/목표의 동일 수준을 기록. | 기존선 / source선; 무리한25분 scratch와source무효화는 구분해 비교. | box 생성·위험·유효기간 정성 조건 |
| supertrend_pullback | 기술부품 검사: 공식 ATR band와 역할 분리 | ATR/smoothing/초기 band·신호가격 vs stop trigger 가격·다음 적용시각을 결속. | 같은 entry에서 direction 또는 risk 한 역할씩 비교; 실제 체결가 사용. | 독립 진입의 우위·부품의 손실/승리 효과 |
| trend_ma_macd | 기술부품 검사: GMMA / 3–10 SMA / MACD 분리 | 각 식의 alpha/seed·봉기간·feature 시각,가격 동일시점에 연결한 세트별 값. | 기존과 source 정합값 비교 후 host 한 부품 제거/추가; 원형 간 합성 자동금지. | 정의 정확성 이후 실제 부품 경제 기여 |
| trend_rider | 알고리즘 기준 검사: 별도 Noise-Area / Kell 사례 | 시각별 band·VWAP·lagged exposure,그룹별 원 진입/청산과 같은 자본 패널을 저장. | 원시장 로직 검사 / crypto이식 / 기존Rider 전체구조를 별도 표로 비교. | 세션과 코인 자료 변환·노출·trade lifecycle |
| turtle_trend | 알고리즘 기준 검사: 원 System1/2 전체 | 원기간 채널·N 재귀/seed·가상직전돌파·실제 unit fill·위험/상관 한도를 함께 추적. | 원규칙 사례검사와 coin15m/30m번역을 분리. sizing비교는별도권한. | 원 일봉/다시장 범위와현재G4시간축·실계좌자료 |
| vol_spike_fade | 사례 명세 검사: Kell 소진 / Qullamaggie Parabolic | 확장→균열→재시험실패와같은시각평소volume·실제flow의범위를각각저장. | spike관찰 / 완결가격확인 / host청산부품; fat winner훼손과 비용을 분리. | 정성확장·균열기준·현재자료의flow단위 |
| vwap_revert | 사례 명세 검사: Shannon AVWAP 반응; 추세대조별도 | anchor/session/rolling의type·시작시각·인식시각·실제volume·재시험/실패를 분리. | 같은 사건의 지속/회귀 가설; VWAP근사오차·늦은주문·tail/점유를 비교. | 원모드별trigger·무효화·restingfill 및 독립기여 |


### 전략별 적용 이유·출처 연결


#### 01. `alpha_combo`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Noise-Area·ORB·R2 / 검증된 구성의 역할 비교 |
| 원형/대체/부품 관계 | 대응하는 단일 원저자 없음; 별도 구성 모델 |
| R3 수익 기제 | 서로 다른 기회의 수익과 손실 시점이 보완되는지 보며, 거래 수 증가 자체를 alpha로 보지 않는다. |
| 현재 자료로 충분한 것 | 개별 원 모델 및 결합 비교 설계 |
| 정정 또는 예방 검수 | 같은 시장에서 아직 검증되지 않은 구성에 ‘검증된 구성’이라는 표현을 쓰지 않는다. |
| 추가 적용 항목 | E10 · E12 · E13 · E14 |
| 추가 근거 | [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S422](https://www.nber.org/papers/w22208) [S423](https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S420](https://arxiv.org/html/2607.09426v2) [S414](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 02. `anchor_vwap_trend`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Brian Shannon / 사건 고정 AVWAP |
| 원형/대체/부품 관계 | 원저자 역할 대응; 자체 rolling anchor와 비교 |
| R3 수익 기제 | 중요 사건 이후 가격이 평균 원가를 지키거나 회복하는 반응을 추세 진입의 문맥으로 쓴다. |
| 현재 자료로 충분한 것 | anchor·인식 시각·재접촉 사례 대조 |
| 정정 또는 예방 검수 | 원문 저점의 발생과 중요성을 인식한 시각은 다르다. tick VWAP와 봉 근사를 분리한다. |
| 추가 적용 항목 | E01 · E02 · E04 · E06 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 03. `bb_revert`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | John Bollinger / Method III; Connors R2는 별도 대조 |
| 원형/대체/부품 관계 | 공식 반전 알림 대응 / 독립 대체 모델 구분 |
| R3 수익 기제 | 추세를 따라 밴드에 붙는 움직임이 아니라 반전 가능성 알림 뒤 가격 확인을 거래한다. |
| 현재 자료로 충분한 것 | 공식 Method III alert→confirmation |
| 정정 또는 예방 검수 | ‘알림 당일 거래 금지’를 삭제한다. 요구는 알림 뒤 가격 확인이며 임의 하루 대기는 아니다. |
| 추가 적용 항목 | E01 · E05 · E06 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 04. `break_and_continue`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Gajjala 장중 bull flag / Concretum Stocks-in-Play ORB |
| 원형/대체/부품 관계 | 사례 기반 구조와 수치 알고리즘을 서로 다른 기준본으로 사용 |
| R3 수익 기제 | 강한 수요·유동성 종목에서 눌림 중 공급 약화와 재개를 찾는다. ORB는 비정상 참여 종목을 먼저 고른다. |
| 현재 자료로 충분한 것 | Gajjala flag / 별도 ORB 알고리즘 |
| 정정 또는 예방 검수 | VCP 원사례와 세션 ORB를 하나의 rolling20 반등으로 섞지 않는다. |
| 추가 적용 항목 | E01 · E02 · E07 · E08 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S407](https://docs.ccxt.com/docs/manual) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S418](https://www.nber.org/papers/w30783) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 05. `ema_ribbon_scalp`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Oliver Kell / EMA Crossback·Base n’ Break |
| 원형/대체/부품 관계 | 가격행동 단계의 역할 대응; EMA 묶음 산식과 구분 |
| R3 수익 기제 | 큰 추세가 유지되는 중간 조정을 기다리고 가격 확인 뒤 참여한다. extension에서는 부분청산과 위험 조절을 검토한다. |
| 현재 자료로 충분한 것 | Kell 단계별 EMA 눌림 |
| 정정 또는 예방 검수 | 교차를 발견한 시점과 실제 base/pivot 확인은 다르다. |
| 추가 적용 항목 | E01 · E05 · E06 · E10 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S422](https://www.nber.org/papers/w22208) [S423](https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 06. `fvg_revert`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | ICT 2022 Mentorship Episode 6 |
| 원형/대체/부품 관계 | 원 개념/사건 순서 대응; 수익 인증은 제외 |
| R3 수익 기제 | 옛 고저점 침범 이후 구조 전환과 변위가 나타난 구간의 재방문을 거래하고 반대편 가격 목표를 노리는 설명. |
| 현재 자료로 충분한 것 | FVG/MSS 정의·원 자막 |
| 정정 또는 예방 검수 | Paper 시연은 실수익 근거가 아니다. OHLC로 잔량 흡수를 인증하지 않는다. |
| 추가 적용 항목 | E01 · E02 · E04 · E06 · E15 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S424](https://www.cmegroup.com/education/courses/introduction-to-futures/open-interest) [S425](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly) [S420](https://arxiv.org/html/2607.09426v2) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 07. `grid_rebalance`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Chen·Chen·Jang DGT 논문·저자 코드 |
| 원형/대체/부품 관계 | 현재 bounded reversion의 직접 원형이 아닌 별도 재고 모델 |
| R3 수익 기제 | 여러 가격 수준의 사고팔기와 추세 방향 재설정을 결합하며 하락 시 재고를 보유한다. |
| 현재 자료로 충분한 것 | DGT 논문·알려진 코드 결함 진단 |
| 정정 또는 예방 검수 | R2/R3에서 확인한 함수·현금보충·OHLC 경로 문제는 해결됐다는 증거가 없다. |
| 추가 적용 항목 | E02 · E03 · E04 · E10 · E16 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S403](https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule) [S404](https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S422](https://www.nber.org/papers/w22208) [S423](https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 08. `keltner_trend`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Linda Raschke / Holy Grail 1997·2004 |
| 원형/대체/부품 관계 | 원형 계보 대조; 이미 실패한 ADX child 재튜닝 아님 |
| R3 수익 기제 | 강한 새 추진이 보인 뒤 첫 EMA20 눌림을 기다려 추세 재개를 거래한다. |
| 현재 자료로 충분한 것 | Raschke 실제 30m Grail 사례 |
| 정정 또는 예방 검수 | ADX 시간순서만 수선한 실패본을 원형 전체의 FAIL로 확장하지 않는다. |
| 추가 적용 항목 | E01 · E02 · E05 · E06 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 09. `liquidity_sweep`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Connors Turtle Soup / 실제 OFI는 별도 |
| 원형/대체/부품 관계 | 가격 false-break 원형 대조와 미시구조 부품 분리 |
| R3 수익 기제 | Soup는 실패한 새 극값 이후 기존 가격대로 돌아오는 반응을 노린다. OFI는 실제 호가 수급을 측정하는 별개 입력이다. |
| 현재 자료로 충분한 것 | 가격은 Soup; flow는 별도 기술 부품 |
| 정정 또는 예방 검수 | 가격 sweep와 호가 소진은 동일하지 않다. OI·체결량·잔량 사건을 합치지 않는다. |
| 추가 적용 항목 | E01 · E04 · E06 · E15 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S424](https://www.cmegroup.com/education/courses/introduction-to-futures/open-interest) [S425](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S420](https://arxiv.org/html/2607.09426v2) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 10. `mfi_rsi_div`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Fidelity RSI/MFI 정의; Bollinger Method II는 별도 역할 |
| 원형/대체/부품 관계 | 기술 패턴 원형과 거래량 확인 부품 구분 |
| R3 수익 기제 | 가격의 새 극값을 자금 흐름/oscillator가 확인하지 않는 상태를 반전·위험 보조 정보로 평가한다. |
| 현재 자료로 충분한 것 | 공식 지표·동일 가격 pivot divergence |
| 정정 또는 예방 검수 | 한 봉 기울기와 두 pivot divergence를 바꾸어 부르지 않는다. |
| 추가 적용 항목 | E04 · E05 · E06 · E14 |
| 추가 근거 | [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 11. `obv_trend`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | OBV 정의 / Gajjala의 volume 단계 |
| 원형/대체/부품 관계 | 지표 계산과 사례의 거래량 문맥을 분리 |
| R3 수익 기제 | 상승 추진의 참여 증가와 눌림의 공급 감소를 구분해 가격 패턴의 질을 확인하는 부품을 노린다. |
| 현재 자료로 충분한 것 | OBV 산식·단계별 volume 역할 |
| 정정 또는 예방 검수 | 계산이 맞는 OBV를 다시 고치는 대신 이 feature가 추가하는 정보를 검사한다. |
| 추가 적용 항목 | E04 · E07 · E08 · E14 |
| 추가 근거 | [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 12. `pivot_reversal`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Kell Reversal Extension / Connors Turtle Soup |
| 원형/대체/부품 관계 | 확정 swing 반전과 전일 pivot 산식을 별개로 취급 |
| R3 수익 기제 | 추세가 약해지고 확인된 가격 구조가 바뀌는 경우만 반전의 위험 대비 여지를 평가한다. |
| 현재 자료로 충분한 것 | Kell 관찰 상태 / 별도 Soup |
| 정정 또는 예방 검수 | 잠재 반전 관찰을 주문으로 바꾸지 않는다. swing pivot과 세션 산술 pivot도 분리. |
| 추가 적용 항목 | E01 · E05 · E06 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 13. `range_fade`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Raschke Anti / Connors false-break / Bollinger III |
| 원형/대체/부품 관계 | 모드별 원형 대조; R2와 range는 별개 |
| R3 수익 기제 | 겹치는 가격 범위에서 실패한 방향 시도가 다시 범위로 돌아오는 움직임을 노린다. |
| 현재 자료로 충분한 것 | Soup·Bollinger 반전 / Anti는 별도 |
| 정정 또는 예방 검수 | Anti는 선행 impulse 뒤 작은 flag 재개다. 단순 range 경계 반전 원형으로 취급하지 않는다. |
| 추가 적용 항목 | E01 · E06 · E09 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S420](https://arxiv.org/html/2607.09426v2) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 14. `rbreaker_like`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Saidenberg 계보 / vn.py 게시자 코드 / ORB는 대체 |
| 원형/대체/부품 관계 | 원저자 인증 미완료; 커뮤니티 구현을 명시한 engineering reference |
| R3 수익 기제 | 세션 전일 가격으로 당일 기준을 정하고 추세 돌파와 반전 실패를 분리하는 구조다. |
| 현재 자료로 충분한 것 | 지정된 community implementation |
| 정정 또는 예방 검수 | 공개 구현은 Saidenberg 원형·성과 인증이 아니다. 상이한 수식의 정답을 임의 선택하지 않는다. |
| 추가 적용 항목 | E01 · E03 · E05 · E08 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S403](https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule) [S404](https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 15. `rsi_swing_fail`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | RSI failure swing / Connors R2·Soup는 별도 |
| 원형/대체/부품 관계 | 직접 정의와 다른 평균회귀 baseline을 분리 |
| R3 수익 기제 | oscillator 구조의 돌파는 반전 확인 부품, R2는 장기 추세 속 극단적 단기 과매도 회귀라는 다른 기제다. |
| 현재 자료로 충분한 것 | RSI14 failure swing; R2는 대체 |
| 정정 또는 예방 검수 | R2의 높은 과거 WR와 현재 RSI14를 같은 시스템으로 합치지 않는다. |
| 추가 적용 항목 | E05 · E06 · E09 · E14 |
| 추가 근거 | [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S420](https://arxiv.org/html/2607.09426v2) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 16. `scalp_snap`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Gajjala bull flag / Cameron momentum / Raschke Short Skirt |
| 원형/대체/부품 관계 | 가격행동 기준; OFI/Rotter 원형 재현이 아님 |
| R3 수익 기제 | 강한 첫 추진이 유지되는 동안 짧은 눌림과 다시 들어오는 참여를 포착하려는 구조다. |
| 현재 자료로 충분한 것 | flag / Short Skirt 시간축 구분 |
| 정정 또는 예방 검수 | 2–10분에 끝난 사례를 15m 종가로 소급 진입하지 않는다. |
| 추가 적용 항목 | E01 · E02 · E08 · E09 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 17. `session_bias`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Concretum ORB·Noise-Area / Qullamaggie EP |
| 원형/대체/부품 관계 | 명시된 session 알고리즘과 뉴스 재평가 모드를 분리 |
| R3 수익 기제 | 같은 시간대 정상 변동 대비 이례적인 참여와 가격 진행을 비교한다. |
| 현재 자료로 충분한 것 | Noise-Area / ORB source clock |
| 정정 또는 예방 검수 | NYSE 개장 효과를 임의 UTC 시간 제외로 옮기지 않는다. |
| 추가 적용 항목 | E03 · E04 · E07 · E08 |
| 추가 근거 | [S403](https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule) [S404](https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S406](https://bingx.com/en/support/articles/11263299657103) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 18. `squeeze_break`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Carter 일반 TTM / 구체적 옵션 playbook |
| 원형/대체/부품 관계 | 서로 다른 모드를 고정하고 기존 High2 변형과 비교 |
| R3 수익 기제 | 압축 중 좋은 위치 또는 압축 해제 확장에 참여하고, 옵션 모드는 시간가치·delta와 부분청산까지 수익 구조에 포함한다. |
| 현재 자료로 충분한 것 | Carter/TTM의 명시적으로 다른 모드 |
| 정정 또는 예방 검수 | 옵션 theta 시간손절과 선물 봉수, 최초 진입과 High2 대체를 다시 혼합하지 않는다. |
| 추가 적용 항목 | E01 · E02 · E03 · E08 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S403](https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule) [S404](https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 19. `sr_levels`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Shannon AVWAP / Carter Box / 명시된 session levels |
| 원형/대체/부품 관계 | 문맥·risk 부품 대응; 모든 선을 같은 SR로 합치지 않음 |
| R3 수익 기제 | 원인 있는 수준에 대한 반응을 진입/유지/실패 판단에 사용하고 같은 기준으로 risk와 목표를 연결한다. |
| 현재 자료로 충분한 것 | Shannon 사건선 / Carter box |
| 정정 또는 예방 검수 | 어느 선이 진짜 지지인가와 코드의 참조 버그 수선은 다른 문제다. |
| 추가 적용 항목 | E01 · E04 · E06 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 20. `supertrend_pullback`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | 공식 Supertrend / 역할 제거 비교 |
| 원형/대체/부품 관계 | 지표 원형과 자체 pullback 진입을 분리 |
| R3 수익 기제 | 추세 방향과 가격이 넘지 말아야 할 추적 수준을 제공하는 부품이며 그 자체가 수익을 입증한 전략은 아니다. |
| 현재 자료로 충분한 것 | 공식 ATR band와 역할 분리 |
| 정정 또는 예방 검수 | native trail은 이미 존재한다. 새로운 trailing의 이름만 바꿔 반복하지 않는다. |
| 추가 적용 항목 | E03 · E05 · E11 · E14 |
| 추가 근거 | [S403](https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule) [S404](https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S406](https://bingx.com/en/support/articles/11263299657103) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 21. `trend_ma_macd`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Raschke 3–10 SMA / Guppy GMMA / 표준 MACD 별도 |
| 원형/대체/부품 관계 | 서로 다른 지표 원형을 구분한 부품 검증 |
| R3 수익 기제 | 빠른 추진의 새 모멘텀과 느린 추세 상태를 구별해 눌림·재개의 문맥을 읽는 역할을 노린다. |
| 현재 자료로 충분한 것 | GMMA / 3–10 SMA / MACD 분리 |
| 정정 또는 예방 검수 | 지표 이름의 혼용과 같은 모멘텀의 중복 투표를 분리한다. |
| 추가 적용 항목 | E05 · E06 · E13 · E14 |
| 추가 근거 | [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) [S414](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S408](https://www.freqtrade.io/en/stable/backtesting/) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 22. `trend_rider`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Kell·Gajjala 사례 / Concretum Noise-Area는 대체 baseline |
| 원형/대체/부품 관계 | 현재 GMMA 변형과 별개의 외부 수익 구조 비교 |
| R3 수익 기제 | Kell/Gajjala는 좋은 종목·눌림의 재개를 선택한다. Noise-Area는 정상 변동 밖의 추세와 VWAP/밴드 유지로 수익을 노린다. |
| 현재 자료로 충분한 것 | 별도 Noise-Area / Kell 사례 |
| 정정 또는 예방 검수 | 새 Noise-Area는 GMMA 원형이 아니라 대체 모델이다. 현재 GMMA 실패 재시험 금지. |
| 추가 적용 항목 | E01 · E05 · E07 · E09 · E10 · E13 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S407](https://docs.ccxt.com/docs/manual) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S418](https://www.nber.org/papers/w30783) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S422](https://www.nber.org/papers/w22208) [S423](https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) [S414](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 23. `turtle_trend`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Dennis·Eckhardt / 공개 Original Turtle Rules |
| 원형/대체/부품 관계 | 완전 원 시스템의 의미 대응; 짧은 TF port는 별도 |
| R3 수익 기제 | 빈번한 작은 손실보다 드문 긴 추세의 큰 이익을 얻는 구조이며 위험 단위·다시장 분산이 함께 정의돼 있다. |
| 현재 자료로 충분한 것 | 원 System1/2 전체 |
| 정정 또는 예방 검수 | 20일을20개30m봉으로 바꾸거나 N·추가입력을 제거한 결과가 원형 전체가 아니다. |
| 추가 적용 항목 | E01 · E05 · E10 · E12 · E13 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S409](https://www.freqtrade.io/en/stable/lookahead-analysis/) [S410](https://www.freqtrade.io/en/stable/recursive-analysis/) [S426](https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S422](https://www.nber.org/papers/w22208) [S423](https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/) [S413](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) [S415](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) [S417](https://economics.yale.edu/research/common-risk-factors-cryptocurrency) [S420](https://arxiv.org/html/2607.09426v2) [S414](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 24. `vol_spike_fade`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Kell Exhaustion / Qullamaggie Parabolic Short |
| 원형/대체/부품 관계 | 거래량 spike 자체가 아닌 단계·실패 확인 기준 |
| R3 수익 기제 | 너무 확장된 움직임에서 상승 추진이 실제로 꺾이고 회복 시도가 실패하는 반전을 노린다. |
| 현재 자료로 충분한 것 | Kell 소진 / Qullamaggie Parabolic |
| 정정 또는 예방 검수 | 큰 volume만으로 반전을 확정하지 않는다. 시계상 정상 burst를 소진이라 하지 않는다. |
| 추가 적용 항목 | E04 · E06 · E08 · E11 · E15 |
| 추가 근거 | [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S419](https://arxiv.org/abs/2109.12142) [S420](https://arxiv.org/html/2607.09426v2) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S424](https://www.cmegroup.com/education/courses/introduction-to-futures/open-interest) [S425](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


#### 25. `vwap_revert`


| 항목 | 최종 검토 |
| --- | --- |
| R3 벤치마크 | Shannon AVWAP / Qullamaggie VWAP 실패; Noise-Area는 반대 추세 대조 |
| 원형/대체/부품 관계 | 동일 지표의 회귀와 지속 추세 모드 구분 |
| R3 수익 기제 | 고정된 원가 수준의 회복 실패/재시험을 보거나, 반대로 강한 추세에서 VWAP가 지지하는지 구별한다. |
| 현재 자료로 충분한 것 | Shannon AVWAP 반응; 추세대조별도 |
| 정정 또는 예방 검수 | VWAP위 지속 추세의 논문수익을 평균회귀의 근거로 상속하지 않는다. |
| 추가 적용 항목 | E01 · E02 · E04 · E06 · E11 |
| 추가 근거 | [S406](https://bingx.com/en/support/articles/11263299657103) [S408](https://www.freqtrade.io/en/stable/backtesting/) [S412](https://hftbacktest.readthedocs.io/en/latest/latency_models.html) [S411](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) [S407](https://docs.ccxt.com/docs/manual) [S418](https://www.nber.org/papers/w30783) [S405](https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price) [S416](https://www.nber.org/papers/w7613) [S401](https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf) [S402](https://lindaraschke.net/faq/) [S421](https://doi.org/10.1016/J.FINMAR.2013.07.001) |
| 현재 저장소 영향 확인 | 이번에는 미검사. 해당 기능이 없다고 단정하지 않음 |
| 경제실행/채택 | 이번 조사에서 미실행 / 없음 |


## 6. 19개 원 모드의 최종 사용 범위


| ID | 모드 | 원 범위 | 이번 검사 | 남은 공백 |
| --- | --- | --- | --- | --- |
| Q01 | Gajjala 장중 flag | 미국 주식 5m/15m | Gajjala 5m/15m 사건·실제 시장가 시각 | 정성적 demand/organic와 모든 규모·청산은 미공개 |
| Q02 | Carter 옵션 squeeze | daily/weekly 옵션 | 옵션 theta·거래일·daily ATR | perp에는 옵션 손익/3거래일 관리가 그대로 적용되지 않음 |
| Q03 | Kell 관찰→실제 진입 | 다중 TF 주식; ARM/반례 | Kell watch와 실제 pivot entry·관리 | 모든 phase 수치와 체결 비중 미공개 |
| Q04 | Qullamaggie breakout | 주식 swing, ORH 실행 | Qulla 원 daily 구조·ORH 체결 | 15m 봉수 치환은 다른 모델; 현재 대상과 시간축 다름 |
| Q05 | Qullamaggie EP | 주식 이벤트 재평가 | EP 뉴스 first_seen·개장 RVOL | 코인 session/catalyst 번역 및 데이터 가용성 |
| Q06 | Qullamaggie parabolic short | 주식 급확장 이후 | 확장·첫 균열·재시험 실패 | 원 주식 borrow와 perp 위험은 다름 |
| Q07 | Turtle Soup | 20일 극값·당일 실행 | Soup 전일 극값·조건부 주문·취소 | daily·tick 원 단위와 intraday 이식 차이 |
| Q08 | ICT FVG/MSS | 15m 문맥·1~5m 세부 | FVG 확정 시각·사건 순서 | 전체 차트좌표·정성 변위·실계좌 성과 미확인 |
| Q09 | Noise-Area | SPY NY session·30분 결정 | Noise-Area lagged exposure·공통시각 | 원시장 재현·현재crypto이식·코드조각 차이 |
| Q10 | Stocks-in-Play ORB | US 5/15/30/60m opening range | ORB 당시 RVOL·stop entry·EOD | 주식 universe·ATR위험과 코인시장 차이 |
| Q11 | Holy Grail | 원1997/2004,30m사례존재 | HG 자격·first touch·조건부trigger | 모든 expiry/trail·원가격 경로 없음 |
| Q12 | Bollinger I | TradeStation2021 | BB I source version·압축/alert | SL/TP·전체 수익system은 미공개 |
| Q13 | Bollinger II/III 구분 | TradeStation2021 | BB III alert→후속확인; II와 다른 feature | 일괄 당일 금지 삭제; confirmation/SL/TP 수치 선택 남음 |
| Q14 | Bollinger IV 버전 비교 | TS2021/eSignal | BB IV TS/eSignal 별도정의 | 같은 이름으로 두버전조건 혼합 금지 |
| Q15 | Shannon AVWAP | 사건기반가격/거래량 | AVWAP event/known·누적원가 | 일관된 anchor자동선정·전체관리 미공개 |
| Q16 | Turtle 전체 구조 | 원daily다시장 | Turtle System1/2·N·실제fill | 장기 다시장과 현재 intraday는 별도 |
| Q17 | DGT code 연구 | BTC/ETH spot | DGT cash/inventory·호출정합 | 선택된 코드결함·유한자본·OHLC경로 문제 |
| Q18 | R-Breaker 구현 참조 | 커뮤니티session/day | R-Breaker session·전일level·OCO | 원저자 전체규칙·수익인증 아님 |
| Q19 | OFI 기술 부품 | 실측BBO/호가사건 | OFI 최우선호가 가격·잔량·순서 | 거래trigger·경제수익은 논문이 주지 않음 |


## 7. 비교 결과에 붙일 측정 계약


| ID | 영역 | 단위·분모 | 계산/검수 | 오독 방지 |
| --- | --- | --- | --- | --- |
| K01 | 입력·결정 시각 | UTC ms / 각 feature·주문 | 가용시각 ≤ 결정시각 ≤ 주문시각 ≤ 체결시각. 사건 발생시각과 입수시각은 별도. | 미래 봉의 정보를 과거 주문에 사용 |
| K02 | 완료 T·WR | 건 / % / 동결한 에피소드 정의 | 부분체결·부분청산 건수와 매매 건수를 구분. 0손익 처리도 미리 고정. | fill 수를 T로 세거나 일별 hit를 거래 WR로 사용 |
| K03 | Gross·Net | USDT, bps / 같은 계약수·명목 기준 | 실체결가 gross에서 슬리피지를 다시 차감하지 않는다. 수수료·signed funding은 별도. | 집계 기준을 섞어 execution drag 이중 차감 |
| K04 | 거래비용 | USDT, bps / 체결별 당시 명목 | 메이커/테이커·계정/종목별율, 주문수량, 당시 스프레드와 체결가를 보존. | 지정가는 무조건 maker·touch는 전량체결 |
| K05 | 펀딩 | USDT, %/정산 / 정산 당시 포지션가치 | 심볼별 1h/4h/8h 등 실제 일정·rate·보유 여부. 8h 환산 표시와 실제 일정 분리. | 전 종목 일률 8h 또는 미래 확정 rate를 과거에 사용 |
| K06 | 자본·평가 DD | USDT, % / 고정 초기자본 또는 현금흐름 조정 | 실현·미실현·수수료·펀딩·deposit를 각각 원장화. basis를 지정. | 명목 bps 합계를 계좌수익률·MTM DD로 변환 |
| K07 | 크기 효과 | USDT·R / 비교 모드별 별도 | 가격신호의 edge와 크기 조절을 분리. 위험한 원저자 규모를 그대로 적용하지 않음. | 큰 계좌수익=높은 WR·좋은 진입이라고 해석 |
| K08 | 기회·점유 | 건·시각 / 같은 경제 사건 | 같은 기회의 진입시각 이동과 독립 추가기회, 뒤 거래 차단을 분리. | 늦게 들어간 동일기회를 신규 alpha로 세기 |
| K09 | 불확실성 | 건·%·분 / 동일시간 블록·종목군 | 승률 CI와 손익/차이의 paired block 불확실성을 분리. 미완결·빈창 표시. | 25T 표본을 확정 WR로 쓰거나 코인6을 독립6표본으로 취급 |
| K10 | 연구 누적시도 | 회 / 캠페인 전체 | 탈락·probe 포함. 데이터 조건 충족시에만 DSR/PBO를 계산하고 기존 OOS 재사용 기록. | 마지막4회만 세고 수백회 탐색 흔적 삭제 |
| K11 | 재료 기여 | ΔNet·ΔDD·ΔT / 같은 입력·risk·execution | 기존 winner 훼손·loser 절감·노출·점유 변화까지 같은 기회로 비교. | standalone 실패=모든 역할 폐기 |
| K12 | 복원/이식 지위 | 범주 / 각 identity | 원형 대응·실행 변형·신규 모델·경제결과를 독립 상태로 저장. | 원저자 성과를 코인15m 결과에 상속 |


## 8. 무엇부터 실행 검수에 사용할 것인가

| 순서 | 목적 | 실제로 필요한 최소 산출물 | 하지 않을 것 |
|---|---|---|---|
| 1 | 원 주문과 엔진 의미 일치 | 필요한 stop/limit/next-open의 가용시각·체결·취소·비용 사례 | 새 엔진 전체 교체·모든 tick 수집을 무조건 선행 |
| 2 | 비교 가능한 손익 확보 | 단위·가격종류·funding·자본·부분청산·미완결 계약 | research bps를 계좌 수익률로 변환 |
| 3 | 원형 대조 | source 모드별 사례와 미공개 선택을 코드 앞에서 고정 | 자체 선택을 원형 재현으로 포장 |
| 4 | 범위 내 실제 비교 | 동일 조건 기존/원형대응/역할 부품의 경제표와 불확실성 | 수익이 나올 때까지 무제한 숫자 튜닝 |
| 5 | 25개별 판정 | 검증된 것·재료기여·보류 사유·기각할 변형을 개별 기록 | 일부 배치로 전체25 검증 완료 처리 |

이미 있는 기능은 검수 후 재사용한다. 모듈16개를 새 프레임워크16개로 만들지 않는다.
기존 체크포인트·원장·시험·데이터를 활용하되, 이번 연구 때문에 ML-Light·런타임 LLM 직접매매·G5 이후 권한을 앞당기지 않는다.
실제 경제실행은 기존 승인 원장과 SSOT를 확인한 Work가 단일 소유한다.
이 보고서는 새 FULL 실행·유료 API·데이터구매·서비스 변경·배포·주문·LIVE 권한을 만들지 않는다.

## 9. 추가 출처와 확인 수준

이번 26개 자료만 ‘이번에 확인’으로 표시한다. 기존 R3의71개 중 나머지를 모두 다시 원문 열람한 것으로 계산하지 않는다.
초록·소개 수준 자료는 그렇게 표기한다. 실제 원문 URL 존재·논문 내용·코드 실행·트레이더 수익 인증은 별개다.


### S401 — Bollinger Method III 공식 매뉴얼

- URL: https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf
- 종류: 원저자 매뉴얼
- 확인: 본문·p1 화면 재확인
- 내용: 반전 alert 뒤 가격 확인을 요구한다. 같은 거래일 전체를 금지한다는 조항은 없다.
- 한계: 강한 봉의 수치·완전한 SL/TP는 이 문서만으로 확정되지 않는다.


### S402 — Raschke 공식 FAQ

- URL: https://lindaraschke.net/faq/
- 종류: 원저자 설명
- 확인: Anti·Short Skirt·Grail·Breakout Mode 항목 재확인
- 내용: Anti는 범위 안 또는 추세 반전 뒤에도 나타나지만 선행 단기 impulse가 필수인 작은 flag형 구조다.
- 한계: Anti를 범위 경계 무조건 역매매로 정의하지 않는다. 정성 조건의 수치화는 별도 가설.


### S403 — BingX Perpetual Futures Fee Schedule

- URL: https://bingxservice.zendesk.com/hc/en-001/articles/11263240298255-Perpetual-Futures-Fee-Schedule
- 종류: 거래소 공식
- 확인: 2025-09-17 갱신 수수료·정산 설명
- 내용: 공개 일반 요율은 taker 0.05%, maker 0.02%이며 VIP 차이가 있다.
- 한계: 사용자 실제·역사 수수료 확인 아님. 현재 공개 요율로 기존 비용 원장을 덮어쓰지 않는다.


### S404 — BingX Funding Rate Mechanism

- URL: https://bingxservice.zendesk.com/hc/en-001/articles/14857605906575--Notice-Perpetual-Futures-Funding-Rate-Mechanism-Explained
- 종류: 거래소 공식
- 확인: 2026-01-15 개정 본문 §2·§4
- 내용: 8시간 외 4시간·1시간 정산 가능. 정산 시 보유 명목과 해당 펀딩률로 비용/수입이 정해진다.
- 한계: 각 코인의 당시 실제 interval·정산 영수증을 필요로 한다. funding_8h 지표와 실제 부과 스케줄은 별개.


### S405 — BingX Mark Price & Index Price

- URL: https://bingxservice.zendesk.com/hc/en-001/articles/11263299451023-Perpetual-Futures-Mark-Price-Index-Price
- 종류: 거래소 공식
- 확인: mark와 실현 PnL 설명
- 내용: Mark는 청산·미실현 손익의 기준 중 하나이고 실현손익은 실제 체결가격에 근거한다.
- 한계: Mark로 신호를 판단했다고 Mark에서 체결됐다고 계산하지 않는다.


### S406 — BingX Perpetual Order Types

- URL: https://bingx.com/en/support/articles/11263299657103
- 종류: 거래소 공식
- 확인: limit·post-only·trigger·TP/SL 항목
- 내용: 시장성 지정가는 taker가 될 수 있고 post-only는 즉시 매칭 시 취소된다. TP/SL 트리거 가격종류와 주문가격은 다르다.
- 한계: 일반 TP/SL의 트리거 도달이 동일가격 체결 보장은 아니다. 상품별 실제 주문 응답 우선.


### S407 — CCXT Manual

- URL: https://docs.ccxt.com/docs/manual
- 종류: 공식 라이브러리 문서
- 확인: OHLCV 누락·현재봉·since·시장 메타데이터 절
- 내용: 미완료 마지막 봉과 실제 거래가 없어 빠진 구간이 존재할 수 있다.
- 한계: 가용시각·거래소 응답 원문·단위를 별도로 검증한다. 누락을 자동 체결이나 가격 경로로 만들지 않는다.


### S408 — Freqtrade Backtesting

- URL: https://www.freqtrade.io/en/stable/backtesting/
- 종류: 공식 엔진 문서
- 확인: Assumptions·Improved accuracy·limits·wallet metrics
- 내용: 봉내 선후관계·가격범위 내 체결·슬리피지 등에 가정이 있다. 결정 TF와 더 작은 체결 상세 TF를 구분할 수 있다.
- 한계: 참고 엔진 설명이지 ZEL 결함 판정이 아님. detail 옵션만으로 원문의 resting stop/limit이 자동 재현되지는 않는다.


### S409 — Freqtrade Lookahead Analysis

- URL: https://www.freqtrade.io/en/stable/lookahead-analysis/
- 종류: 공식 검증 도구
- 확인: 작동방식·Caveats
- 내용: 검사 중 발동한 신호만 검증하며 미발동 분기는 검증되지 않을 수 있다. 기본 market 강제는 limit callback을 검사하지 않는다.
- 한계: 무편향 표시 하나로 모든 경로 PASS를 선언하지 않는다.


### S410 — Freqtrade Recursive Analysis

- URL: https://www.freqtrade.io/en/stable/recursive-analysis/
- 종류: 공식 검증 도구
- 확인: 출력·제약 절
- 내용: 시작봉 수별 마지막 행 지표값 차이를 비교한다. 그 차이가 실제 진입·청산을 바꾸는지는 별도다.
- 한계: 0% 표시가 모든 시점 동일성과 경제적 무영향을 뜻하지 않는다.


### S411 — HftBacktest Order Fill

- URL: https://hftbacktest.readthedocs.io/en/latest/order_fill.html
- 종류: 공식 엔진 문서
- 확인: 전체 fill·queue 모델
- 내용: 재생으로 호가가 변하지 않는 가정과 queue 추정 한계가 있다. 가격 접촉만으로 대기 지정가의 전량 체결을 확정할 수 없다.
- 한계: Market-by-price 데이터에서 자기 주문의 실제 queue는 관측되지 않는다. 고빈도 엔진으로 갈아타라는 지시 아님.


### S412 — HftBacktest Latency Models

- URL: https://hftbacktest.readthedocs.io/en/latest/latency_models.html
- 종류: 공식 엔진 문서
- 확인: feed·entry·response 모델
- 내용: 피드 지연, 주문 도달 지연, 응답 지연을 분리한다.
- 한계: 실측 없는 latency를 0ms 실제 관측이라고 적지 않는다.


### S413 — Bailey·López de Prado — Deflated Sharpe Ratio

- URL: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- 종류: 원저자 논문
- 확인: 선택편향·반복 holdout·DSR 식, p8 화면
- 내용: 다중시도와 비정규성에 따른 성과 과장을 다룬다. 시도수·시도간 의존·표본 및 수익률 분포 정보가 필요하다.
- 한계: DSR은 수익 보증이나 SSOT 대체 gate가 아니다. 자료가 없으면 정확한 값을 만들어 내지 않는다.


### S414 — Bailey 외 — Probability of Backtest Overfitting

- URL: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- 종류: 원저자 논문
- 확인: 정의·IS/OOS 선택·CSCV 절
- 내용: PBO는 IS 최고 선택이 OOS 비교군 중앙값보다 부진할 위험을 평가하는 틀이다.
- 한계: PBO를 미래 손실 확률과 동일시하지 않는다. 과거 기간을 되돌려 새로운 forward로 만드는 방법도 아니다.


### S415 — NIST — 비율 신뢰구간

- URL: https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm
- 종류: 공식 통계 참고
- 확인: Wilson 식·작은 표본 설명
- 내용: 거래 승률의 점추정과 비율 신뢰구간은 다르다.
- 한계: 독립 이항 예시는 거래 군집·다중시도 보정이 아니다. 95%는 설명 예시이며 새 승격기준 아님.


### S416 — Lo·Mamaysky·Wang — Foundations of Technical Analysis

- URL: https://www.nber.org/papers/w7613
- 종류: 원 연구
- 확인: NBER 저자 초록 확인
- 내용: 정성 차트 패턴을 계산적으로 정의하고 조건부 수익분포의 정보성을 시험했다.
- 한계: 미국 일봉 과거 연구이며 특정 코인15m 모델의 비용 후 성과가 아니다. 이번에 논문 전체 알고리즘을 복제하지 않음.


### S417 — Liu·Tsyvinski·Wu — Common Risk Factors in Cryptocurrency

- URL: https://economics.yale.edu/research/common-risk-factors-cryptocurrency
- 종류: 저자 소속기관 원 논문 소개
- 확인: 저자 초록·출판 정보
- 내용: 시장·크기·모멘텀 공통요인이 여러 암호화폐 전략 수익을 설명하는 연구다.
- 한계: 현재 여섯 코인의 15m 회귀계수나 새 alpha를 추정한 자료는 아니다.


### S418 — Cong 외 — Crypto Wash Trading

- URL: https://www.nber.org/papers/w30783
- 종류: 원 연구
- 확인: NBER 저자 초록·출판 정보
- 내용: 29개 거래소 표본에서 일부 거래량의 조작성과 시장별 품질 문제를 연구했다.
- 한계: 논문의 평균70% 추정치를 오늘의 BingX나 우리 거래량에 적용하지 않는다. 해당 feed를 부정거래로 단정할 근거 아님.


### S419 — Hansen·Kim·Kimbrough — Crypto Volatility/Liquidity Periodicity

- URL: https://arxiv.org/abs/2109.12142
- 종류: 원 연구 프리프린트
- 확인: v2 저자 초록·범위
- 내용: BTC·ETH의 요일·시각·시간 내 거래량·변동성 패턴을 여러 거래소에서 조사했다.
- 한계: 특정 UTC시각을 무조건 매수/금지하는 수익 규칙을 제공하는 것은 아니다.


### S420 — Kim·Hansen — Quarter-Hour Effect

- URL: https://arxiv.org/html/2607.09426v2
- 종류: 2026 원 연구 프리프린트
- 확인: 본문·데이터·예측 정의·A.5 표·공동 block bootstrap
- 내용: 6개 Binance 무기한계약의 15분 경계 첫10초 연구. 표A.3 방향 적중률 평균56.6%, 평균 비용전 방향수익0.510bps. 이 논문의 OI는 공격적 체결량을 정규화한 order imbalance이며 open interest가 아니다.
- 한계: 예측 대상은 미래 VWAP 기반 수익이고 실체결 경제성과가 아니다. 비용·시장 이식·15m 전체 보유 우위를 보장하지 않는다.


### S421 — Kaminski·Lo — When Do Stop-Loss Rules Stop Losses?

- URL: https://doi.org/10.1016/J.FINMAR.2013.07.001
- 종류: 원 연구 저널
- 확인: 출판사 본문 요약·초록·MIT 서지
- 내용: 정해진 stop 정책의 기대효과는 기초 수익과정의 성질에 따라 달라진다.
- 한계: 일별 포트폴리오 노출축소 연구와 15m 개별 구조 stop은 같지 않다. 손절 해제 권고 아님.


### S422 — Moreira·Muir — Volatility Managed Portfolios

- URL: https://www.nber.org/papers/w22208
- 종류: 원 연구
- 확인: 저자 초록·출판 정보
- 내용: 여러 주식·통화 요인에서 변동성에 따른 위험 조절 효과를 보고했다.
- 한계: 원 자산·추정조건 결과를 코인에 상속하지 않는다. 반대 결과 S423과 함께 검토.


### S423 — Cederburg 외 — Volatility-managed portfolio OOS

- URL: https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/
- 종류: 저자 소속기관 원 논문 소개
- 확인: 저자 초록·출판 정보
- 내용: 103개 주식 전략의 실시간/OOS 비교에서 변동성 조절이 일관되게 우월하지 않았음을 보고했다.
- 한계: 규모 조절도 비용·추정오차 포함 별도 평가 대상. 모든 vol targeting 무용론 아님.


### S424 — CME — Open Interest

- URL: https://www.cmegroup.com/education/courses/introduction-to-futures/open-interest
- 종류: 거래소 교육
- 확인: OI·volume 차이·예시 본문
- 내용: 미결제약정과 기간 내 거래량은 다른 측정량이며 OI는 다른 정보와 함께 해석된다.
- 한계: OI증가 자체가 새 롱만의 유입을 식별하지 않는다. 본문의 일별 발표를 코인 API 주기에 복사하지 않음.


### S425 — Binance — Local Order Book Synchronization

- URL: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly
- 종류: 거래소 공식 기술문서
- 확인: snapshot·U/u/pu·재동기화 절
- 내용: snapshot과 update ID를 결속하고 이전 u와 새 pu의 연속성이 끊기면 다시 초기화하는 절차를 명시한다.
- 한계: 기술 참고일 뿐 거래소·데이터 소스를 Binance로 바꾸는 승인이 아니다. BingX에는 해당 API의 실제 필드 계약 적용.


### S426 — pandas Series.ewm

- URL: https://pandas.pydata.org/docs/reference/api/pandas.Series.ewm.html
- 종류: 공식 라이브러리 문서
- 확인: span/alpha/adjust/min_periods/ignore_na 설명
- 내용: EW 계산에는 평활계수·초기화·결측 처리 선택이 있다.
- 한계: 현재 저장소 설치 버전을 확인한 것이 아님. 라이브러리 기본값을 원저자의 산식으로 오인하지 않음.


## 10. 산출물·실제 수행 범위

- 원래25 ID의 중복·누락과19개 모드 카드를 확인하고 R3원본을 보존했다.
- 공개자료를 추가 조사하고 문구/매매모드 연결을 정정했다.
- 표·구조화JSON·산술 예시와 출처 연결을 작성했다. 산술은 가상 예시이며 전략 경제실행이 아니다.
- 신규 전략 코드, 사용자 저장소 변경, 시장 백테스트, 서비스 재시작, 새 Work 자동 시작은 수행하지 않았다.
- 작성한 검수 항목은 실제 통과 테스트로 보고하지 않는다.
- 공개 웹의 전체 원문·유료자료·타인 코드 전문은 재배포하지 않는다. 기존 사용자 대화 산출물과 이번 요약·링크만 묶는다.
- 파일 SHA256은 산출물 무결성 확인이지 원문 주장의 진실성을 증명하는 값이 아니다.

**최종 결론:** 벤치마킹 자료를 더 많이 모으는 것보다, 지금 확보한 원 모드가 실제 주문·체결·비용·위험·표본 기준과 맞는지 확인해야 한다.
이번 표는 원래25개 각각에 그 연결을 제공한다. 알려진 공백을 숨기지 않되, 확보된 근거로 가능한 항목은 더 이상의 전면 재조사 없이 검수·구현으로 진행할 수 있다.
