# D → 기존 A: Trend Rider 256T 종결 인계

**완료 판정: `SOURCE_FEATURE_BLOCKED / NO_CAUSAL_CHILD`. 새 후보0, 경제 비교0.**
이 패키지는 원본 실행 소스·실제 저장256행·전체7파일 artifact·반례시험을 결속한 실행 가능한 종결 근거다. 수익 개선은 미측정이다. K117 최종 `ef16489a81dbd2fcd74af60fcba08515da8e22f0`의 `CLOSED_FROZEN_NO_CAUSAL_CHILD` 및 이전 D 집계/수선은 그대로 보존했다.

소유자는 `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`이다. D branch의 직전 head는 `2f26c8dab8085c2406c5fb6f51462361e0355292`. 이 파일이 속한 전달 commit의 정확한 SHA와 fetch/worktree 명령은 #1358의 D 인계 댓글에 기록한다. 활성 실행 폴더 대신 그 commit의 별도 checkout에서 아래 명령을 사용한다. 이 작업은 A의 경제 슬롯이나 소비원장을 변경하지 않는다.

## 즉시 재현 명령

표준 Python3.11+만 필요하며 입력은 패키지에 포함했다. 저장 원장만 계산하고, 소스 반례는 합성5봉과 명시 stub으로 원형 `transform` AST 하나만 실행한다. 원형 module/main, 시세 API, 경제 엔진을 실행하지 않는다.

```bash
D_PACKAGE=research/campaigns/scalp7_20261022/parallel_fastfinish_v1/work_d/trend256_source_gate_v1
PYTHONDONTWRITEBYTECODE=1 python -B "$D_PACKAGE/run_saved_evidence.py" \
  --repo-root . \
  --output-dir /tmp/zel_d_trend256_source_gate_readback_v1

WORK_D_NATIVE_SOURCE="$D_PACKAGE/frozen_source/a1_trend_rider_delayed_fill_evaluator_v1.py" \
  PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover \
  -s "$D_PACKAGE" -p 'test_*.py' -v
```

출력 경로는 존재하지 않아야 한다. 덮어쓰기·재시도·시세복구 기능은 없다. 정상 출력은 `NO_CAUSAL_CHILD`, `SOURCE_FEATURE_BLOCKED`, output_files8, new_full_runs0, orders0이다. 이 exit0는 증거 검증 완료이며 경제/승격 PASS가 아니다. `completion/`에 실제 실행 결과8개와 출력별 SHA가 이미 저장되어 있다.

## 정확한 입력·계보

| 입력 | 고정값 |
|---|---|
| long-only 원본 | run37989679810 / artifact11646670634 / `inputs/long_only_prospective.json` /256T |
| 원문 SHA256 | `686c5574c2554867b8cdb38fcb23f2de50fa9c3837dd9406d0be4a168b976fb9` |
| 내부 receipt SHA256 | `4515dfa653d0ebf25029ee6b1eb0a9a54f81c8c4f65d3fbaecc30f9efc334c70` |
| 원본 artifact ZIP | `inputs/long256.zip` /983610bytes / SHA256 `412e3f7456c53dd79869f7b6c9934fc3d3247d01250166cc165076e64fe3a819` |
| 실제 checkout | job114020351819 로그 확인 `758fde9213032ef0211e5d8d3ffc914f6dad5ca2` |
| native policy blob | `5212f92a0b181e523c235dc546b64ea2852045e7`, 256행 모두 일치 |
| 비용 authority | canonical SHA256 `9a397e21412e2ab739f55953dc8fda6e4a66d8ac022d1de105876a2fb95debec` |
| 별도 Liquid6 | run37995747426 / artifact11647389180 / `inputs/liquid6_child.json` /123T |
| Liquid6 원문 SHA256 | `ddeadab19a915bf43cee8534f44369cd7ff5805aacf10331a308e4201dc17028` |
| 재사용 D 함수 | `research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/contribution_report.py`; SHA256 `1b0a7bedc97d75f14498518e5d5783a4907d1368a2d21891f98838e6ec6e8e56` |

원본은 12종목 1h이며 Scalp7 15m/30m가 아니다. 진입은2026-09-01 00Z–10-09 19Z. 256은 delayed parent301의 long 부분집합이다. source count/bounds는 원시 시세 바이트 검증이 아니다. 원래 run은 prospective hardening의 `BINGX_API_ERROR:100410`으로 failure였으며 이를 PASS로 바꾸지 않았다. #566의 최신265T/run39802697122 및 repair299/long260은 별도 계보다.

## 실제 저장 결과와 한계

모두 거래별 bps의 비가중 합이며 계좌 NAV나 새 경제 결과가 아니다.

| 256T 전체 | 비용1배 | 저장 비용2배 사후 스트레스 |
|---|---:|---:|
| 승률 |25.0000%|24.6094%|
| Gross/T |42.3153|42.3153|
| Cost/T |18.3039|36.6079|
| Net/T |24.0114|5.7074|
| Net 합계 |6146.9110|1461.1031|
| PF |1.195871|1.042101|
| exit-bar 개별순 DD |10503.5949|12722.7525|
| exit-bar 개별순 최대연패 |40거래|40거래|

동시봉 내부 순서는 관측되지 않았다. 원본 entry순 DD/연패는10783.8962·13018.0709/33거래, 동일 exit-bar를 묶은 연속음수는24cohort이며 별도 단위다. 시간대·날짜 경계·0진입일을 포함한 공통 source envelope는2026-08-29 07Z≤t<10-09 22Z,42UTC일/41.625 elapsed days다. long256은6.15015건/elapsed day, UTC0진입4일; Liquid123은2.95495건/elapsed day,0진입9일이다. 저장 진입 빈도는 실제 독립 실행 기회가 아니다.

October59T/Net1−3999.7999는 **종료봉 월** 기준이다. 진입월은53T/−4244.2067이며 별도 출력한다. 비용2배 최고승리1건 제외−1861.2724는 집중도 민감도이며 거래 삭제 전략이 아니다. 전체256 및 승리64/63건을 모두 보존했다. 작은 양gross→1배 비용손실1건,1배승리→2배비양수1건으로 이 표본의 손실 대부분을 작은 승리의 비용교차로 설명할 수 없다. 회복승리/MFE/MAE는 원시 경로가 없어 UNKNOWN이다.

기존 overlap106/123은 zero-span 기록을 포함한 이전 비교식으로 재현된다(107쌍). 엄밀한 `[entry,exit_stamp)`는104/123(105쌍), `exit_stamp+1h` 모델은113/123(115쌍). 둘 다 실제 체결 점유를 확정하지 않는다. +0.92372474는 종료일 **합집합37일 0채움**이며, 실제 공통 종료일28일은+0.94367796이다. 양쪽 일별음수19일은 회고 지표다. 379행의 symbol/side/signal proxy는280개지만 독립 기회 수가 아니다. Liquid의 추가 UTC진입일은8월31일1개, Berlin에서는0개다. 50:50 결합·공동 Net·NAV를 만들지 않았다.

## 원문 → 코드 → 반례 → 종결

`SOURCE_GATE.json`은 ZIP7파일에서 OHLC 객체0·native feature body0·가용 timestamp0을 재확인한다. 256행은 feature hash만 보유한다. 원형 ATR14/EMA50/Supertrend/entry-chase, prior BTC/ETH snapshot의 전체 prefix/seed와 완성봉 가용시각을 복원할 수 없다. 최종손익·월·종목으로 이를 대체하지 않았다.

`LIFECYCLE_COUNTEREXAMPLES.json`은 실제 source SHA를 확인한 뒤 진입/후속 갭에서 봉 고가 밖 stop 체결, TIMEOUT 종가와 봉 시작 timestamp, 부모 비용 복사,48봉 이전 자료끝 TIMEOUT, 부모 open/rejected 상속, partial/trailing 메타 미실행을 합성 반례7개로 재현한다. 실제256의 entry<SL4건도 원문 그대로 표시했다. 실제 체결 경로·수선된 손익은 계산하지 않았다. 상세 함수/원문은 `SOURCE_LIFECYCLE_FINDINGS.md`, 이미 시험된 peer/chase 등은 `DUPLICATION_FINDINGS.md`에 결속했다.

기존 parent의 open1/rejected1889는 보존하되 child256의 새로운 admission/후속점유로 바꾸지 않는다. 5–7전략의 추가 독립기회·동시손실·공동 Net·NAV/DD는 미측정이다. 실제자료가 없는 값은 null로 남겼다.

**A 소비 요청:** 이 패키지의 종결 근거와 기존 실패를 보존하고, 이미 준비된 별도 기전의 기존 진행 경로로 이동한다. 이256이나 K117을 재실행·재튜닝하지 않는다. 이번에는 구현된 child/변경축이 없으므로 경제 FULL 명령도 없다. D는 master/owner/소비원장/B/STARTED/활성runtime/guard/Actions/주문을 변경하거나 실행하지 않았다.
