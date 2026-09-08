# 동일 후보 독립 대조

판정: **동일 후보 — 신규 경제 실행 불필요**.

- 요청 scope: `KR3_ORIGINAL_ANCHOR_FAILURE_AFTER_PR1221_V1`
- 기존 PR #1222 scope: `KR3_WHOLE_FAILURE_AFTER_PR1221_V1`
- 고정 검토 head: `e97e032044114ff81a1f3aa4be48ef8a17a77e56`
- 대조 방식: 코드 3개·합성시험 소스 1개 정적 읽기. 시장자료 읽기·경제 실행·원격 쓰기·코드 변경 0회.

## 기능 대조

| 요구 | 코드 근거 | 판정 |
|---|---|---|
| Direct parent is original KR3 | from ... import keltner_kr3_v1 as parent; original parent blob matches expected | MATCH |
| Original signal, EMA, next-open entry, reference reservation | Uses parent.kr.replay under a temporary path-only hook; i=signal_index, ei=i+1, signal_low=rows[i].low; no D mechanism import | MATCH |
| First suppressed breach is preserved and cannot trigger same bar | state.status==SUPPRESSED AND index>state.index before strict close comparisons | MATCH |
| Later completed close below original frozen low and current EMA50 | additional_failure compares current row.close<signal_low AND row.close<ema50[j] | MATCH |
| Original exit priority | Timeout processed first; reason order EMA -> allowed-low -> runner -> added failure | MATCH |
| Next-open execution without future HLC | After trigger raw geometry ends at j and fills only rows[j+1].open | MATCH |
| Out-of-window next open remains censored and pending | If xi absent or open_ts>=end, breaks to CENSORED with pending_exit_trigger retained | MATCH |
| No D delay/recheck or shifted references | No decision_index or exit_anchor_index; no p.MODES[3], delay6 or D replay | MATCH |
| Disabled is exact KR3 | enabled=False directly returns parent.replay(rows,bundle,**kw) | MATCH |
| SL, TP, add-on, allocation and leverage unchanged | Only held exit path copied with one additional predicate; no entry/sizing edits | MATCH |

## 기존 합성시험 증거의 범위

기존 시험 소스 17개를 읽었다. 최초 유예·엄격한 후속 발동·고정 원형 저가·다음 시가 gap·미래 HLC 제외·EMA 및 timeout 우선·기존 allowed-low·정상 hook 복원·기존 참조예약 보존·disabled KR3 일치를 명시적으로 확인한다. 이 감사에서 시험을 재실행하지 않았으며 CI PASS를 직접 판정하지 않았다.

| 명시적 증거 결손 | 근거 |
|---|---|
| Intermediate evaluation start, warmup prefix and original coordinates | All replay invocations have eval_start_ms=0; no nonzero-start fixture |
| Reference checkpoint restart | No reference_checkpoint invocation; test_serialized_suppression_preserves_decision covers only local suppression predicate state |
| Input immutability | No rows/bundle before-after deep equality assertion |
| Temporary hook restoration under exception | Normal-path hook identity is asserted; exception restoration not explicitly tested |
| Next open present in input but outside eval window | Pending test truncates input so next bar does not exist; does not exercise xi present and open_ts>=end |

이 결손은 코드의 실제 오작동을 뜻하지 않는다. 상속과 `with patch`가 해당 동작을 보존하는 근거는 있으나, 사용자가 요구한 모든 인공시세 시험이 사전에 수행됐다고 보고할 수 없다. 필요하면 경제 실행 없이 합성시험만 보강하고, **경제 결과 이후 추가한 검증**이라고 기록한다.

## 불변성과 해석

직접 KR3 blob은 `b6b42ad0a8b92ff1f5717adc832d962bfbc9f509`, D2 참고 blob은 `8b9edcf879a589acfc88fd9dc585e02a9d4eabc7`로 요청한 원형과 일치한다. 후보 blob은 `d75a34edb59efce3a6ab3e581561401f0e1570ef`, 시험 blob은 `877455ffde3823a27b996770a2be319ddf21094c`이다.

진입 규칙 보존은 FULL 진입집합 동일을 보장하지 않는다. 청산 변화로 실제 점유가 달라져 신규·제외 진입이 발생할 수 있다. 부모·예산·저장 경제 결과의 실제 유효성 검증은 root가 담당한다. root가 기존 50후보·80평가 실행을 확인했다면 그 이력을 승계하며 후보 51 또는 추가 FULL 2회를 만들지 않는다.

