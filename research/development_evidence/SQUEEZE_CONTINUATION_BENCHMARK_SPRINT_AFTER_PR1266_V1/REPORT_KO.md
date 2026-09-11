# Squeeze Continuation v1 — 마지막 DEV benchmark sprint 결과

scope_key=`SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1` · 승인: [Issue #1267](https://github.com/leegkssk2000-commits/vultr-z/issues/1267) · 증거 기준: [SPEC.json](SPEC.json), [STAGE1_TABLE.json](STAGE1_TABLE.json), [STAGE1_SELECTION.json](STAGE1_SELECTION.json).

**Stage1 survivor는 0개입니다. 최종 DEV 구조는 `Squeeze Continuation v1 = C70_TM_CAPREUSE_V1`, 기존 candidate82로 고정합니다.** 8개 source를 검토하고 적격 component 4개를 두 기간에서 각각 고정 진입 screen으로 확인했습니다. 2025년 Basso·Martin Luk의 손익 proxy는 개선됐지만, 2026년에는 네 component 모두 비용 포함 증분이 음수였습니다. 사전에 동결한 양 기간 통과 조건에 따라 Stage2 FULL을 열지 않았습니다.

이번 결과는 **새로운 수익개선 채택 0건**입니다. 기존 CAPREUSE의 DEV TRADEOFF 판정은 보존하며, 이름 고정과 G5B 준비가 경제 PASS나 실거래 승격을 의미하지 않습니다. 후속 자동 미세조정 없이 이 DEV sprint를 종료하는 경계입니다.

## Source 검토: 8개 중 4개 적격

A는 독립 대회/공식 성과기록, B는 추적 가능한 공개기록, C는 본인 주장과 구체적 규칙, D는 2차 전언입니다. 성과 등급은 해당 단일 component의 유효성 등급과 다릅니다. 적격 source도 원문 그대로의 전체 전략 복제가 아니며, UTC 일봉·4h 관측·다음 open 체결·기존 partial 이후 활성화는 사전 공개한 ZEL 변환입니다. source에 없는 기간/임계치 sweep은 없습니다.

| slot | source / 성과등급 | 원문 규칙 | ZEL 변환 | 사전 판정 | 근거 |
| --- | --- | --- | --- | --- | --- |
| S1-01 | Jerry Parker / B | 공식 펀드의 EMA·breakout 50–200일 범위 | 구체적 단일 청산 규칙 미확인; 구현 없음 | 제외: 기간·조건 선택 시 원문 밖 숫자 선택 필요 | [펀드 원문](https://blueprintip.com/systematic-investing-strategies/exchange-traded-funds/next-generation-liquid-alt-blueprint-chesapeake-multi-asset-trend-etf/) |
| S1-02 | Tom Basso / C | 교육용 5일·10일 이동평균 예시 | 실제 partial 후 완료 UTC일 SMA5<SMA10이면 runner만 다음 open 청산 | 적격; deployed 설정·성과 복제 주장 없음 | [1993 인터뷰](https://enjoytheride.world/wp-content/uploads/2023/06/StockAndCommoditiesMagazineInterview.pdf) |
| S1-03 | Linda Raschke / C | SMA3−SMA10; 가격 상승·oscillator 하락의 sell divergence | 실제 partial 후 진입 이후 최고 close 경신 + 당시 oscillator 약화 시 잔량 청산 | 적격; 재량 divergence를 인과적 최고 close 비교로 명시적 변환 | [2004 인터뷰](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf) |
| S1-04 | John Carter / C | 초기 squeeze thrust가 통상 4봉; 이후 무수익이면 청산 | 진입봉 포함 4번째 완료4h봉에서 비용 차감 진행손익≤0이면 한 번만 청산 | 적격; 통상 지속시간을 고정 checkpoint로 변환 | [공식 설명](https://www.simplertrading.com/news/ttm-squeeze-explained) |
| S1-05 | Oliver Kell / A | EMA Crossback·Wedge Drop 개념 | 실행 가능한 EMA 기간·실패 비교·시점 미확인; 구현 없음 | 제외: 성과와 별개로 정확한 새 규칙 불충분 | [공식 규칙](https://kelltrading.com/) · [성과 영수증](SOURCES/kell_minervini/SOURCE_RECEIPTS.json) |
| S1-06 | Mark Minervini / A | SEPA·엄격한 위험관리 | 공식 공개자료의 실행 가능한 실패 청산 조건 미확인; 구현 없음 | 제외: 임의 7–8% 손절·timeout 추가 금지 | [공식 규칙](https://minerviniprivateaccess.com/strategy) · [성과 영수증](SOURCES/kell_minervini/SOURCE_RECEIPTS.json) |
| S1-07 | Martin Luk / A | 본인 기고의 EMA9 trailing-stop sell rule | 실제 partial 후 완료 UTC일 close<EMA9이면 runner만 다음 open 청산; SMA9 seed 고정 | 적격; 전체 매매와 대회수익 복제 주장 없음 | [본인 기고](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons) |
| S1-08 | Christian Flanders / A | 완료일 close<10일 MA에서 청산 | 부모의 SMA10 runner와 같은 매핑 | 제외: CONTROL 중복; 소량 DMA20 대안은 수량 불명확 | [본인 기고](https://tradingresourcehub.substack.com/p/christian-flanders-2025-review) |

전체 카드·일자·검색/수신 hash: [SOURCE_REGISTRY.json](SOURCE_REGISTRY.json), [Basso/Parker](SOURCES/parker_basso/SOURCE_CARD.json), [Raschke/Carter](SOURCES/raschke_carter/SOURCE_CARD.json), [Kell/Minervini](SOURCES/kell_minervini/SOURCE_CARD.json), [최근 trader 2명](SOURCES/recent_traders/SOURCE_CARD.json). Qullamaggie는 기존 CONTROL이며 신규 8개 슬롯에 포함하지 않았습니다. 제외된 4개 slot은 screen 미실행으로, 경제지표를 0으로 꾸며 채우지 않았습니다.

## Stage1: 실제 완료한 8개 window screen

기간은 이미 사용한 `DEV2025`와 `SEEN2026`입니다. 모든 증분은 **exact CAPREUSE 저장 원장 대비 수량가중 trade-bps**이며 계좌수익률이 아닙니다. parent의 campaign 진입·실제 배정수량을 고정했고 신규 신호·점유 재생을 하지 않았습니다. runner 교체는 같은 진입의 청산 경로만 연장할 수 있으므로 고정된 후속 진입과 겹치는 노출이 생길 수 있습니다. 따라서 screen 손익·노출을 실행 가능한 FULL 결과로 해석하지 않습니다.

원문/인과성/무결성 PASS, normal 증분>0, cost2 증분>0, 일반·상위10% 승리 보존 각각≥60%를 **두 창에서 따로 모두** 만족해야 합니다. 두 창 합산 이익으로 다른 창의 실패를 덮지 않습니다. 모든 8개 window의 source conformance와 causal/integrity는 PASS입니다.

| slot / 창 | gross 증분 bps | 추가비용 bps | normal 증분 bps | cost2 증분 bps | 일반 승리 보존 | 상위10% 보존 | 창 gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1-02 / DEV2025 | +2,354.29 | +113.33 | +2,240.96 | +2,127.62 | 85.94% | 96.14% | PASS |
| S1-02 / SEEN2026 | -435.95 | +15.09 | -451.05 | -466.14 | 91.26% | 100.00% | FAIL |
| S1-03 / DEV2025 | -3,710.47 | -439.25 | -3,271.22 | -2,831.97 | 87.09% | 58.22% | FAIL |
| S1-03 / SEEN2026 | -2,579.31 | -64.67 | -2,514.64 | -2,449.97 | 78.97% | 61.60% | FAIL |
| S1-04 / DEV2025 | -4,240.49 | -249.19 | -3,991.29 | -3,742.10 | 74.29% | 67.90% | FAIL |
| S1-04 / SEEN2026 | -3,253.04 | -90.74 | -3,162.30 | -3,071.57 | 69.77% | 0.00% | FAIL |
| S1-07 / DEV2025 | +3,152.67 | +26.11 | +3,126.57 | +3,100.46 | 99.03% | 100.00% | PASS |
| S1-07 / SEEN2026 | -281.89 | +9.33 | -291.22 | -300.55 | 96.14% | 100.00% | FAIL |

일반/상위10% 보존률은 부모의 **완결 net 양수 campaign**만 대상으로 합니다. 부모 이익순 상위 `ceil(승리수×10%)`를 큰 승리로 나누며 나머지가 일반 승리입니다. 각 부모 이익을 상한으로 child의 완결 양수 이익만 인정하고, 추가로 번 이익은 보존율 손실을 상쇄하지 않습니다. child가 미완결이면 이 보존율에서는 0으로 계산합니다. 분모는 CAPREUSE이며 예전 보고서의 C70_LOCAL 기준 보존율과 직접 혼용하지 않습니다.

### 손익 변화의 원인

| slot / 창 | 줄인 기존손실 gross | 추가 악화손실 gross | 더 남긴 승리 gross | 잘라낸 승리 gross | 추가비용·funding | 회피 / 감소 / 훼손 건수 |
| --- | --- | --- | --- | --- | --- | --- |
| S1-02 / DEV2025 | 0.00 | 0.00 | 4,859.68 | 2,505.39 | +113.33 | 0 / 0 / 11 |
| S1-02 / SEEN2026 | 0.00 | 0.00 | 219.39 | 655.34 | +15.09 | 0 / 0 / 4 |
| S1-03 / DEV2025 | 755.27 | 0.00 | 3,436.43 | 7,902.16 | -439.25 | 1 / 1 / 8 |
| S1-03 / SEEN2026 | 0.00 | 0.00 | 0.00 | 2,579.31 | -64.67 | 0 / 0 / 3 |
| S1-04 / DEV2025 | 5,071.03 | 18.14 | 0.00 | 9,293.37 | -249.19 | 0 / 24 / 8 |
| S1-04 / SEEN2026 | 1,752.56 | 131.45 | 0.00 | 4,874.15 | -90.74 | 0 / 8 / 2 |
| S1-07 / DEV2025 | 0.00 | 0.00 | 3,274.59 | 121.92 | +26.11 | 0 / 0 / 3 |
| S1-07 / SEEN2026 | 0.00 | 0.00 | 6.87 | 288.76 | +9.33 | 0 / 0 / 2 |

단위는 gross/비용 모두 trade-bps입니다. 회피는 부모 net≤0→child net>0, 감소는 부모 손실의 net 개선, 훼손은 부모 승리의 net 감소 건수입니다. 회피와 감소는 중복될 수 있어 합산하지 않습니다. 검산식은 `줄인 손실−추가 악화+더 남긴 승리−잘라낸 승리−추가비용=normal 증분`입니다. 신규·제외 점유 항목은 고정 진입 screen에서 모두 0이며, 미검증 FULL에서 후속거래 영향까지 0이라는 뜻은 아닙니다. 원장별 검산 잔차 절대값은 전부 1e−7 bps 미만입니다.

### 위험·보유·trigger proxy

| slot / 창 | MFE giveback 감소 bps | 수량가중 MAE 변화 bps | 최악손실 bps / 변화 | 손실 하위10% 평균 bps / 변화 | 노출 symbol-days / 변화 | 최장보유 일 | trigger / 체결청산 / 변경 campaign |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1-02 / DEV2025 | -3,640.94 | -136.37 | -920.11 / +0.00 | -743.18 / +0.00 | 333.59 / +34.59 | 32.67 | 19 / 19 / 21 |
| S1-02 / SEEN2026 | -435.95 | -152.30 | -856.09 / +0.00 | -856.09 / +0.00 | 85.17 / +4.67 | 19.50 | 5 / 5 / 6 |
| S1-03 / DEV2025 | +25,862.89 | +1,056.97 | -920.11 / +0.00 | -743.18 / +0.00 | 180.07 / -118.93 | 8.83 | 20 / 20 / 20 |
| S1-03 / SEEN2026 | +4,558.86 | +0.00 | -856.09 / +0.00 | -856.09 / +0.00 | 59.17 / -21.33 | 9.33 | 3 / 3 / 3 |
| S1-04 / DEV2025 | +18,189.73 | +6,065.34 | -691.16 / +228.96 | -511.97 / +231.21 | 207.39 / -91.61 | 23.17 | 33 / 33 / 33 |
| S1-04 / SEEN2026 | +4,645.15 | +1,896.94 | -613.97 / +242.13 | -476.36 / +379.73 | 51.00 / -29.50 | 17.50 | 11 / 11 / 11 |
| S1-07 / DEV2025 | -1,899.32 | +0.00 | -920.11 / +0.00 | -743.18 / +0.00 | 312.44 / +13.44 | 31.33 | 22 / 22 / 22 |
| S1-07 / SEEN2026 | -281.89 | +0.00 | -856.09 / +0.00 | -856.09 / +0.00 | 83.61 / +3.11 | 19.50 | 6 / 6 / 6 |

MFE giveback은 `Σ max(0, 해당 보유경로 MFE×배정수량−campaign gross)`의 부모−screen 차이입니다. 조기 청산이 관측경로 자체를 줄이면 포착하지 못한 미래 고점도 빠집니다. 따라서 큰 양수도 실현이익 보존이나 계좌 DD 수선을 증명하지 않습니다. MAE 변화는 child−parent이며 양수는 그 경로에서 불리한 가격 움직임이 줄었음을 뜻합니다. 둘 다 단순 경로 proxy로, 전체 시간순 점유·배정 상호작용과 구분합니다. trigger 수는 component 신호 수이고 변경 campaign은 기존 SMA10 청산이 지연되는 경우까지 포함해 서로 같지 않을 수 있습니다.

Basso는 2025 normal +2,240.96 bps였지만 2026 −451.05 bps였습니다. Martin Luk도 +3,126.57 / −291.22 bps로 두 기간 일관성을 확보하지 못했습니다. Raschke는 보유·giveback proxy를 줄였지만 잘라낸 승리가 컸고, 2025 상위10% 보존은 58.22%로 60% gate도 미달했습니다. Carter는 손실 꼬리를 개선했으나 승리 훼손이 이를 초과했으며 2026 상위10% 승리 보존은 0%였습니다. 네 component 모두 Stage1 탈락으로 보존합니다. 임계치 변경·후속 child 수선은 이번 scope에서 하지 않습니다.

## 최종 부모 경제표: 저장된 FULL 회수, 재실행 0회

| 지표 | 단위/기준 | DEV2025 CAPREUSE | SEEN2026 CAPREUSE |
| --- | --- | --- | --- |
| 실제 진입 / 완결 / 미완결 |  | 83 / 79 / 4 | 22 / 17 / 5 |
| 승률 | % | 39.24% | 52.94% |
| 평균 승리 / 평균 손실 | trade-bps | 896.87 / -310.16 | 1,110.78 / -244.94 |
| payoff / PF | 배 | 2.89 / 1.87 | 4.53 / 5.10 |
| 완결 net | trade-bps | 12,914.96 | 8,037.44 |
| 미완결 mark | trade-bps | -272.90 | -2,113.01 |
| terminal net | trade-bps | 12,642.06 | 5,924.43 |
| cost2 terminal net | trade-bps | 10,419.11 | 5,323.11 |
| marked DD | trade-bps | 6,793.58 | 4,415.19 |
| 최대 연패 | 건 | 8 | 4 |
| 최악 손실 / 손실 하위10% 평균 | trade-bps | -920.11 / -743.18 | -856.09 / -856.09 |
| 수량가중 노출 | symbol-days | 299.00 | 80.50 |
| 평균 수량가중 동시노출 | full-entry 단위 | 0.80 | 0.67 |
| 최장 보유 | 일 | 30.67 | 17.50 |
| 일반 / 상위10% 승리 보존 | CAPREUSE 자신 기준 | 100.00% / 100.00% | 100.00% / 100.00% |
| partial / runner / reuse | 건 | 28 / 28 / 10 | 9 / 9 / 1 |
| 점유 제외 신호 | 건 | 1 | 0 |
| 제외 / 신규 / 점유탈락 증감 | 자신 기준 건 | 0 / 0 / 0 | 0 / 0 / 0 |
| top1 양의 기여 집중도 | % | 16.10% | 23.76% |
| formal PASS / independent | 상태 | False / False | False / False |

저장 근거: [DEV2025 SNAPSHOT](PARENT/DEV2025/SNAPSHOT.json), [SEEN2026 SNAPSHOT](PARENT/SEEN2026/SNAPSHOT.json). 손익은 원래 full-entry 기준 수량가중 trade-bps이며 계좌 원금·레버리지·실제 계좌 DD%를 의미하지 않습니다. 비용·funding·미완결 mark를 포함합니다. CAPREUSE에 새 component가 채택되지 않았으므로 이 표의 전후 경제 증분은 0이며, 신규 성과로 재집계하지 않습니다.

## Stage2·Stage3·challenge 종료

| 단계 | 실제 결과 | canonical 후보 / FULL | 처리 |
| --- | --- | --- | --- |
| Source | 8개 검토, 4개 source/one-axis 적격 | 0 / 0 | 원문 불충분·중복 4개 제외 |
| Stage1 | 4 component×2 USED_DEV = 8개 common-trade screen; survivor 0 | 0 / 0 | 모든 raw·accounting·receipt 보존 |
| Stage2 | NOT_RUN_NO_STAGE1_SURVIVOR | 0 / 0 | 탈락 component FULL 금지 준수 |
| Stage3 | bundle 0; B1/B2 NOT_RUN | 0 / 0 | interaction_delta=N/A; 측정값 0으로 표시하지 않음 |
| Reserved challenge | NOT_AVAILABLE, Stage1 전에 동결 | 0 / 0 | 깨끗한 pre-existing unused window 증거 없음 |
| Final architecture | Squeeze Continuation v1 = exact candidate82 CAPREUSE | 신규 0 / 0 | 기존 누계 84후보 / 152평가 유지 |

Funnel은 **8개 source→4개 적격 component→Stage1 survivor 0→신규 합성 0→기존 final identity 1개**입니다. 생존 후보가 없으므로 Pareto·성과등급 tie-break는 작동하지 않았습니다. 상호작용을 측정한 bundle도 없습니다. [CHALLENGE_REVIEW.md](CHALLENGE_REVIEW.md)에 따라 USED_DEV를 사후 OOS로 재분류하거나 새 과거창을 발굴하지 않았습니다. parent/C63/Top5 재생·FULL 재시도·FIXED·sweep·paid AI·주문·배포는 모두 0입니다.

이전 대화 중단 시점의 저장되지 않은 로컬 screen 완료 여부는 확인되지 않아 완료로 주장하지 않습니다. 원격에 봉인된 동일 source와 기존 부모 ledger에서 이번 8개 고정 진입 screen을 복구했으며, 과거 FULL을 재실행한 것은 아닙니다. 재개 근거는 [RECOVERY_RECEIPT.json](RECOVERY_RECEIPT.json)입니다.

## Squeeze Continuation v1 정확한 구조·고정 근거

| 항목 | 고정값 |
| --- | --- |
| strategy_family / 이름 | SQUEEZE_CONTINUATION / Squeeze Continuation v1 |
| 내부 계보 / 최종 identity | C70_LOCAL registered71 → C70_TM → C70_TM_CAPREUSE_V1 candidate82 |
| 부모 exact merge | [PR #1262](https://github.com/leegkssk2000-commits/vultr-z/pull/1262) · `73b1277b218a1f178e424790271aa161d8ee9365` |
| sprint source freeze commit | `57e687ddda322c8ee347ad8f7e32a92a1328b918` |
| strategy digest | `5c63d3a69e1398dd1fae1076c9e8bdc29b8252a3188ac6b6a79571b363b22a16` |
| sprint SPEC SHA256 | `7b464510ddb66e3766731bc3711a7dbf8e4c0dbc23bc663a04f10617c2614cfb` |
| CAPREUSE 실행 코드 SHA256 | `cd4e3eeb3ec456a66d753dceb508e32ddc7ca202c1a56894752f338b49536ef2` |
| 부모 관리 코드 SHA256 | `1b5fd06450c9a08af1812f60757980db3a08679461480fb3241866bc7790a95c` |
| DEV2025 input packet SHA256 | `4c1936726690fd29407694bf55e1047c4870d524843dd5b3420e60ac238a919c` |
| SEEN2026 input packet SHA256 | `91d6e07a38c6b0dd3bcfcfa4b1b10bcf8cb3595d35fba183765f8e02a6a24a70` |

진입은 reg71의 기존 신호·ER14/range 조건과 daily EMA21 또는 비하락 SMA5 strict-range rescue를 그대로 사용합니다. 진입·수량을 새로 최적화하지 않습니다. 실제 진입 후 세 번째 완료 UTC일에서 비용 차감 진행손익이 양수이면 다음 실제 open에 1/3 partial을 수행합니다. 그 partial이 실제 체결된 뒤 BE와 완료일 close<SMA10 runner 청산을 유지합니다. D3 동일 close에서 발생하는 SMA10/일봉자료 안전청산, 기존 floor와 partial 전 momentum 비양수 청산도 유지합니다.

CAPREUSE는 완료된 실제 partial로 반환된 용량만 후속 reg71 신호에 재사용하며, 아직 체결되지 않은 같은 시각 청산을 미리 재원으로 쓰지 않습니다. 비용 함수는 기존 `max(20 bps, fee+spread+impact+funding)`이며 funding은 기존 8시간 settlement 경계를 사용합니다. 다음 open이 경계 밖이면 가짜 fill 없이 terminal mark로 남깁니다. group-PROFITLOCK83·LOTLOCK84는 실패 비교로 보존하며 최종 규칙에 넣지 않습니다. 전체 의존성 hash는 [SPEC.json](SPEC.json), 원격 재확인은 [REMOTE_FREEZE.json](REMOTE_FREEZE.json), 최종 이름·규칙·digest는 [ARCHITECTURE_SEAL.json](ARCHITECTURE_SEAL.json)에 있습니다. 진입 함수 locator의 문서 오타만 정정했으며 규칙·코드·경제수치는 변경하지 않았습니다.

## G5B 인계: PREPARED_NOT_ACTIVE

이번 scope의 [G5B_HANDOFF.json](G5B_HANDOFF.json)은 **PREPARED_NOT_ACTIVE 준비 기록**이며 runtime registry 등록은 아직 false입니다. fresh T=0이며 USED_DEV·Stage1·기존 FULL의 formal G5B credit은 전부 0입니다. final identity를 고정했어도 현재 G5A 통과 receipt는 확인되지 않았고, 기존 연결부는 time_stop 청산만 지원하므로 partial·SMA10 runner·CAPREUSE의 정확한 경로를 그대로 실행하는 bridge가 아직 충족되지 않았습니다. 이를 G5B 실행 중이나 fresh 수집 완료로 보고하지 않습니다. 구체적인 차단 근거는 `backend/research/rebuild/g5_forward_real_evidence_bridge_v1.py`의 `ONLY_FROZEN_TIME_STOP_SUPPORTED`와 `backend/research/rebuild/g5b_operational_terminal_v1.py::freeze_boundary`입니다. 각 lot의 entry/partial/exit에 관측 depth·수량·비용·signed actual funding·latency·영속 dedupe 증거도 필요하며, DEV 비용 proxy를 생산급 증거로 재분류하지 않습니다.

다음 lane에서 exact identity를 보존한 source/fill/accounting bridge와 G5A receipt를 검증하고, 새 fresh boundary·출처·비용·무결성 기준을 봉인한 뒤 활성화해야 합니다. T6는 diagnostic, T12는 provisional이며 terminal은 명시적 receipt로 판정합니다. 같은 lane G5B terminal PASS 전 G6는 열지 않습니다. 신규 아이디어는 v2_backlog로 보내며 이번 USED_DEV 수정을 자동 연장하지 않습니다. handoff의 activation_id·cohort_id·boundary_ms는 모두 null입니다. 후속 [G5B 준비 인계 Issue #1268](https://github.com/leegkssk2000-commits/vultr-z/issues/1268)에 구체적인 activation 미충족 조건과 완료 기준을 결속했습니다.

## CI·리뷰·병합 최종 결속

경제 실행은 종료됐습니다. PR CI·리뷰·정상 병합·정확한 merge SHA 검증의 최종 결과는 `EXACT_MERGE_VERIFICATION.json`에 별도 결속합니다. 이 기록은 수치 검증과 구현 마감 증거이며 경제개선 PASS 또는 G5B PASS가 아닙니다. 추가 경제 실행 예산은 0입니다.

V | 신규 component 채택 0건; exact CAPREUSE를 Squeeze Continuation v1로 보존.
A | hold — 실거래·formal G5B 활성화 권한을 추가하지 않음.
R | 2025년 2개 screen 개선, 2026년 4개 모두 normal/cost2 음수; 양 창 gate survivor 0.
D | parent marked DD 6,793.58 / 4,415.19 trade-bps; 기존 위험과 미완결 손익을 그대로 공개.
N | DEV 종료 후 PREPARED_NOT_ACTIVE G5B handoff의 실제 bridge·receipt·fresh boundary 충족 여부부터 검증.
요약 | source 8→적격 4→survivor 0→CAPREUSE 유지; 신규 후보 0·FULL 0·누계 84/152·fresh T 0.
