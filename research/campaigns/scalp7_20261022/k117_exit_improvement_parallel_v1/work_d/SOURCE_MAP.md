# K117 비용교차·BE 보호 원문 및 코드 결속

범위는 `8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8`의 동결 117거래 기준선과 수동 계측이다. identity는 `scalp7_k126_veto_objective_completed_fresh_touch_v1`이다. 기존 K126/C114 경제결과를 K117로 재명명하지 않는다.

## 정확한 질문 → 원문 → 코드 → 반례

| 질문 | 실제 읽은 1차 자료와 지원 내용 | K117 코드에 적용한 확인 | 반드시 유지할 반례/한계 |
| --- | --- | --- | --- |
| 이름이 BE이면 비용 후 손실도 항상 없어지는가? | [TradeStation 공식 SetBreakEven](https://help.tradestation.com/10_00/eng/tsdevhelp/elword/word/setbreakeven_reserved_word_.htm)은 지정 이익 도달 후 본전 청산을 설명하고 수수료·슬리피지가 계산에 포함되지 않음을 명시한다. | ZEL의 기존 `exit_update`는 진입 시 `frozen_cost_bps`와 기존 2bps를 이미 stop 가격에 반영한다. 따라서 외부 함수의 비용 누락을 ZEL 결함으로 옮겨 말하지 않는다. 실제 예약 stop·체결가격·원래 명목 대비 gross·비용·net을 나란히 관측한다. | gap 체결, 추가 carry, 부분실현 후 잔량, 비용 2배의 사후 스트레스는 각각 다르다. 기준비용 BE를 사후 2배 비용에서도 본전인 것처럼 표시하지 않는다. |
| 금액·전체포지션·계약당 단위를 혼용하면 보호가격이 맞는가? | [공식 SetStopPosition](https://help.tradestation.com/10_00/eng/tsdevhelp/elword/word/setstopposition_reserved_word_.htm)은 전체포지션 기준, [공식 SetStopContract](https://help.tradestation.com/10_00/eng/tsdevhelp/elword/word/setstopcontract_reserved_word_.htm)은 계약/주당 기준과 선물 point-value 변환을 설명한다. 이 두 페이지는 단위 질문만 해결하려고 추가로 읽었다. | K117 엔진의 `remaining`은 원래 명목의 비율이고 `realized_parts_bps`도 원래 명목 기준이다. 실제 계약수·USDT·레버리지로 바꾸지 않는다. `_close_row`의 가중 잔량 계산과 부분실현 합산을 검산한다. | 비율을 계약수로 취급, quote 금액을 bps에 합산, 원래 명목 대신 잔량 명목으로 비용을 다시 나누기, 비용을 부분청산마다 중복 차감하기를 합성 반례로 둔다. |
| BE를 더 당기면 순익·DD가 개선된다고 단정할 수 있는가? | [Kevin Davey 본인 글](https://kjtradingsystems.com/algo-trading-breakeven-stops.html)은 BE 포함/미포함 비교 틀을 제시하며 최적화된 개선의 낙관성과 사후 규칙 추가의 과적합을 경고한다. 자체 시스템 검증과 외부 구간 검증의 필요성을 설명한다. | 기존 stop을 없애거나 나쁘게 되돌리지 않는다. 기존 arm·partial·runner·terminal 순서를 전부 계측하고, 손실 회피뿐 아니라 일반·큰·회복 승리 훼손을 A의 같은 기회 및 전체 시간순 평가에서 확인한다. | 28개 비용교차 거래만 골라 stop을 조정하면 winner 반례를 놓친다. 관측 MFE는 실제 청산 가능 이익과 다르다. 저자의 최적화 수치나 발동 값을 가져오지 않는다. |

TradeStation 본문 및 관련 단위 문서는 공개 본문을 읽었다. Davey 글도 공개 본문을 읽었으나 도표 원데이터, 제시 코드 이미지의 전체 실행환경, 저자의 전체 계좌감사 자료는 확인하지 않았다. 외부 수익이나 개선 수치는 ZEL 성과·임계치·보장으로 사용하지 않는다.

## 동결 원본과 실제 실행 순서

다음 로컬 보관 원본의 바이트 SHA256을 확인한 뒤 관련 함수 본문을 읽었다. 원본은 변경하지 않았다.

| 원본 | SHA256 | 확인 지점 |
| --- | --- | --- |
| `backend/research/rebuild/scalp7_positive_lanes_v2.py` | `b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2` | `exit_update`: closed-prefix/available 시각 검사, 관측 1R 후 비용 포함 BE, 기존 scratch·runner·partial |
| `backend/research/rebuild/scalp7_execution_v2.py` | `d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1` | `_single`: terminal 우선순위·관측 MFE·partial·stop 적용; `_close_row`: 잔량 가중 gross와 net |

`_single`의 실제 순서는 이미 예정된 next-open exit → 현재 유효 stop/gap → 기존 target → MFE/MAE 갱신 → 완성봉 가용성 확인 → callback → partial 체결/실현분/잔량 갱신 → 단조로운 next-stop 변경 → 다음시가 청산 예약이다. 따라서 현재 stop에 걸려 종료되는 봉의 high/low로 사전에 BE를 새로 arm하거나 그 봉의 이익을 회수했다고 계산할 수 없다. callback이 돌려준 next-stop은 현재 봉의 이미 지난 경로에 소급하지 않는다.

`exit_update`가 초기 BE stop을 제안하더라도 엔진은 long에서 `max(old_stop, proposal)`, short에서 `min(old_stop, proposal)`로 보호를 되돌리지 않는다. 기존 runner가 더 강한 stop을 제안한 경우에도 이 단조성을 보존해야 한다. 수동 observer는 해당 분기의 입력과 결과를 복사해 기록할 뿐 반환값이나 포지션을 변경하지 않는다.

## 보호 명칭과 수식 검산

기존 가격 제안은 `P_BE = E × (1 + side × (c_ref + 2) / 10000)`이다. `E`는 진입가격, `c_ref`는 진입 시 고정한 참조비용의 trade-bps이며 2bps는 기존 Keltner 코드의 값이다. 새 숫자를 선택한 것이 아니다.

원래 명목 기준 부분실현을 `p`, 잔량 비율을 `r`, 실제 terminal 체결의 가격수익률을 `b`, 원장 비용을 `c_booked`라고 하면 기존 엔진의 전체 거래 net은 `p + r × b − c_booked`다. 실제 terminal이 제안 BE에 정확히 체결된 경우에만 `b = c_ref + 2`가 된다. 그러므로 부분실현이 없고 `r=1`, gap도 없고 `c_booked=c_ref`일 때 +2bps가 성립한다. 부분실현·추가 carry·gap이 있으면 그 식의 해당 항목을 직접 검산해야 한다.

사후 2배 스트레스는 같은 저장 gross에서 `2 × c_booked`를 빼는 별도 보고다. 그 비용 가정을 그대로 실행 stop에 넣는 것은 새로운 정책이며 기존 BE의 단순 회계수선이 아니다. `2×cost+2bps` stop을 정답으로 고정하거나, 미래 MFE/최종손익으로 실행 분기를 만들지 않는다.

이 검토에서 기존 잔량 회계 수식이 틀렸다는 증거는 발견하지 않았다. 부분이익을 반영해 목표 net에 맞춘 계산값이 기존 stop보다 나빠질 수도 있으므로, 그런 재계산을 보호 개선이라고 적용할 수 없다. 현 단계의 근거 있는 산출물은 **passive BE observer와 보호 회계 검산**이다. 별도 exit 후보를 정당화하려면 A가 생성할 실제 상태 trace에서 구체적 결함 또는 관측 가능한 확인 구조를 먼저 입증해야 한다. 숫자 최적화로 그 결손을 메우지 않는다.

## 확인된 것과 아직 확인하지 않은 것

사용자 실행문이 지정한 25건 BE 종가 일치와 24건 약 +2bps는 저장행/원본 수식의 확인 대상이다. 그것만으로 최초 arm 시각, stop의 실제 유효 봉, partial 상태, runner 우선순위가 각 거래에서 전부 확인된 것은 아니다. 나머지 비용교차 3건의 scratch/시간청산은 BE stop 체결과 따로 보고한다.

이번 원문 검토는 신규 가격 replay·경제 FULL·시장 API·Actions·원격 실행을 하지 않았다. 원형 117건 전체에서 observer-disabled 동일성과 event 순서를 확인하는 명령은 A가 기존 단일 경제슬롯에서 실행한다. 경제효과·연패 감소·계좌 NAV·미사용 OOS·실거래 PASS를 주장하지 않는다.

## 원문 주장 → 보호하는 함수 → 실행 가능한 시험

아래 이름은 전달된 시험 파일의 실제 method다. 합성 반례의 변경 callback은 시험 전용이며 실행 후보나 SSOT 설정이 아니다. 저장 원장 검산은 가격 replay와 별도다. 시험 통과 여부는 실행 영수증에서 확인한다.

| 원문에서 가져온 검증 질문 | 보호하는 함수/행동 | 정확한 시험 method |
| --- | --- | --- |
| TradeStation의 명목 BE와 비용 후 BE 구분 | `protection_accounting.protection_at_price`; 기존 `positive.exit_update`의 비용 포함 가격을 long/short 양쪽에서 검산 | `test_accounting_and_ledger.AccountingTests.test_long_short_existing_cost_aware_BE` |
| 전체포지션과 잔량의 분모 구분 | `execution._close_row`, `BEObserver.on_partial`, `protection_at_price`; 부분실현+잔량 가중 gross | `test_accounting_and_ledger.AccountingTests.test_partial_realized_amount_uses_original_notional`; `test_be_observer.PassiveObserverTests.test_partial_actual_fraction_and_remaining_gross_net_accounting` |
| 전체 금액·계약당 단위 혼동 거부 | `protection_accounting.quote_amount`, `_state`; 명시된 실제 수량·승수만 금액으로 변환 | `test_accounting_and_ledger.AccountingTests.test_amount_conversion_requires_explicit_actual_quantity_unit`; `test_accounting_and_ledger.AccountingTests.test_fraction_unit_nonfinite_and_negative_cost_checks` |
| 사후 비용 스트레스는 실행 stop 규칙과 별개 | `stress_after_outcome`, `protection_at_price`, `saved_ledger_audit.build_evidence` | `test_accounting_and_ledger.AccountingTests.test_stress_is_posthoc_and_not_an_execution_input`; `test_accounting_and_ledger.SavedLedgerTests.test_extra_carry_is_separate_and_stress_does_not_alter_entry_cost` |
| 계산상 보호가격과 체결 가능한 가격은 다름 | `inverse_floor_price`가 stop update를 반환하지 않음; `_single`은 실제 gap-open 체결 | `test_accounting_and_ledger.AccountingTests.test_inverse_with_partial_is_algebra_only_not_stop_change`; `test_be_observer.PassiveObserverTests.test_gap_after_be_uses_actual_next_open_and_can_be_negative`; `test_be_observer.SyntheticRefutationTests.test_cost2_level_beyond_completed_close_is_not_an_immediate_fill` |
| Davey의 발동·실행시점 구분을 우리 계약에 맞춰 검산 | `BEObserver.on_callback_after`, `on_stop_applied`, `on_bar_start`; 기존 stop-first와 pending precedence 보존 | `test_be_observer.PassiveObserverTests.test_long_and_short_be_arm_next_bar_and_exact_return_parity`; `test_be_observer.PassiveObserverTests.test_same_bar_stop_precedes_favorable_extreme_be_and_partial`; `test_be_observer.PassiveObserverTests.test_pending_exit_precedes_stop_and_mfe_on_next_bar` |
| 규칙 추가의 장점만 보지 않는 before/after 반례 | 동결 `positive.exit_update` 대 시험 전용 조기보호 callback; observer는 양쪽 결과에 간섭하지 않음 | `test_be_observer.SyntheticRefutationTests.test_early_protection_can_remove_an_ordinary_winner`; `test_be_observer.SyntheticRefutationTests.test_early_protection_can_remove_a_large_runner_winner`; `test_be_observer.SyntheticRefutationTests.test_early_protection_can_remove_a_recovery_winner`; `test_be_observer.SyntheticRefutationTests.test_early_protection_can_also_avoid_a_later_loss` |
| 최적화된 비용 버퍼가 기존 승리를 훼손할 수 있음 | 시험 전용 `toy_copy_cost2_into_be`; 기존 runner 보존 반례 | `test_be_observer.SyntheticRefutationTests.test_copying_double_cost_buffer_can_cut_an_existing_runner`; `test_be_observer.PassiveObserverTests.test_partial_then_runner_is_monotonic_and_not_double_counted` |
| 원문을 근거로 현재에 미래 라벨을 주입하지 않음 | `instrument_single`의 passive/disabled 동일성, callback의 closed prefix, 저장행의 미실행 trace 표시 | `test_be_observer.PassiveObserverTests.test_disabled_is_original_function_identity`; `test_be_observer.PassiveObserverTests.test_callback_gets_only_closed_prefix_and_future_suffix_changes_nothing`; `test_be_observer.PassiveObserverTests.test_future_history_injected_into_callback_is_rejected`; `test_accounting_and_ledger.SavedLedgerTests.test_exact117_and_all71_winners_exported_without_new_trace_claim` |
| 비용교차 부분집합을 전체 117건으로 과장하지 않음 | `saved_ledger_audit.checked_inputs`, `build_evidence`; 25/24/나머지3 구분과 고정 원문 검증 | `test_accounting_and_ledger.SavedLedgerTests.test_28_split_25_BE_24_two_bps_one_partial_algebra_only`; `test_accounting_and_ledger.SavedLedgerTests.test_wrong_cardinality_future_feature_and_duplicate_fail`; `test_accounting_and_ledger.SavedLedgerTests.test_hash_change_rejected_and_output_is_exclusive` |

저장소 루트에서 실행하는 명령:

```bash
python -m unittest discover \
  -s research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/work_d \
  -p 'test_*.py' -v
```

동결 원본이 기본 탐색 위치에 없으면 `K117_FROZEN_SOURCE_DIR`를 위 SHA가 일치하는 두 원본 파일의 디렉터리에 지정한다. 저장행 시험까지 실행하려면 `K117_BASELINE_DIR`를 정확한 K117 `SUMMARY.json`·`ROWS.json.gz`·`EXECUTION_FREEZE.json` 보관 디렉터리에 지정한다. 저장 원문이 없을 때 표시되는 skip은 검산 PASS로 세지 않는다.
