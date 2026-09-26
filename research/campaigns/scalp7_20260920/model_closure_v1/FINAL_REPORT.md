# 원래 25개 모델 연결 증분 결과

범위: `G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1`.

**실제 수익 개선은 아직 측정하지 않았다. 신규 FULL 0회이며 T·WR·Net·DD·승리 훼손은 미실행(null)이다.** 이번 결과는 PR #1343의 부분 구현을 수량·주문·청산·계좌 평가까지 연결한 연구 모델 7개와 시간순 실행·비교 경로다. 원형 전체 재현 인증, 채택, C→B, B→A는 0개다. G4 전체 및 원래 25개 전체 구현은 완료되지 않았다.

아래 5개를 동일한 12개월 자료·6개 심볼·비용·구간에 결속하는 최소 신규 배치로 최종 동결했다. 원래 25개 중 구현된 6개 행에는 Noise의 `trend_rider/session_bias` 별칭이 포함된다. 나머지 19개 행의 미완료는 [COVERAGE.md](COVERAGE.md)에 전부 남겼다.

| 모델 | 비교 역할·실제 구현 | 신규 T / WR / Net / DD | 실행 상태 |
|---|---|---|---|
| ST30_STRUCTURAL_CONTROL_V1 | 방향 전환→확장→눌림→재개; 구조 stop·반대 방향/세션 청산 | 미실행 / 미실행 / 미실행 / 미실행 | 신규 FULL 제안 1회 |
| ST30_COMPLETED_BAND_TRAIL_V1 | 같은 진입·수량·공통 청산; 완료봉 Supertrend band 추적만 변경 | 미실행 / 미실행 / 미실행 / 미실행 | 신규 FULL 제안 1회 |
| sr_levels_30m_prior_utc_day_box_breakout_control_v1 | 이전 완결 UTC 일봉의 고정 박스; 첫 돌파 진입·구조 실패 청산 | 미실행 / 미실행 / 미실행 / 미실행 | 신규 FULL 제안 1회 |
| sr_levels_30m_prior_utc_day_box_intraday_v1 | 같은 박스·위험·관리; 이후 retest/reclaim 진입으로 변경 | 미실행 / 미실행 / 미실행 / 미실행 | 신규 FULL 제안 1회 |
| NOISE_OPPOSITE_BAND_UTC30_RESEARCH_V1_FIXED_SLEEVES | 14일 같은 슬롯 Noise·30m 반대 band·UTC 종료; 6개 고정 자본 sleeve | 미실행 / 미실행 / 미실행 / 미실행 | 독립 새 기준본 1회 |
| ANTI30_CAUSAL_FLAG_PIVOT_V1 | 추진→작은 flag→재개; 진입 후 확정 반대 pivot 관리 | 미실행 / 미실행 / 미실행 / 미실행 | 역사 PIT tick 증거 부족 |
| liquidity_sweep_15m_daily_soup_intraday_v1 | 실제 DAILY20·극값 나이4일·회복 주문; 별도 intraday 관리 | 미실행 / 미실행 / 미실행 / 미실행 | 역사 PIT tick 증거 부족 |

ST의 청산 대조, SR의 진입 대조는 각각 단일 변경 축이다. Noise는 기존 PR #1341 Rider의 같은 조건 child가 아니므로 그 결과와 단순 차감해 개선을 주장할 수 없다. Noise의 6개 심볼은 같은 모델의 고정 sleeve이며 B×B fusion 또는 독립 재료 6개가 아니다. Anti/Soup의 코드 완결성과 실제 tick 자료 준비는 구분한다.

경제실행 권한은 첨부 [START_WORK.txt 5번](../implementation_v1/source_package/START_WORK.txt)을 따른다. 기존 PR #1341의 승인 4회는 이미 모두 완료됐다. 새 상한을 만들거나 옛 예산을 재사용하지 않고, 새 승인이 없으면 준비된 기준본·필요 대조군의 최소 수와 원래 25개 미완료를 함께 산정하라는 지시다. 이에 따라 **최소 신규 FULL 5회**를 제안하며 이번 증분에서 예약·실행하지 않았다. 이는 옛 승인 4회를 재확인하는 요청이 아니다. 구현·시험은 이 권한과 별개로 진행했다.

**이전 PR #1341의 실제 결과는 아래처럼 보존했다. 이번 증분의 신규 성과가 아니다.** rolling 245일, 금액은 동일 원금 기준 거래 bps 합이며 계좌 수익률·계좌 평가 DD가 아니다.

| 이전 비교 | T | WR | Net 1x (bps) | Net/T (bps) | PF | DD (bps) | MaxLS | Net 2x (bps) | 부모 승리이익 보존 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Squeeze SQ0→SQ2 | 25→13 | 48.00→46.15% | 1520.49→230.43 | 60.82→17.73 | 1.912→1.465 | 576.67→171.06 | 3→3 | 1148.69→37.56 | 21.06% |
| Rider R15→R30 | 2147→1970 | 21.66→20.76% | -33115.78→-35652.53 | -15.42→-18.10 | 0.675→0.652 | 37403.11→40086.92 | 39→41 | -65169.10→-65048.26 | 69.69% |

SQ2는 DD 감소보다 승리·Net 훼손이 컸고 R30은 비용 1x Net·DD·연패가 악화됐다. 당시 채택 0개와 T↑·WR↑·Net↑·DD↓ 동시 달성 0개를 유지한다. 원문·상세 구간 및 승리 귀속은 [기존 최종 보고](../economic_development_v1/FINAL_REPORT.md)에 있다. 같은 경제실행은 반복하지 않았다. PR #1340의 HG/RSI/Break/SR 실패도 보존하며 이번 새 구조를 기존 실패 취소로 표시하지 않는다.

자료·비용·구간을 실제 caller에 결속했다. 대상은 2025-09-15~2026-09-15의 365일·6개 BingX perpetual 심볼이다. 심볼별 결측 4분을 보존하고, 최초 90일 문맥·별도 validation 30일·rolling 245일 창을 분리한다. 구간 경계에서도 자본·포지션 점유는 연속하고, 성과를 각 구간에 귀속한다. 따라서 이전 캠페인의 FLAT_INDEPENDENT_WINDOW 실행과 같지 않다. 이미 관찰한 개발 이력이므로 fresh/OOS로 승격하지 않는다. 2x는 같은 체결·수량의 비용 재계산이며 추가 FULL이 아니다.

현재 역사 funding은 미확인이다. 준비 모델의 비용은 고정 참고 수수료·impact·spread이고 **funding 제외 연구 손익**으로 표시한다. 이를 완전한 perpetual 계좌 Net이나 실제 거래소 체결로 해석할 수 없다. 실제 주문·호가 queue·마진·청산은 재현하지 않는다. 결측 구간의 소유 포지션은 미해결 상태를 유지하며 손익을 만들어 넣지 않는다.

변경 함수는 4개 모델 모듈의 `compile_model/create_order/exit_update` 및 Noise target·fill 회계, 자료 모듈의 genuine 입력/시각 결속, runner의 `freeze_model/verify_binding/admission/run_authorized`, 비교 모듈의 같은 원인·승리 훼손 계산이다. 이전 동결 source·실행 코드는 보존했다. 관련 synthetic 테스트·독립 검산·자료 결속·기존 봉인 검증 및 연구 전용 CI를 추가했다. DRAFT_ROWS 및 과거 감사의 결속 대기 문구는 단계별 이력이며 MODEL_CLOSURE.json의 final_binding과 5개 실제 freeze로 갱신한다. 통합 Scalp7 1605개 시험과 정상 hooks·기존 8개 저장 봉인·frontend 검증은 PASS다. 이후 저장 검증기 변조 회귀의 최종 추가 개수·결과와 정확한 최종 코드 SHA는 [VALIDATION.json](VALIDATION.json), 준비 identity는 [PREPARED_EXECUTION_REQUEST.json](PREPARED_EXECUTION_REQUEST.json)과 `freezes/`, 보존 확인은 [복구 감사](audits/RECOVERY_20260926.json)를 따른다. 과거 중간 검토의 SHA와 최종 봉인을 혼합하지 않는다.

PR·CI·병합 SHA·master 고정본 검증은 해당 PR 및 Issue #1334의 최종 영수증에 연결한다. 이 문서의 테스트·코드 완결 주장은 경제 개선을 대신하지 않는다. 신규 포트폴리오 경제실행·fresh 거래·C→B·B→A는 없고, 독립 fresh B 2개가 없어 B×B는 시작할 수 없다.

배포는 불필요하다. 주문·LIVE·서비스 변경·공식 승격·새 유료 지출·G5 이후 작업은 계속 금지다. 위험은 연구용 이식 가설, funding 미확인, 계좌/체결 모델의 한계와 남은 19개 구현 공백이다. 통합 문제 시 이번 연구 증분만 revert하고 과거 결과·봉인·완료 identity는 보존한다. 다음 재개 지점과 정확한 함수 서명은 [WORK_NEXT.txt](WORK_NEXT.txt)에 있다.

