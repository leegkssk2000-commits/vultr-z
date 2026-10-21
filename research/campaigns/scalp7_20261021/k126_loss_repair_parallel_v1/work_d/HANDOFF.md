# K126 동시노출·진입허용 준비본 — A 인계

수신: **CLOUD_WORK_COORDINATOR_ISSUE1358_V1 / A**. Scope: `K126_WORST8_CONCURRENT_LOSS_CONTROL_D_V1`.

**코드·인과적 원장 연결·시험 완료. 실제 공통 위험예산/수량 입력은 REQUIRED_INPUT.** C 완료를 기다리지 않았다. 이 준비본은 경제계산 시작이나 양수 성과 판정이 아니다. 신규 파일만 `work/zel-portfolio-coverage-20261021`에 `[skip ci]`로 저장한다. 기존 `e4c875213951ff0c9442bd9b2496478b6e71a903`, `94e4eb2433604c331a37397a8d5d1e5f0278c28c`와 이후 이력을 보존한다. 전달 커밋 및 재조회 증거는 #1358 인계 댓글에 고정한다.

## 정확한 기준과 계보

| 항목 | 고정 값 |
| --- | --- |
| 현재 비교 기준 | `81a12c422ee9329996d2f6b983267d2def490d4b` |
| 현재 원장 | `research/campaigns/scalp7_20261021/k126_native_structure_failure_v1/completion/ROWS.json.gz`의 `trades`, **126건** |
| 관리 identity | `scalp7_k126_native_pullback_invalidation_next_open_v1` |
| 진입 lineage | `scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1` |
| 현재 압축 원장 SHA256 | `5f45180aa762dc091c16e8fa2d208dcf027c16f795d9533911d2c11d73a30c77` |
| 현재 비압축 원장 SHA256 | `98eaa46994eb8c4e9d89e7e17bbb9a9cce97b86f6a3a727c11e8136da75a85f3` |
| 원대조군 보존 | `308bd2deb7acaaacf1adb582206e78262d72c9d1`, `carry_scenario_trades` **126건**. 앞선 관리 전 control **128건과 혼용 금지** |
| 진단 입력 | `4a5985e362959f8460726fb56780fc10eab04a8b`, `k126_worst8_parallel_20261021T2159Z/` |
| 원 엔진 ref | `6f7a42171dab54ff1be544304f44ee06fdd8f056` |
| 평가창 | `2026-01-13T00:00:00Z <= t < 2026-09-15T00:00:00Z`, 245일, 30분, 9개 독립 flat rolling window |
| 문맥 hash | `168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c` |
| 비용 snapshot SHA256 | `cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73` |

6종목 시세 SHA, windows, 코드/SSOT 출처는 `SSOT_FIELD_BINDING.json`에 있다. 비용은 기존 reference snapshot 및 기록된 추가보유 reserve 시나리오다. cost1x/2x는 같은 체결에서 비용만 1배/2배 차감하며, 역사적 실제 funding·계좌 NAV가 아니다. 현재 저장 결과 Net **7942.268973684915 / 6049.2458247083 trade-bps**, 원래 연패 **8 / 13**, 최악 연패액 **-1128.2251166863311 / -1946.766452879958 trade-bps**를 그대로 보존한다. 이 값은 새 D 성과가 아니다.

## 이번 구현

`causal_exposure.py`는 완료한 D `contribution_report.normalize`를 SHA 검증 후 재사용한다. 기존 날짜 집계나 `analyze.py`를 재실행하지 않고 저장된 원장·geometry·raw path를 결속하여 다음을 만들었다.

- `CAUSAL_EXPOSURE_EVENTS.json`: 126 진입 + 126 청산기록 + 126 손익확정 = **378개 이벤트**. 진입별 미결 동방향 노출, 이미 확정된 개별 손실과 승리, 동일시각 미확정 손익, 과거 window와 현재 window를 구분한다. `native_outcome_refs`는 파일의 `native_outcome_key_index`를 가리킨다.
- `DIRECTIONAL_COHORTS.json`: 전체 126건을 같은 방향·같은 window·양의 보유시간 겹침으로 묶는다. 연결군 65개 중 동시보유군 **19개: 전부 승리 3, 전부 손실 6, 혼합 10**. 연결군 전원이 동시에 열려 있다는 뜻은 아니며 실제 active segment와 최대 동시수를 함께 저장했다. 승리 **69건**, 기존 큰 승리군 **34건** 전부 포함한다. 큰 승리 정의는 기존 A의 사후 `net1x>0 and mfe_R>=2` 그대로이며 진입 조건으로 사용하지 않는다.
- `risk_admission.py`: 기본 비활성 순수 함수. 실제/예약 미결 노출을 하나의 총한도·방향별 한도에서 먼저 차감하고, 동일시각 완전한 신호 묶음을 공통 비율로 줄인다. 수량단위/통화/계약승수/step/minimum을 검증하며 내림 잔여량을 특정 종목에 재분배하지 않는다.
- `report_adapter.py`: 기존 동일명목 trade-bps 보고와 A의 공통 총위험 전체 chronology 비교를 분리한다. 후자는 exact source/window/cost 및 같은 위험계약, 실제 수량·quote 손익·예약/실행 영수증을 요구한다. 공통/추가/제외 거래, 승리 훼손, 일률 수량축소를 구분하고 NAV·alpha 개선을 자동 주장하지 않는다.

최악4포지션의 진입은 각 손실 확정보다 이르다. 03:30/04:30 진입 때 그4건의 미래 손실을 판단 feature로 넣지 않고 기존 이전 손실은 유지했다. 08:30 SOL 진입에서는 그때까지 확정된4건을 알고 있다는 경계를 검증했다. 같은 symbol/side 재진입을 같은 setup이라고 단정하지 않는다.

## 시간·위험 계약

원 엔진은 종목별 ownership만 가지며 종목 간 공통 위험 admission 선후는 정하지 않는다. 이번 보수계약은 **같은시각 ENTRY batch → 청산기록 → OUTCOME_KNOWN batch**다. 진입은 손익확정시각이 엄격히 이전인 결과만 본다. 같은시각 청산될 노출도 예산을 미리 해제하지 않는다. 실제126에는 진입/손익확정 동시시각이 2개 있고 혼합 승패 확정 batch는 5개다. 원래 연패는 원래 tie-order로 유지하며 104개 결과 batch로 연패를 재정의하지 않는다.

기존 position 내 pending exit·stop/gap·target·completed-bar·partial·next-stop 순서는 보존한다. stop update는 `available < decision` 및 `effective <= decision`일 때만 반영한다. Raw OHLC에는 실제 동적 stop/부분수량 trace가 없으므로 이를 추정해 예산을 해제하지 않는다. 이전 window 손익은 audit에 남기되 독립 window 사이의 새 loss policy carry를 자동 승인하지 않는다.

위험 단위는 명시된 하나의 quote currency다. 선형 instrument에서 `q * contract_multiplier * (방향별 현재가-유효stop 거리 + 당시 알려진 남은 비용reserve/baseunit)`를 사용한다. 이미 stop에 도달/통과한 snapshot은 0위험으로 처리하지 않고 체결 대사를 요구한다. `signal.meta.frozen_cost_bps`는 진입 당시 reference이고, 미래 보유비용이 들어갈 수 있는 최종 `row.cost_bps`는 admission에 넣지 않는다.

알려진 손익은 별도 audit다. 손익으로 예산을 자동 복구하거나 몇 연패/몇 시간 쿨다운을 만들지 않는다. 원문 적용 근거와 한계는 `SOURCE_APPLICATION.md`에 있다. 대칭 비례배분은 내부 구현 가설이며 CME 일별 상관을 30분 위험 할인이나 임계치로 이식하지 않았다.

## A가 채워야 할 정확한 입력

K126의 `remaining=1.0`은 정규화된 position fraction이다. 실제 수량·NAV·stop-risk 한도가 아니다. 발견한 production sizing은 BTC/ETH 전용 `FROZEN_PAPER_ONLY`, SSOT binding은 `HOLD_UNBOUND`이므로 해당 숫자를 K126에 적용하지 않았다.

필수 입력은 승인된 총/방향별 stop-risk 예산과 적용 범위, 실제/요청 수량과 선형 계약/step/minimum, 당시 mark·유효 stop·부분수량·비용reserve 및 각 가용시각, canonical setup-instance와 재진입 허가, 현재 미체결 예약까지 포함한 exposure snapshot, 완전한 동일시각 신호 batch다. 모두 정확한 source ref/SHA 및 계약 필드에 결속해야 한다. 상세 필드별 상태는 `SSOT_FIELD_BINDING.json`의 `required_input`과 `adapter_interface_fields_not_existing_ssot`에 있다. 합성시험 숫자는 SSOT 설정으로 저장하지 않았다.

## 안전한 사용 명령과 통합 지점

이 전달 커밋을 포함한 저장소 루트에서 아래 시험을 실행한다. `$K126_INPUT_ROOT`는 `INPUT_MANIFEST.json`의 정확한 commit/path/blob으로 받은 `current/`와 `diagnostic/` 입력 디렉터리다. 입력이 없으면 합성시험만 수행되고 저장126 시험은 skip임이 표시되므로, 전체 통과로 보고하지 않는다.

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover \
  -s research/campaigns/scalp7_20261021/k126_loss_repair_parallel_v1/work_d \
  -p 'test_*.py' -v
```

저장된126 인과적 연결만 재현할 때는 새 출력 디렉터리를 사용한다. 기존 산출물 덮어쓰기는 거부한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python -B \
  research/campaigns/scalp7_20261021/k126_loss_repair_parallel_v1/work_d/causal_exposure.py \
  --input-root "$K126_INPUT_ROOT" \
  --output-dir /tmp/k126_d_causal_audit_new
```

adapter API:

```python
from risk_admission import evaluate_batch
receipt = evaluate_batch(batch, bound_risk_contract, enabled=True, receipt=prior_receipt)
# contract 없음/누락/시간·단위오류 -> REQUIRED_INPUT, allocations=[]
# SYNTHETIC_ONLY는 합성시험 전용; 실제 owner 승인은 별도로 검증한다.
from report_adapter import saved_equal_notional, compare_common_total_risk
saved = saved_equal_notional(current_rows, authoritative_metrics=current_summary['child'])
comparison = compare_common_total_risk(a_control_receipt, a_candidate_receipt)
```

각 함수의 docstring과 시험 fixture에 JSON 입력 구조가 있다. 입력 proposals는 기존 native 진입·상태·window/symbol 점유 검사를 통과한 신호여야 하며, D의 수량 계산은 원래 거절·점유 규칙을 해제하지 않는다. `evaluate_batch`는 주문이나 예약 쓰기를 하지 않는다. A는 **snapshot 읽기 → complete batch 계산 → 영수증 저장과 전체 batch 예약 확정**을 원자적으로 연결하고 이후 batch에 pending 예약을 반드시 포함해야 한다. 재시작은 입력 SHA와 출력 영수증 SHA를 검사하며 같은 batch의 다른 입력을 거부한다. 이 준비본을 원 엔진에 단순 import해 종목별 순차 적용하면 대칭 계약을 깨뜨리므로 금지한다.

실제 차단 뒤의 다음 신호/점유 변화는 기존 경제 owner의 full chronology에서만 평가한다. 저장126에서 거래를 삭제하거나 전부 같은 비율로 줄인 표를 성과로 제출하지 않는다. 공통 총위험 비교에는 양쪽 run이 같은 한도계약을 사용했는지 확인하고 해당 A 영수증을 함께 게시한다. 이 Work가 경제 실행권·배정량을 갱신하지 않는다.

## 검증 영수증과 보존

**43개 시험 PASS: 합성 38개 + 실제 저장126 인과/무결성 5개.** 아직 확정되지 않은4손실, 이전 확정손실, 동시 혼합승패, 신호 순열 대칭, 기존/예약 노출, stop update 시각, 비용/수량단위, 승리군, 결측, setup 재진입, 재시작/영수증 변조, 계보/평가창/정밀합계를 검증했다. `SYNTHETIC_TEST_RESULTS.json`에는 각 시험 ID와 시험한 코드 SHA가 있다.

현재 실제 admission 및 공통위험 경제 결과는 `PREPARATION_RECEIPT.json`의 REQUIRED_INPUT 상태다. 경제 FULL·시장API·Actions·Paper/Live·주문·배포·runtime 쓰기 모두 0회. A/B/C 코드, root ops/tests, master/workflow, OWNER/CHECKPOINT/소비원장과 이전 D 결과는 변경하지 않았다.
