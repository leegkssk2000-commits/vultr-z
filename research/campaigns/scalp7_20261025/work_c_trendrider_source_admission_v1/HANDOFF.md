# Work C — integrated TrendRider first result

판정: **HOLD_NEW_ECONOMIC_EVIDENCE_NOT_ESTABLISHED**. 새 수익 개선을 입증하지 못했다. 이번에 실제 완료한 것은 PR #1469/#1471의 고정 입력·원장 계약 감사와 저장 회계 검산이다. 새 현실 숏 체결 비교, 경제 FULL, 원래 S0–S4 전략 재실행은 하지 않았다.

기존 C 브랜치 `work/zel-candidate-adapters-20261021`, 부모 `cd782837747e581cafa5e023cc942a91fea7cf4f`에 이 디렉터리만 추가한다. PR1469 merge `d256807c58a41d77606df1a844a2d13c2cfff945`, PR1471 merge `2e7c2e80655c6b1517a37504f8b39f3c1e534fc2`를 먼저 읽었다. 감사 입력은 master의 고정 객체 `93f5048dc6d57e49ddafe11bdcd1084fe5d830dd`에 결속했다. master를 C에 병합하지 않는다.

## 실제 확인한 실패

- 원본 SHA·schema·lineage, 97개 중복 제거, 267개 기회의 stage별 accepted/rejected 분할은 일치한다.
- S4의 숏 71개 중 **15개**가 동결된 24시간 제한을 초과한다. 14개 TIME24와 1개 intrabar stop이 모델의 effective-close 기준 25시간이다. S3도 80개 중 같은 15개다. 실제 거래소 체결시간이라는 뜻은 아니다. BTC-USDT 원기회 `BTC-USDT|long|1791860400000`의 25번째 시간 손절 반례를 포함해 전부 `FROZEN_AUDIT.json`에 남겼다.
- 손실회로는 이미 effective-close인 `end_ms`에 1시간을 다시 더한다. 이 시각을 고치면 이후 점유·입장이 바뀔 수 있다. 이번에 수정하거나 수정 수익을 계산하지 않았다.
- PR1471 비용/손절거리 필터는 원래 거래의 실현 기간·funding이 포함된 `instrument_source_cost_bps`를 사용한다. 진입 당시 관측 가능한 비용 근거가 아니며, 원본 스크립트의 baseline 경로 결함도 있다. 이미 실패한 필터를 보존하고 재최적화하지 않았다.
- 267개는 완료된 부모 거래 영수증의 합집합이다. 점유가 달라질 때 새로 허용될 수 있는 **전체 원시 신호 스트림**의 완전성을 증명하지 못한다. 기존 accepted 거래만 재가격화해서 현실 비교로 만들 수 없다.

## 입력·시각·비용 결속

원본 gzip SHA256 `16198ac2a3db7849237028a5f5a0100e2033162a9d93b05ad171273215c9a592`, 251334 bytes. 12종목 × 1000개의 1h OHLCV이고, 각 종목의 행 SHA도 다시 검산했다. 종목과 모든 핀은 `SOURCE_MANIFEST.json`, `SOURCE_AUDIT.json`, `SNAPSHOT_WITNESS.json`에 있다. BCH·1000PEPE를 제외하지 않았다.

원천 ts 범위는 2026-09-13 17:00Z ~ 2026-10-25 08:00Z, 아카이브가 기록한 일괄 수집시각은 2026-10-25 08:01:20.410374Z다. 역사적 received_at/available_at은 **UNKNOWN**이다. 봉 종료시각을 실제 가용시각으로 대체하지 않는다. 모델처럼 ts를 봉 시작으로 해석하면 마지막 08시 봉은 수집 시각에 미완성이고, 원천 reader는 미완성 봉을 제거하지 않는다. 특정 S4 거래가 그 봉을 사용했다는 결론까지 내린 것은 아니다.

S4 동결 2026-10-25 14:29:26.215264Z 이후의 행은 **0개**다. 이 스냅샷은 이미 사용한 개발자료다. 미사용 미래구간·독립 소비 증명·저주기 quote/fill·실제 양방향 수수료·부호 있는 숏 funding·당시 tick/최소주문 제약이 결속되지 않았다. HGL1 handoff도 새 입력 SHA가 null인 DATA_BINDING_BLOCKED였다. B의 명명된 44개 TrendRider 브랜치와 지정 master 디렉터리의 제한된 검색에서 새 공개 handoff를 찾지 못했으며, 미공개 B 작업이 없다고 단정하지 않는다.

원래 숏 비용은 `max(source long native instrument cost,14bp) × 1/3`과 8시간마다 시작되는 5 instrument bp carry의 모델이다. 실제 숏 funding이 아니다. 따라서 새 경제 비교의 비용 근거로 승격하지 않는다.

## 같은 기준의 저장 비교

`METRICS.md`와 `SAVED_METRICS.json`에 S0–S4, 실패 PR1471, 새 현실 S4 행을 함께 둔다. Gross/Cost/Net1/Net2·월별·종목별 합계는 sealed legs에서 검산했다. PF/WR/DD/연패/R/top2는 기존 결과를 복사하고 그 출처를 명시했다. 거래/일은 적격 고정 기간과 마지막 봉 closure가 결속되지 않아 null이다. 임의 기간이나 첫/마지막 거래로 분모를 만들지 않는다.

저장 S4 Net2 +1752.480309bp, PF 1.294173, DD 2225.861306bp, 연패14다. 그러나 기존 +40bp 스트레스는 −807.519691bp, 1000PEPE 제외 replay는 −752.270814bp다. 숏 +1h는 총 +236.835957bp여도 10월 −1168.504213bp와 상위2승리 제외 −1163.907064bp다. 모두 **과거 모델 결과**이며 이번 새로운 수익 근거가 아니다. 원형 S0는 Net2 −1005.270344bp다.

H4 새 사전등록 placebo와 미사용 OOS는 NOT_RUN이다. 기존 no-short/no-early-bailout ablation은 과거 귀속 분석으로만 보존한다. 실제 체결에서 지배적인 실패 원인은 아직 **NOT_DETERMINED**이므로 새 수정축을 골라 동결하지 않았다. 과거 실패를 보고 비용·손절 필터를 다시 맞추지 않는다.

## 재현 명령 — 읽기·회계 감사 전용

이 커밋을 checkout한 저장소 루트에서 다음을 실행한다. 원본 모델을 import하지 않으며 주문·시세 API·Actions·경제 replay를 호출하지 않는다. 출력 디렉터리/파일은 새 경로여야 한다.

```bash
git fetch --no-tags origin 93f5048dc6d57e49ddafe11bdcd1084fe5d830dd
python research/campaigns/scalp7_20261025/work_c_trendrider_source_admission_v1/materialize_saved_inputs.py --repo . --destination /tmp/trendrider-c-saved-inputs-v1
python research/campaigns/scalp7_20261025/work_c_trendrider_source_admission_v1/audit_saved_contract.py --source-dir /tmp/trendrider-c-saved-inputs-v1 --filter-dir /tmp/trendrider-c-saved-inputs-v1/repair_diagnostics_v1 --output /tmp/trendrider-c-contract-audit-v1.json
python research/campaigns/scalp7_20261025/work_c_trendrider_source_admission_v1/saved_metric_table.py --input-root /tmp/trendrider-c-saved-inputs-v1 --output /tmp/trendrider-c-saved-metrics-v1.json
python -m unittest discover -s research/campaigns/scalp7_20261025/work_c_trendrider_source_admission_v1 -p 'test_*.py' -v
```

핵심 입력 TRACES gzip SHA256 `bc20d7e6b2f931cad8c5cd020fd3b396370dbf80e0bf746dd0fa1330f7e80239`, RESULT SHA256 `e99bbd783908628572a64875f7d019676fa5d686fdc7e7b29fd24cee2d4fab13`, ROBUSTNESS SHA256 `d3f716800de6665df0ce0465776bdb938227cf9803d9f1c1fb279d5ddc494cb3`. 모든 9개 파일의 bytes/Git blob/SHA는 manifest에 고정되어 있다.

## 경제 owner A 인계 경계

준비된 새 경제 명령은 **null**이다. 입력 적격성 실패를 정상 실행 명령으로 감추지 않는다. 다음 실제 비교에는 원시 신호 전체와 사전 선택된 미사용 미래구간, 실제 시각·체결·비용·종목 계약을 먼저 결속해야 한다. 해당 입력으로 원형 S4와 현실 숏 variant를 동일하게 시간순 처리하고, 진입·손절·점유 변경이 모든 이후 입장에 전파되도록 해야 한다. 수정축은 그 첫 적격 비교에서 확정된 지배적 원인 하나에만 사전 동결할 수 있다.

17:11Z의 읽기 전용 확인에서 run40209551229/job121217718959가 `a1-global-heavy-economic-evaluator-v1` 그룹에서 IN_PROGRESS였다. 이는 시점 증거이며 현재 상태로 영구 간주하지 않는다. 기존 owner/claim을 수정하거나 만들지 않았다. 후속 적격 실행 직전 기존 A가 slot과 소비 여부를 다시 확인해야 한다.

21개 synthetic 반례시험이 검산 코드의 변조·중복·미래 종속/시각 오류 탐지를 검사한다. 시험 PASS는 전략 수익 PASS가 아니다. 추가 디렉터리 외 A/B/D·master·workflow·원본 원장 변경은 없다. 주문0, 경제실행0, Actions dispatch0, G5/Paper/Live 승격0. 배포는 불필요하며 실행하지 않는다. 롤백은 이 추가 커밋의 파일만 제거하면 된다.
