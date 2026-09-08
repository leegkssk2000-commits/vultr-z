# Candidate51 one-close recovery child — measured result

REJECT_NO_CUMULATIVE_ADOPTION

Same fixed nominal trade-bps. Both periods USED_DEV; opens marked with original costs. No account returns or G5 PASS.
C51 is the direct parent, KR3 the original cumulative control. No prior strategy was rerun.

|Period|Rule|Closed/open|WR %|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3|202/1|41.09|581.35|-318.58|1.825|1.273|10265.00|5744.23|11727.79|
|DEV2025|C51|202/1|42.57|556.13|-300.43|1.851|1.372|12900.53|8420.93|11267.44|
|DEV2025|C52|202/1|44.06|539.47|-314.95|1.713|1.349|12346.59|7863.95|11143.80|
|SEEN2026|KR3|75/4|33.33|717.76|-251.61|2.853|1.426|4746.58|3002.13|4093.69|
|SEEN2026|C51|75/4|36.00|662.26|-254.66|2.601|1.463|5040.20|3300.67|3997.48|
|SEEN2026|C52|75/4|36.00|662.26|-257.46|2.572|1.447|4905.97|3164.40|4093.69|

One nonpositive-mark breach may wait exactly one completed close; all original exits retain priority. This can enlarge losses. No assured recovery, stop price or positive fill.
Loss/winner, new/removed and open-state bridge: per-period ACCOUNTING_C51.json and ACCOUNTING_KR3.json.
Candidate51 stays preserved; no operational adoption follows this report. Counts52/84 include actual attempts; prior51/82 and all failures remain unchanged.
CI/merge closure is separate. Completed scope must become verify-only; no retry or automatic successor.

## 정확한 판정: 후보51 유지, 후보52 불채택

2025 WR은42.57→44.06%로 상승했으나 net−553.94bps, cost2−556.98bps다.2026 WR36%는 그대로이고 net−134.23bps, cost2−136.27bps, DD+96.20bps다. 목표8개 중2개만 충족했다. 비교대상은 KR3로 되돌리지 않았으며 후보51의2025/2026 개선분은 원형 그대로 보존한다.

|후보51 대비 동일 원신호 기여, trade-bps|2025|2026|
|---|---:|---:|
|기존 손실 감소/승리 전환의 이득|+348.48|+25.61|
|늦어진 청산으로 악화한 기존 손실|-902.41|-159.83|
|기존 승리 증가/훼손|0|0|
|신규/제외/완결↔미완결 전환|0|0|
|전체 종료net 증분|-553.94|-134.23|

부모51의 기존 승리86/27건과 그 이익은100% 보존됐지만, 더 오래 보유한 손실이 확대돼 총이익이 낮아졌다.2025 손실3건이 승리로 바뀌고 승리→손실은0건이며,2026 승패 전환은0건이다. 이는 승률만 높였다고 채택하면 안 되는 실제 반례다. 모든 비용변화는 net에 포함되어 다시 더하지 않는다.

확인 유예는13/3건 발생했다.2025는 다음 완료봉 회복4건, 지속 이탈6건, 기존 청산 우선3건이다. 회복4건 중 HYPE는 나중에 다시 손실로 끝났으므로 회복봉 관측을 확정 승리로 세지 않았다.2026은 회복0, 지속이탈2, 기존 청산 우선1건이다. 조건을 전체 적용한 결과이며 옛 승리 네 건만 복원하는 사후 전략을 만들지 않았다.

원래 부모51 대비 평균손실은2025−300.43→−314.95bps,2026−254.66→−257.46bps로 모두 악화했다. 이 유예 조건을 자동 편입하거나 유예 봉 수를 바꿔 재시험하지 않는다. 이번 결과로 모든 개선 가능성이 없다는 결론을 내리지 않으며, 비용 후 비양수 상태만으로는 회복과 추가 하락을 구별하기 부족했다는 범위로 해석한다.

## 구현·검증·원장

실제 실행run34287417970/job102266102941에서 동결 후 각 기간1회씩 완료했다. 사전17개 신규+25개 부모 합성시험42개가 원격에서도 통과했다. 결과 이후 연구규칙/경제원장/비용은 변경하지 않았다. 원시277완결+5미완결→가격·보유시간·비용·net/cost2·일별DD·승패·8그룹 전체기여를 별도 저장 검산기로 확인했다. 유예의 당시 비용/판정가격/한봉 시계/취소·확정 및 우선청산도 점검한다. 검산은 새 경제재생이 아니다.

이 PR은 연구 결과 보존용이다. 운영SSOT/다른Top5/G5/OOS/실주문/배포는 변경하지 않는다. 후보52/평가84, 이번 새후보1/FULL2, 이전51/82 기록은 그대로 보존한다. 완료 시 workflow는 읽기·저장검증 전용으로 바꾸고 필수 CI·리뷰·병합 상태는 PR 마지막 기록을 따른다. 평균손실·DD는 연구용trade-bps이며 계좌손실상한이나15배 선물 청산위험의 검증이 아니다.
