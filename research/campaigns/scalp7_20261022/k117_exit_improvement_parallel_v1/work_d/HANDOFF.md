# D → 기존 A: K117 passive BE 계측·비용 회계 검산

첫 실행 가능한 산출물이다. 기존 owner `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`에게 전달한다. C 결과를 기다리는 의존성은 없다. D는 저장행 검산과 합성시험을 실행했고, 실제 가격 native 계측은 A에게 전달만 한다.

변경 축은 **관측 가능성 한 축**이며 exit 정책 후보는 **0개**다. 기존 BE·부분익절 수식은 일관되므로 결함 수선이라고 부르지 않는다. 근거 없는 `cost2x+2bps` stop이나 새 임계치를 추가하지 않았다. 현 실행문이 요구한 조건부 후보 구현과 구분되는, 완성된 passive observer 산출물이다.

## 동결 대조군과 선행 작업

- K117 경제 commit: `8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8`.
- 경로: `research/campaigns/scalp7_20261022/k126_veto_objective_lifetime_v1/completion/`.
- identity: `scalp7_k126_veto_objective_completed_fresh_touch_v1`.
- 정확한 입력 파일·바이트 SHA: `exact117_input_contract.json`. 압축을 푼 ROWS SHA는 `7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7`.
- 전체 117건, 1x 71승/46패, 2x 43승/74패. Net1x `10159.281145923826`, Net2x `8399.99437120003` trade-bps.
- K117의 큰 승리 36건/일반 승리 35건과 기존 K126 큰 승리 34건 보존축을 구별한다. 후자는 기존 SUMMARY의 보존 결과를 인용했다.
- D 기존 head `ec2e3c0b0545e0d86cda34b8e6b68f2afac1c03b`와 연구 head `bd0e9721796cf07e5a540c6d88531280fbd6492e`를 시작 시 확인했다. 이번 후속 경로에 기존 D 구현/소비영수증이 없었다.
- 완료된 D 집계 `e4c875213951ff0c9442bd9b2496478b6e71a903`, 문맥순서 수선 `94e4eb2433604c331a37397a8d5d1e5f0278c28c`, K126 위험배분 산출물은 보존했다. 재작성하지 않았으며 이전 risk-budget 입력 결손을 이 작업의 차단 조건으로 삼지 않았다.

## 실제 저장행 근거와 아직 없는 state 근거

`SAVED_LEDGER_EVIDENCE.json`은 원본 SHA를 검사한 **117건 전체**의 회계·인과 시각·승리군·비용 분리를 포함한다. 최종 PnL/MFE/거래키는 회고적 보고 라벨이며 실행 조건이 아니다.

비용교차 28건의 합은 1x `+89.33427510419119`, 2x `-335.1132757781666` trade-bps다. 이 중 STOP_FIRST 25건은 관측 MFE≥1R이고 실제 종료가격이 `entry ± (frozen_cost_bps + 2bps)`와 일치한다. 24건은 약 +2bps다. DOGE long signal `1773664200000` 한 건의 +11.76905278bps는 부분실현 약 `11.6421175061` + 잔량 terminal 약 `16.8575825406` − 비용 `16.7306472673`으로 설명된다. 이 계산은 고정된 10% 부분익절과 저장 gross의 대수 일치이며 **부분체결 event 시각을 관측한 결과가 아니다**.

| 나머지 비용교차 거래키(symbol, side, signal_ts_ms) | 원래 종료 | Net1x / Net2x trade-bps |
| --- | --- | ---: |
| LINK-USDT, +1, 1784136600000 | MAX_HOLD_NEXT_OPEN | +8.95734273 / −6.74767508 |
| BTC-USDT, +1, 1787324400000 | HG_FROZEN_5BAR_MFE_SCRATCH | +7.05048239 / −6.94951761 |
| LINK-USDT, −1, 1789065000000 | HG_FROZEN_5BAR_MFE_SCRATCH | +13.55739720 / −2.14762061 |

117건 전체에서는 BE 종료가격 일치가 29건이다. 28건만 골라 계측하지 않는다. 저장 원장에 없는 BE 최초 arm/실제 적용 봉/부분체결/runner 시각은 evidence에서 null로 표시했다. 이 값들을 채우는 실제 native trace는 아직 실행되지 않았다.

## 코드와 반례

`be_observer.py`는 SHA가 일치하는 `_single`의 AST 복제본에 읽기 전용 event hook을 삽입한다. disabled는 원래 함수 객체를 그대로 반환한다. enabled도 동일 입력의 return 값·원래 콜백·포지션 업데이트·우선순위를 보존한다. 기록은 호출별 snapshot이며 원래 원장을 수정하지 않는다.

기록 범위는 entry 원래 위험/참조비용, BE 최초 arm 시각과 완성봉 close·관측 MFE, 요청 stop/단조 적용 stop, 실제 다음 연속봉의 활성 여부, partial 실제 비율·누적 실현분·잔량, runner와 terminal 우선순위다. native 원장은 실제 계약수를 제공하지 않으므로 partial 수량은 원래 포지션 대비 비율로 기록한다. 임의 계약수/레버리지는 가정하지 않는다.

원래 pending next-open가 stop 검사보다 먼저다. stop에 먼저 걸린 봉의 고저를 BE 결정에 소급하지 않는다. gap이면 실제 open 체결을 기록하고, 결측 구간은 미결로 유지한다. callback이 없던 terminal도 엔진 내부 hook으로 포착한다.

`protection_accounting.py`는 원래 명목 기준 `부분실현 + 잔량 × terminal − 참조비용 − 추가 carry`를 검산한다. 역산 보호가격 함수는 대수 계산일 뿐 stop setter가 아니다. 사후 2x 스트레스는 별도 함수다. 비용/명목/수량 단위 반례와 실제 수식의 장단점을 `SOURCE_MAP.md`에 원문→코드→시험으로 연결했다.

합성 경로는 조기 보호로 일반 승리·큰 runner 승리·이후 회복 승리를 잃는 경우와 손실을 피하는 경우를 모두 포함한다. `cost2x+2`가 기존 runner를 조기 종료하거나 완성봉 시점보다 높은 가격을 소급 체결할 수 없는 반례도 포함한다. 이 경로는 존재 반례이며 거래 규칙이나 실제 경제성과가 아니다. 회복 여부는 미래 경로 라벨로만 쓰인다.

## 바로 실행 가능한 경량 검산과 합성시험

아래 명령은 인계 댓글에 고정한 **정확한 D commit**의 저장소 루트에서 실행한다. 필요한 frozen engine 두 파일은 `REPLAY_DEPENDENCY_PINS.json`의 기존 read-only checkout에 있다. D commit의 기존 브랜치 ancestry에 있는 더 오래된 원본을 자동 대체로 사용하지 않는다.

```bash
D_PACKAGE="$PWD/research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/work_d"
K117_BASELINE_DIR=/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1 \
K117_FROZEN_SOURCE_DIR=/home/z/worktrees/zel-work-b-retry-6f7a4217-20261020/backend/research/rebuild \
PYTHONDONTWRITEBYTECODE=1 /home/z/z/venv/bin/python -B -m unittest discover \
  -s "$D_PACKAGE" -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 /home/z/z/venv/bin/python -B "$D_PACKAGE/saved_ledger_audit.py" \
  --baseline-dir /home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1 \
  --output /home/z/k117_d_saved_ledger_verified_20261022_v1.json
```

원장 검산은 새 출력 파일에만 쓰며 기존 파일이 있으면 실패한다. 시험 receipt는 `VALIDATION.json`이다. 저장117 시험이 skip된 실행은 전체 검증 PASS가 아니다.

## A만 실행할 native run-once 계측 명령 — D 미실행

A가 기존 owner 권한과 기존 단일 공유 경제슬롯을 정상 확보한 뒤, 위와 같은 정확한 D commit에서 **이 명령 하나만** 사용한다. 이 명령 자체는 slot/owner 획득이나 권한 부여가 아니다. 신규 서비스·guard·Actions·큐·재시도는 만들지 않는다.

```bash
D_PACKAGE="$PWD/research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/work_d"
PYTHONDONTWRITEBYTECODE=1 /home/z/z/venv/bin/python -B "$D_PACKAGE/run_owner_be_observer.py" \
  --owner-ack CLOUD_WORK_COORDINATOR_ISSUE1358_V1 \
  --run-once \
  --baseline-dir /home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1 \
  --output-dir /home/z/k117_be_observer_d_once_20261022_v1
```

출력 디렉터리는 존재하지 않아야 하며 부모 `/home/z`만 기존에 존재해야 한다. runtime/repo/input 밑의 출력은 거부한다. 동결 source/dependency/cache/CSV/context SHA를 검증하고 기존 `paired.lock`을 읽기 모드로 연 뒤 비차단 잠금한다. 임의 대기·재시도·기존 lock 생성은 없다. 기존 source.SYMBOLS 순서 BTC/ETH/SOL/XRP/LINK/DOGE, 각 17,519개 30m봉, `round_trip`, 원래365일 문맥을 사용한다. 짧은 거래구간으로 지표를 재seed하지 않는다.

K117의 원래 `Structure(True) → objective(enabled)` 빌더를 사용하고 메모리 내 `_single`만 잠시 관측 함수로 교체하여 finally에서 복원한다. 원래 `run_compare.run()`은 호출하지 않아 STARTED/authority/경제 결과/소비원장을 건드리지 않는다. 추가 carry reference 재생도 하지 않는다. 원장에 저장된 carry 4건 합 5.4bps를 trace 후 별도 결합한다.

완료 조건은 순서까지 포함한 raw117 전행·미결·경계 제외·objective expiry events·native entry traces의 정확한 동일성과 117건 전부의 trace 결합이다. 결과는 `BE_NATIVE_CALLS.json.gz`, `BE_ALL117.json.gz`, `OBSERVER_RECEIPT.json`이다. 실패하면 해당 새 폴더에 원인을 남기고 중단하며 자동 재실행하지 않는다.

## 경제 판정 경계

이번에는 정책을 바꾸지 않았고 경제 효과를 측정하지 않았다. 계측 후 구체적 결함이나 확인 가능한 추가 구조가 나오면 그 근거로 최대 한 exit 축을 별도로 고정할 수 있다. 어떤 후속 정책도 A의 같은 기회 비교와 새/놓친 진입·점유·미결을 포함한 전체 시간순 결과로 판단한다. Net1x/2x, T/빈도, PF/승률, 손실 묶음 수·최장 연패 묶음액·최악 손실액 묶음, cohort-net DD, 일반/큰/회복 승리 손상, 추가 비용을 함께 본다. 계좌 NAV/MTM DD·실제 역사펀딩·OOS·실거래 PASS로 확대하지 않는다.

이 디렉터리만 add-only 저장한다. 정확한 전달 SHA와 비강제 branch 갱신·원격 내용 재조회 결과는 기존 issue #1358의 D 인계 댓글에 기록한다. 경제 FULL·Actions·주문·원격 native 계측·활성 실행 폴더 변경은 이 Work에서 0건이다.
