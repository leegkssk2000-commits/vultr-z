# Kell·Gajjala 선언 연구모델 구현 계약

scope_key: G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1

기존 동결 component를 실제 caller에 연결하여 선별 → 형성 → 진입 → 실패 → 관리 → 유한 계좌를 합성 데이터로 검증했다. 새 역사 데이터 전략 probe·backtest·FULL은 0회이며 경제 결과는 미측정이다. 원래25개·미완료19개 및 이전5회 결과를 변경하거나 전체 완료로 승격하지 않는다.

| 연구모델 | 원래 ID 연결 | 독립 계보 수 | 의미 |
|---|---|---:|---|
| KELL_BASE_BREAK_HTF15_PARTIAL_PIVOT_V1 | ema_ribbon_scalp | 1 | EMA cross watch와 이후 base·확정 pivot 돌파를 구분한 선언 가설 |
| GAJJALA_FLAG15_CRYPTO_PARTIAL_PIVOT_V1 | break_and_continue, scalp_snap | 1 | impulse·저거래량 flag·재개와 부분관리를 연결한 하나의 코인 연구 번역 |

## 원문과 기계적 가설

기존 최종 source package의 Q03/S305·S306 및 Q01/S301만 사용했다. 원문 전수조사를 반복하지 않았다. 원문은 선별·형성·진입·구조적 실패·관리의 순서를 뒷받침한다. 아래 모든 수치와 통일된 관리 방식은 원저자의 완전한 규칙이나 파라미터가 아닌 DECLARED_HYPOTHESIS다. 각 규칙의 출처 종류·문서·단위·버전은 CONTRACT.json에 저장한다.

- 공통 선별: setup origin 시점에 알려진 연속 1시간봉 4개. 종목 close가 4봉 SMA seed EMA보다 높고, 처음 대비 수익률이 양수이며 동시간 benchmark 이상이고, setup low가 4봉 저점 지지 이상이어야 한다. 마지막 context 종료부터 최대 1시간만 허용한다. 이는 원래 미국 주식 scanner·float·halt·거래대금 선별을 재현하지 않는다.
- Kell: 15분 EMA20 cross는 watch만 만든다. 이후 base3봉, watch range 대비 0.5 이내, 엄격한 1L1R 고점 pivot 확정을 거쳐 pivot+가격 tick STOP_MARKET을 낸다. watch8봉 만료. frozen producer 필수인 watch_extension_fraction=0.05는 이 비반전 mode에서 사용되지 않음을 공개한다.
- Gajjala: 이전20봉 평균 range의 2배 impulse와 증가 volume 뒤, 2~6봉 flag, impulse range의 최대0.5 되돌림, impulse 대비 volume0.7 이하를 사용한다. 완료15분봉 resumption을 확인한 뒤 다음 온전한 분봉 open 진입은 원문의 장중 market 진입과 구별되는 명시적 변형이다.
- 관리: 완료봉 close가 알려진 formation floor 아래면 다음 분봉 open 전량 종료. 진입 이후 완전히 형성된 엄격한 1L1R 저점 pivot−가격 tick으로 stop을 올리며 내리지 않는다. 직전3개 완전한 진입후 봉 high와 실제 진입가를 넘고 range가 그3봉 평균보다 큰 첫 완료봉에서 남은 수량의30%를 다음 분봉 open에 한 번 청산한다.
- 크기: 알려진 reference entry와 구조적 stop 차이에 가용 cash의0.25%를 배정하고 entry notional은 cash10% 이하. q=min(0.0025×cash/risk distance,0.10×cash/reference). 모델 체결가의 notional이 예약 한도를 넘으면 취소한다. 갭 손실의 상한을 보장하지 않는다.
- 시간: 의사결정·detail은 available_ts_ms=close_ts_ms인 BAR_CLOSE 모델만 허용한다. 지연된 decision/volume clock은 조용히 관리 callback을 생략하지 않고 차단한다. 알려진 시점 직후의 첫 온전한 minute부터 활성화한다. Kell stop 유효기간2×15분, Gajjala next-open 유효기간1분. HTF context는 실제 available 시점으로 필터링한다.

## 실제 연결과 증거

scalp7_exact25_structure_v1.evaluate → compile_model → create_order → 기존 DetailExecutionAdapter → 실제 수량 partial record_fill → account_snapshots_from_ledger 경로를 사용한다. frozen source/runner/기존5회 결과는 편집하지 않는다. 기존 adapter가 partial callback을 직접 받지 않으므로 새 합성 caller는 next-open partial 의도를 큐에 저장하고 기존 record_fill API에 MODEL_NOT_OBSERVED 영수증을 전달한다.

체결 영수증은 observed trade/queue가 아니다. partial과 나머지 전량 종료는 같은 position_episode_id를 공유한다. fee와 실제 남은 BASE 수량을 계좌에 반영한다. 보호 stop의 gap open 및 구조실패 전량 종료는 예정 partial보다 우선한다. 분봉 gap이 partial보다 먼저 발견되면 가짜 exit를 쓰지 않고 기존 UNRESOLVED 및 unknown 소유권을 보존한다. 종료 시점 열린 포지션도 강제 flat하지 않는다.

새 order_submit 시점이 이전 포지션의 마지막 알려진 종료보다 이르면 후속 주문을 차단하여 미래에 해제될 cash를 선지출하지 않는다. unknown 이후 후속 setup을 차단하고 계좌는 알려진 가격 prefix만 남긴다. full account/경제손익은 주장하지 않는다.

SYNTHETIC_EVIDENCE.json은 손으로 만든 두 lifecycle의 계획·3개 체결·관리 이벤트·계좌 시작/끝을 재현한다. 합성 NAV와 DD 숫자는 엔진 산술 증거이며 시장 경제성 증거가 아니다. 같은 폴더 build_synthetic_evidence.py로 재생성 가능하다. 코드·test·frozen component·volume adapter·기존 source package SHA를 함께 기록한다.

## 준비 상태와 차단 조건

| 항목 | 상태 | 근거 또는 다음 조건 |
|---|---|---|
| 두 선언모델의 configured lifecycle | 구현·합성 검증 가능 | 구체적인 formation/entry/stop/partial/ownership/account 경로 |
| 동일 단위 Gajjala volume 비교 | 공통 admission 연결 | observed BASE field·schema·authority SHA 및 available clock 검사; UNKNOWN 금지 |
| price grid tick | 계약 검사 구현 | tick은 체결 건수가 아닌 quote price increment; source receipt SHA와 PIT 유효기간 필요 |
| source price basis | 명시적 충돌 차단 | decision/detail/HTF attrs·row의 mark/index 등 LAST_PRICE 충돌 거부 |
| genuine 데이터 준비 | BLOCKED | 실제1h context/benchmark/15m/1m 정합·가용시간·갭·source hash 입증 필요 |
| genuine 비용·자금범위 | BLOCKED | venue/product/cost·slippage 증거 및 별도 승인이 필요; funding은 UNKNOWN_NOT_ZERO |
| genuine partial 실행 caller | BLOCKED | future identity·동결·예산을 검증하는 gateway 추가 필요; 현재 bounded synthetic caller만 있음 |
| 원저자 전체 방법 재현 | 미주장 | 재량 scanner·size·모든 phase/exit 수치 전체를 추정해 사실화하지 않음 |
| 연구 경제성 | 미측정 | 새 FULL 0, 성능·우수성·승격 결론 없음 |

source price 표시가 없다는 사실만으로 진짜 last 데이터임을 증명하지 않는다. fixture label과 합성 선언도 호출자의 주장이다. 실제 역사 데이터 실행 가능성을 입증하는 독립 provenance 검증으로 대체하지 않는다. 미래 연구에서 얻는 손익 역시 funding 미포함이면 “펀딩 제외 연구 손익”으로 표시해야 한다.

## 검증 실행

현재 전용 synthetic 회귀는 test_scalp7_kell_gajjala_closure_v1.py에 있다. 실제 통과 수·정상 hooks 및 독립 검토 결과는 최종 campaign 검증 영수증이 권위 원장이다. 이 문서는 동결 source/기존 5회/원래25개 상태를 덮어쓰지 않는다.

실행 예시: 저장소 root에서 PYTHONPATH=. /home/z/z/.venv/bin/python research/campaigns/scalp7_20261001/measurement_exact25_closure_v1/implementation/kell_gajjala/build_synthetic_evidence.py. 이 명령은 테스트의 손으로 만든 frame만 생성하며 실제 과거 가격 loader를 호출하지 않는다.
