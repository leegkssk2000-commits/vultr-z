# Work C — Supertrend 승리 보존 종결 인계

`ZEL_C_SUPERTREND_WINNER_RETENTION_AFTER_K117_V1`의 결과는
**`NO_SOURCE_EXACT_CAUSAL_CHILD`**다. 새 adapter와 새 경제 후보는 0개다.
원본 거래와 원문 코드를 회수하고, 오프라인 결속 검사·저장 원장 분석·반례시험을
실제 구현했다. 이 결과는 경제 PASS, 수익 개선, OOS 또는 Shadow 성과가 아니다.

## 정확한 대상

| 항목 | 고정 값 |
|---|---|
| 저장 브랜치 | `work/zel-candidate-adapters-20261021` |
| 작업 시작 C commit | `bb0c8312f10c260374addad3569f8c560f59b296` |
| 경제 owner | `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` |
| 조회한 owner ref commit | `910f998b1d60ddec30a76366ba49253a4afaa8dd` |
| 부모 | `supertrend_pullback`, 1h, 완료 236건 |
| 기존 subset | `supertrend_pullback__exact_parent__volatility_regime_owner_only`, 117건 |
| 부모 receipt | `9edb8d722b985af9e6e5f8e77dc560b5473befbaa365e0c61a94838478cfdc9a` |
| subset candidate SHA | `25f5ccd009e33d477a59bfe3f249663e73ad2c3f8d1832d58d283ed9c6066e3d` |
| subset identity-set SHA | `e42711d8843107a94f32019e0a7d1c7492319e812ddf5be377bbdbdac1365e01` |
| 원래 summary blob | `97a6bc3d50dfb91ea3d9d3815549327d40dfafad` |

K117 30분봉·native-line 87건·새 latest 240건과 다른 identity다.
기존 Actions run `38043785567`의 artifact `11667302314`를 읽기만 했다.
원장과 summary의 원래 bytes를 `inputs/`에 보존했으며 SHA는
`inputs/ARTIFACT_MANIFEST.json`에 있다. 현재 시세를 다시 받아 과거 입력을 대신하지 않았다.

## 저장 자료에서 확인한 결과

`49.5763% = 117/236`은 전체 거래 보존율이다. 순이익 거래의 건수 보존율은
**`50% = 32/64`**다. 제외된 119건은 승리 32건과 손실 87건이다.
저장 집계에서 역산한 포기한 승리 순익은 약 `13,359.335860 trade-bps`,
회피한 손실은 약 `13,006.225624 trade-bps`다. 차이는 `+353.110235 trade-bps`다.
제외 거래의 비용은 `2,117.085995 trade-bps`이며, 비용 2배 산술에서는
제외 거래 순익이 `-1,763.975759 trade-bps`다. 모두 이미 저장된 결과의 분해이며
새 진입·청산·점유를 적용한 경제 재실행이 아니다.

ETHFI long, 진입 `2026-09-17T06:00:00Z`, 청산 `2026-09-19T06:00:00Z`의
TIMEOUT 승리는 순익 `+2,217.999965 bps`, 비용 `14.961208 bps`,
진입가→초기 SL 거리 `262.816007 bps`, 순익/그 거리 `8.439364 R`다.
해당 날짜의 제외 수가 1건이고 집계 손익 차이와 일치하는 원장이 유일하다는
**집계 추론**이다. 원래 admission 기록을 회수한 것으로 표시하지 않는다.
전체 원장 중 제외 47건·보존 53건만 집계로 추론되며 136건은 UNKNOWN이다.

원본 117건의 ID 목록과 ATR14/ATR50 분류에 사용한 별도 봉 입력이 없어
subset identity-set SHA를 재검증하지 못한다. 회복 승리·보유 중 MFE·gap 경로와
완성/수신 시점별 feature 값도 UNKNOWN이다. 최종 손익·날짜·종목·MFE·승리 ID를
실행 feature로 사용하지 않았다.

기존 concentration의 `net_R`는 실제 초기위험 R이 아니라 `net_bps/100`이다.
저장 DD는 symbol별 append 순서다. 따라서 기존 `6283.106580`을 계좌 NAV 또는
시간순 DD로 주장하지 않는다. 분석 코드는 원장 순 DD와 exit timestamp를 묶은
시간순 trade-bps DD를 별도로 표기한다. 비용의 funding은 원래 코드의 절댓값 모델이고
실제 signed funding 정산 검증이 아니다.

## 최초 원문 결손

고정 부모 policy blob `5212f92a0b181e523c235dc546b64ea2852045e7`는
`atr_structure_after_favorable_progress`라는 이름만 선언한다. 정확한 activation,
distance, update, cadence, effective time, gap precedence가 없다.
고정 evaluator는 SL→TP→TIMEOUT만 실행한다.

HIST_R7 참조도 원격에서 실제 회수했다: commit
`1dadb1f6a28662823058a58fdeaa978fcd104b7b`, file blob
`7941bb1cfb380b01b27cbe196746bfb2b382ab6c`.
이 원문은 enter/add/hold만 반환하며 `.9 ATR`은 제안 SL geometry에 사용된다.
이를 보유 중 단조 trailing recurrence로 해석할 근거가 없다. ATR 계산·초기 SL·TP·
추가진입 구조도 현재 부모와 달라 통째로 이식하면 한 축 변경이 아니다.
구체적 정적 코드 검사는 원문을 import하거나 실행하지 않고 AST로 확인한다.

원문 결손과 데이터 결손은 별개다. 원자료만 회수해도 규칙이 완성되지 않으며,
generic Supertrend 수식이나 broad-v2의 내부 번역 `1R/1.8ATR`로 빈칸을 채우지 않는다.
기존 subset 축과 EXIT_TRAILING_ONLY, 87T gen2 실패는 그대로 보존한다.

## 최초 실행 가능한 명령: 오프라인 종결 검증

최종 인계 메시지의 원격 commit을 checkout한 저장소 루트에서 실행한다.
Python 표준 라이브러리만 사용하며 추가 패키지·네트워크·API·경제 엔진 호출이 없다.

```bash
work_c=research/campaigns/scalp7_20261022/parallel_fastfinish_v1/work_c
python "$work_c/source_binding_gate.py"
python "$work_c/saved_summary_review.py" --out /tmp/work-c-supertrend-review.json
python -m unittest discover -s "$work_c" -p 'test_*.py' -v
```

Gate의 exit 0은 **고정 입력과 종결 근거가 일치한다**는 뜻이며 candidate READY가 아니다.
다른 identity·변조 bytes·원문 없이 완료라고 주장하는 packet은 거절한다.
원본 입력 byte 보존 검사는 경제 engine의 disabled replay parity와 구분한다.
adapter가 없으므로 실행하지 않은 승리/손절/gap trading fixture를 PASS로 표시하지 않는다.

경제 FULL 입력 계약 및 명령은 **없다**. A에는
`MECHANISM_REPLACEMENT_DECISION_ONLY`를 요청한다. 다른 기전을 별도 승인하기 전까지
이 부모의 후속 trail/subset 튜닝을 시작하지 않는다. 이 파일은 인계용이며 Issue나
외부 상대에게 메시지를 전송하지 않았다.

## 변경 범위와 되돌리기

이 디렉터리 아래 새 파일만 추가했다. 원래 `WORK_NEXT_SUPERTREND.txt`, C1/C2/C3/K117,
A/B/D, master, 실제 `.github/workflows`, owner/claim/소비 원장, 운영 코드 변경은 없다.
`inputs/source/.github/`의 파일은 실행되지 않는 과거 원문 증거 복사본이다.
작업 중 master의 다른 작업자 진행은 조회만 했으며 C에 병합하지 않았다.
경제 FULL·Actions 시작·시장 API·Paper/Live·실주문·배포는 모두 0이다.
배포 Actions 실행은 필요하지 않다. 되돌릴 때 이 게시 commit만 revert하면 된다.
