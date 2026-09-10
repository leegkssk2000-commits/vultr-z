**DEV2025 — 2024-12-19T08:00:00+00:00 ≤ 평가 < 2025-12-29T08:00:00+00:00**

| 지표 | C70_LOCAL | C70_TM | C70_TM_CAPREUSE_V1 |
|---|---:|---:|---:|
| 완결 / 미완결 | 79 / 4 | 69 / 4 | 79 / 4 |
| 승률 | 39.24% | 42.03% | 39.24% |
| 평균 승리 / 손실 (bps) | 878.46 / -359.45 | 912.88 / -341.85 | 896.87 / -310.16 |
| payoff / PF | 2.44 / 1.58 | 2.67 / 1.94 | 2.89 / 1.87 |
| terminal net (trade-bps) | 9,706.09 | 12,526.77 | 12,642.06 |
| cost2 terminal (trade-bps) | 7,811.35 | 10,390.86 | 10,419.11 |
| marked DD (trade-bps) | 5,366.68 | 6,460.53 | 6,793.58 |
| 최대 연패 / 최악 손실 (bps) | 8 / -1,148.05 | 8 / -920.11 | 8 / -920.11 |
| 손실 하위10% 평균 (bps) | -876.38 | -776.71 | -743.18 |
| 수량가중 노출 (symbol-days) | 181.83 | 288.28 | 299.00 |
| 평균 정규화 동시노출 | 0.48 | 0.77 | 0.80 |
| 일반 / 상위10% 승리 보존¹ | 100.00% / 100.00% | 76.26% / 58.95% | 76.26% / 72.21% |
| partial / runner / capacity 재사용 진입 | 0 / 0 / 0 | 26 / 26 / 0 | 28 / 28 / 10 |
| 점유 제외 신호 | 1 | 12 | 1 |
| 부모 대비 제외 / 신규¹ | 0 / 0 | 10 / 0 | 0 / 0 |
| 완결→미완결 / 미완결→완결¹ | 0 / 0 | 0 / 0 | 0 / 0 |
| 최대1건 양의 기여 집중도 | 12.06% | 16.90% | 16.10% |

**SEEN2026 — 2026-05-08T00:00:00+00:00 ≤ 평가 < 2026-09-05T00:00:00+00:00**

| 지표 | C70_LOCAL | C70_TM | C70_TM_CAPREUSE_V1 |
|---|---:|---:|---:|
| 완결 / 미완결 | 17 / 5 | 16 / 5 | 17 / 5 |
| 승률 | 52.94% | 50.00% | 52.94% |
| 평균 승리 / 손실 (bps) | 1,102.80 / -256.84 | 1,179.68 / -244.94 | 1,110.78 / -244.94 |
| payoff / PF | 4.29 / 4.83 | 4.82 / 4.82 | 4.53 / 5.10 |
| terminal net (trade-bps) | 5,757.43 | 5,364.86 | 5,924.43 |
| cost2 terminal (trade-bps) | 5,236.71 | 4,775.67 | 5,323.11 |
| marked DD (trade-bps) | 3,451.20 | 4,305.36 | 4,415.19 |
| 최대 연패 / 최악 손실 (bps) | 4 / -856.09 | 4 / -856.09 | 4 / -856.09 |
| 손실 하위10% 평균 (bps) | -856.09 | -856.09 | -856.09 |
| 수량가중 노출 (symbol-days) | 51.50 | 78.17 | 80.50 |
| 평균 정규화 동시노출 | 0.43 | 0.65 | 0.67 |
| 일반 / 상위10% 승리 보존¹ | 100.00% / 100.00% | 66.59% / 80.67% | 74.14% / 80.67% |
| partial / runner / capacity 재사용 진입 | 0 / 0 / 0 | 8 / 8 / 0 | 9 / 9 / 1 |
| 점유 제외 신호 | 0 | 1 | 0 |
| 부모 대비 제외 / 신규¹ | 0 / 0 | 1 / 0 | 0 / 0 |
| 완결→미완결 / 미완결→완결¹ | 0 / 0 | 0 / 0 | 0 / 0 |
| 최대1건 양의 기여 집중도 | 25.33% | 25.17% | 23.76% |

¹ 보존률·거래 변화는 각 기간 C70_LOCAL 기준. 부분 leg는 WR trade 수에 추가하지 않는다. 수익·손실은 원래 full-entry reference에 대한 수량가중 trade-bps이며 계좌 수익률이 아니다. 두 기간 모두 USED_DEV다.

**단계별 증분 — 동일 규칙, 실제 FULL 결과**

| 비교 | 2025 net Δ | 2026 net Δ | 2025 cost2 Δ | 2026 cost2 Δ | 2025 DD Δ | 2026 DD Δ |
|---|---:|---:|---:|---:|---:|---:|
| A: C70_LOCAL → C70_TM | +2,820.68 | -392.57 | +2,579.51 | -461.04 | +1,093.85 | +854.16 |
| B: C70_TM → CAPREUSE | +115.29 | +559.57 | +28.25 | +547.44 | +333.04 | +109.83 |
| C: C70_LOCAL → CAPREUSE | +2,935.97 | +167.00 | +2,607.76 | +86.40 | +1,426.90 | +963.99 |

**수선 B의 PnL bridge (trade-bps)**

| 구성 | DEV2025 | SEEN2026 |
|---|---:|---:|
| 기존 공통거래 관리/수량 변화 | 0.00 | 0.00 |
| 복구된 후속 캠페인 gross | +202.33 | +571.69 |
| 추가 전체 비용 차감 | -87.04 | -12.13 |
| 그중 수수료 차감 (위 비용에 포함) | -28.89 | -3.33 |
| 그중 funding 차감 (위 비용에 포함) | -45.70 | -7.00 |
| 새 점유 상호작용 / 기존 TM 거래 제외 | 0.00 / 0.00 | 0.00 / 0.00 |
| 잘라내거나 변형한 기존 TM 승리 | 0.00 | 0.00 |
| = 수선 B 전체 순증분 | +115.29 | +559.57 |
| 검산 잔차 | 0.00 | 0.00 |

B는 기존 C70_TM 캠페인 73 / 21개의 관리 경로와 수량을 모두 보존했다. 기존 TM 대비 제외0, 신규10 / 1, 완결↔미완결 변화0이다. TM 기준 일반·상위10% 승리 보존은 두 기간 모두100%다. 2025년 복구10건은 1/3 크기8건과 1/9 크기2건, 2026년 복구1건은 1/3 크기다. 원래 baseline 거래 identity는 모두 복구됐지만 원래 full-size 수익을 복구했다는 뜻은 아니다.

A와 C의 기존 손실 감소·승리 확장·잘라낸 승리·추가 비용·점유변화 전수 분해는 각 기간 DECOMPOSITION_A/C.json에, B의 각 캠페인과 모든 비용 성분은 REPAIR_BRIDGE.json에 보존했다. gross에서 전체 비용을 한 번만 차감하며 수수료/funding 부분 항목을 중복 차감하지 않는다.

**판정: net/cost2 증분 PASS, 전체 TRADEOFF — 개발 workcopy로 보존, 기준전략 승격 없음.**

수선 B와 누적 C의 net/cost2는 두 기간 모두 개선됐다. 그러나 baseline 대비 누적 C의 DD는 두 기간 모두 더 커졌고 baseline 일반·상위10% 승리 보존이100%에 못 미친다. B에서도 DD가 늘고 2025 WR이42.03%→39.24%로 하락한다. 기존 경제 acceptance를 완화하지 않으며 risk/retention/WR의 악화를 수익 증가로 숨기지 않는다.

PR1260 source conformance는 그대로 PASS이며, 이번 ZEL occupancy repair도 별도로 PASS다. 2026의 과거 점유 손실 -1,725.68bps 전액 회복을 가정하지 않았으며 실제 수선 증분은 +559.57bps다. 연도별 규칙 변경·결과 선택·추가 tuning은 없다.

**검증과 보존**

- 55개 합성·인과·기존 회귀 PASS. OFF exact delegation, partial 전 점유, actual fill 이후 capacity, 동일 timestamp 보수적 순서, gap, pending boundary, 반복1/3 재사용, 미래변조/단축 prefix, 비용·funding·WR campaign 회계 검증.
- 저장105 campaigns·3,328 trace events 전수 검증. 동일 종목 활성 정규화 수량 상한1.0, entry available cap, 모든 cash legs·terminal costs/funding·daily marks·A/B/C bridge PASS. 부모 및 경제 replay0인 saved-only 검사다.
- 최초 saved verifier의 hashed-key/tuple-key 매핑과 JSON tuple/list 비교 결함만 수정했다. 봉인 원본과 수정 전후 해시를 FROZEN_VERIFIER.py.txt / VERIFIER_CORRECTION.json에 보존했다. 경제 엔진·회계 엔진·raw/results는 변경하지 않았으며 경제 재실행0이다.
- 후보82 한 개와 평가147/148 두 FULL만 추가했다. 과거81후보/146평가 및188개 부모 코드·증거 파일을 해시로 보존했다. 최대 예산2/2 사용, 경제 실패0, 남은 예산0.
- 신규4개 Python 모듈, 전용 saved-only CI workflow, 이번 scope 증거만 추가/수정했다. temporary economic dispatcher와 쓰기 credentials를 남기지 않는다.
- 수수료·spread·impact·8h funding proxy·20bps cost floor는 부모와 동일하다. 원래 연구 엔진에 거래소 lot/min-notional 모델이 없어 최소 정규화 수량은 양수인 exact rational로 유지했다. 실거래 합산 포지션/최소주문/실제 체결·정산 funding 검증을 주장하지 않는다.
- live/order/deploy·유료 API·부모/C63/FIXED/sweep/retry/new-OOS 모두0. GitHub Actions 배포 실행 불필요. rollback은 신규 DEV 모듈·검증 workflow·scope만 대상으로 하며 기존 전략 및 증거는 보존한다.

이번 scope는 REPORT_ONLY로 종료한다. 정상 PR 병합과 exact merge saved verification의 최종 SHA/CI receipt는 EXACT_MERGE_VERIFICATION.json에 별도로 결속하며 STATUS의 병합 대기 항목을 그 receipt로 대체한다.

근거: [Issue #1261](https://github.com/leegkssk2000-commits/vultr-z/issues/1261), [PR #1260](https://github.com/leegkssk2000-commits/vultr-z/pull/1260), 본 폴더 SPEC.json·START_RECEIPT.json·각 기간 RAW/RESULT/RECEIPT·SAVED_VERIFICATION.json.
