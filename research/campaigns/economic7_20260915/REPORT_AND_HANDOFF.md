# Economic7 campaign 실행 결과 및 재개 기록

**판정: 전체 campaign 미완료 — source/7 lane provider 결속 HOLD. 신규 Core 승격·경제평가·B/A material·fusion은 모두 0건.**

기존 180일 결과를 재실행하거나 fresh OOS로 승격하지 않았다. 이번 결과는 원본 복구, 실제 장기자료 수집, 인과성/중복 검증 구현, raw L2 지속 수집 및 복구 시험이다.

## 기준점과 보존

| 항목 | 결과 |
|---|---|
| 시작 master | `7f91155f478ed7786aa805b168d76f2c2ae56f31` |
| 이전 anchor | `652671a6fa237b7373f017d259dc69fba674dec3`; 시작 master의 조상 아님 |
| 복구 통합 | `6f96d9a2b23c02dad5e700f3b4358c25c1a015fb`; 기존 30개 연구 커밋과 master 기록 보존 |
| dirty 작업트리 | 원위치 보존; Router 전이 의존성 밖의 3개 변경 복사 안 함 |
| 병렬 작업 | source·data·router·material registry·rolling·QA, subagent 6개 |
| 기존 경제 결과 | 16개 원장 receipt import; 재평가 0회 |

## 7 lane 경제표

아래는 `652671a6f`의 기존 개발 결과다. 빈 값은 미확인/미결속이며 0을 뜻하지 않는다. 실제 이번 fresh 결과를 대신하지 않는다.

| strategy | state | TF | T | T/day | WR | avg win | avg loss | payoff | gross/T | cost/T | net/T bps | PF | DD bps | maxLS | positive months | concentration | rolling OOS | fresh T | verdict |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|
| Keltner/Holy-Grail | DEV | 30m | 72 | — | 63.89% | — | — | — | — | — | 81.99 | 2.869 | 1086.64 | 3 | — | 미검증 | NOT_RUN | UNBOUND | 승격 보류 |
| Trend Rider | DEV capped | 1h | 193 | — | 23.32% | — | — | — | — | — | 15.85 | 1.539 | 1656.38 | 17 | — | 미검증 | NOT_RUN | UNBOUND | 승격 보류 |
| Break | WATCH | 1h | 66 | — | 13.64% | — | — | — | — | — | 27.94 | 1.302 | 2115.72 | 18 | — | 미검증 | NOT_RUN | UNBOUND | 승격 보류 |
| Supertrend | WATCH | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 미검증 | NOT_RUN | UNBOUND | 승격 보류 |
| Squeeze PANIC-long | DEV | 30m | 33 | — | 30.30% | — | — | — | — | — | 24.36 | 1.376 | 878.19 | 8 | — | 미검증 | NOT_RUN | UNBOUND | 승격 보류 |
| MR V1 | DEV | — | 57 | 0.3501 | 56.14% | — | — | — | — | — | 5.40 | 1.183 | 623.46 | 5 | — | 미검증 | NOT_RUN | UNBOUND | 승격 보류 |
| Micro EDGE | fresh 부족 | 5m | 18 | — | 44.44% | — | — | — | — | — | 12.18 | 2.447 | 48.04 | 3 | — | 미검증 | NOT_RUN | 기존 저장 0; stale | 승격 보류 |

출처: `backend/research/rebuild/economic7_improvement_sprint_v1_results.json`. `supertrend_regime`은 적격 specialist 수치가 없다. 모든 TF는 기존 구현의 명목 TF이며 UTC 격자/완료시각 결함을 새 자료에 승계하면 안 된다.

## Router/portfolio

| evidence | T | Net bps | Net/T bps | PF | DD bps | maxLS |
|---|---:|---:|---:|---:|---:|---:|
| 기존 Router V2 development | 355 | 12092.74 | 34.06 | 2.211 | 1646.95 | 14 |
| 이번 fresh/rolling portfolio | — | — | — | — | — | — |

| state | payer strategy | old risk | new risk | receiver | receiver-valid-signal | cash fallback | realized delta |
|---|---|---|---|---|---|---|---|
| HOLD_PROVIDER_UNBOUND | — | — | — | — | 미결속 | HOLD/CASH adapter만 검증 | 미실행 |

기존 V2는 같은 hour의 후행 신호, 미완료 1h feature, cutoff 이후 확정 손익을 참조할 위험이 있다. 새 어댑터는 exact decision cohort·available_at·결과 관측시각·실제 위험예산·GREEN 수신자·중복 setup을 검사한다. 원본 결과는 변경하지 않았다.

| 기존 개발 월 | Net bps |
|---|---:|
| 2026-03 | -457.00 |
| 2026-04 | +171.84 |
| 2026-05 | -241.51 |
| 2026-06 | +5441.67 |
| 2026-07 | -892.56 |
| 2026-08 | +7782.19 |
| 2026-09 | +288.10 |

월표는 부분 월을 포함하는 이미 관찰된 history다. fresh 월별 성과·tail/winner concentration·portfolio 상관·노출/NAV는 미검증이다.

## 12/24개월 자료

- 범위: 2025-09-15 00:00 UTC → 2026-09-15 00:00 UTC.
- BTC/ETH/SOL/XRP/LINK/DOGE 각각 525,596개 실제 1분봉; 합계 3,153,576개.
- 각 symbol의 2026-02-13 20:32–20:35 UTC 4개 봉 결측; 총 24개. 좁은 재조회에서도 BTC 결측 확인.
- 결측 전/후 연속 구간과 gap-day prefix를 출처·hash로 보존. 완전한 UTC15/30/60분 버킷만 생성.
- 24개월 전 첫 BTC 경계는 빈 응답. 최대 역사 지원기간 전체를 확정한 것은 아니다.
- volume unit 및 신규1m time 의미 미결속. 전체12개월 canonical 경제권한 HOLD.
- `HISTORY_COVERAGE_RECEIPT.json`과 3개 manifest가 실제 수집 결과다.

## Fresh/지속 수집

- BTC/ETH raw `@incrDepth` + `@trade`: 60초에 수신 1,184개 = depth453 + trade716 + ACK4 + ping11.
- 원문 gzip/JSON, ACK, hash chain, fsync/checkpoint, 단일 writer, 2GiB 제한.
- systemd `zel-economic7-raw-forward-20260915.service` 동작; SIGTERM 후 자동 restart1회·PID변경·checkpoint증가·새 데이터 수신 확인.
- raw archive는 거래 결과 producer가 아니다. 7 lane frozen setup/entry/exit producer 연결은 미완료.
- `RAW_CAPTURE_PROBE.json`, `RAW_RECOVERY_RECEIPT.json`, `FROZEN_ROUTER_RECEIPT.json` 참조.

## Material

| material | old grade | role | change | marginal Net | ΔPF | ΔDD | T retention | behavior cosine | new grade | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| rbreaker_like | C | entry_quality | 없음 | — | — | — | — | — | C | NOT_RUN_SOURCE_GATE |
| rsi_swing_fail | C | exit_or_risk | 없음 | — | — | — | — | — | C | NOT_RUN_SOURCE_GATE |
| trend_ma_macd | C | entry_quality | 없음 | — | — | — | — | — | C | NOT_RUN_SOURCE_GATE |
| turtle_trend | C | entry_quality | 없음 | — | — | — | — | — | C | NOT_RUN_SOURCE_GATE |
| alpha_combo | D | veto/exit 제한 | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| anchor_vwap_trend | D | veto/exit 제한 | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| ema_ribbon_scalp | D | veto/exit 제한 | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| grid_rebalance | D | exit_or_risk | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| obv_trend | D | context_filter_or_veto | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| pivot_reversal | D | context_filter_or_veto | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| vol_spike_fade | D | exit_or_risk | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| vwap_revert | D | context_filter_or_veto | 없음 | — | — | — | — | — | D | NOT_RUN_SOURCE_GATE |
| bb_revert | HOLD | exit_or_risk | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| fvg_revert | HOLD | context_filter_or_veto | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| liquidity_sweep | HOLD | L2 결속 후 execution | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| mfi_rsi_div | HOLD | exit_or_risk | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| range_fade | HOLD | exit_or_risk | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| scalp_snap | HOLD | L2 결속 후 execution | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| session_bias | HOLD | exit_or_risk | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |
| sr_levels | HOLD | context_filter_or_veto | 없음 | — | — | — | — | — | HOLD | NOT_RUN_SOURCE_GATE |

A0/B0/C4/D8/HOLD8 유지. 새 B/A 검토는 실제 부모·단일역할·원자료·비용·구간 및 실행 전 사전등록 marginal 기준의 해시 결속이 필요하다. 기존 SSOT에 없는 일괄 ΔNet/ΔPF/DD 조건을 임의 추가하지 않았다.

## Fusion

| composite | materials | roles | prereg rule | T | net/T | PF | DD | OOS | fresh | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 없음 | 검증 B 없음 | — | — | — | — | — | — | 미실행 | 미실행 | NOT_RUN_NO_B_MATERIAL |

## 검증과 재개

- 통합 pytest132 PASS +8 subtests. 신규5모듈/5테스트 실제 precommit Black/Ruff/Mypy PASS; 검사 생략 없음.
- recovered3모듈의 타입/형식 수선, 원본 보존, 알고리즘 AST 동일 검증.
- 기존 정책3개 및 evaluator self-test PASS; 이미 완료한 경제 replay는 재실행하지 않음.
- PR/merge/master CI의 최종 값은 `MERGE_RECEIPT.json`에 기록한다.

다음 재개는 아래 결손을 해결하는 지점이다. 기존 완료 데이터·테스트·실험을 처음부터 반복하지 않는다.

1. 1m source time/volume 의미를 해당 원응답·normalizer로 결속. gap은 채우지 않고 SSOT 적격구간 정책으로 처리.
2. frozen7 setup/entry/exit 공급자, 최신 stale/exposure 및 비용 authority, MR2leg를 연결. raw archive를 거래 ledger로 오인하지 않음.
3. 데이터/비용/규칙/구간 해시를 중앙 registry에 등록한 미실행 후보만 실행. legacy import 전용0예산은 후속 경제 승인 제한이 아님.
4. 실행 전 rolling calendar·inspection/formation/embargo·DD/LS/concentration/sample acceptance를 결속. 이전180일 및 미래에 학습한 규칙을 과거 fresh OOS로 표시하지 않음.
5. 실제 fresh/rolling/portfolio marginal 검증 후에만 승격. B없으면 fusion 계속 보류.

주문·Live 권한은 BLOCKED. 이 문서는 전체 campaign 완료 또는 수익개선 PASS receipt가 아니다.
