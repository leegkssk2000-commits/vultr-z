# Work D — HGL1 입력 확인 및 실행 판정

판정: **HOLD_DATA_BINDING_AND_D_RESERVATION**. E의 Issue #1358 댓글 [6382321576](https://github.com/leegkssk2000-commits/vultr-z/issues/1358#issuecomment-6382321576)과 `6b91fd2ab8b8933c004712c1d8e49ce6a9fbe035`의 `WORK_D_HANDOFF.md` 전체를 읽고 수행한 D ACK다. HGL1 시장 DEV 결과나 새 실행 허가가 아니다.

## 1. 입력 적격성 — HOLD

기존 승인 원천 `/home/z/z/runtime/scalp7_broad_v2_20260915/fresh_1m_verified`가 존재한다. 기존 서비스 설정과 IDENTITY를 대조했고, **6종목 × 동일 10분 = 실제 60행**의 완료된 receipt·raw·normalized 원본 바이트를 읽기 전용으로 복사했다. 구간은 2026-10-24 **[09:23, 09:33) UTC**다. 변경하지 않은 pinned source `_receipt_frame`으로 6개 receipt의 SHA, 원본/정규화 정확 일치, 요청 구간·가용시각·누락표 일치를 검증했다. 이 표본은 전체 warmup/DEV 입력이 아니다.

| 증거 | 확인값 |
|---|---|
| IDENTITY SHA256 | `a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9` |
| 첫 live CURSOR SHA256 | `0d9c3dd4b6ff8752f3194db91e615ad3660ef9200b38d02cbbb68397b1a8d933` |
| 다음 live CURSOR SHA256 | `bb061c3820eb703d57418fff5464778b5819942571e902a9be3fb665ae10acea` |
| 표본 가용시각(received_at) | 09:34:58.668–09:42:36.337 UTC, 종목별 원본 receipt에 기록 |
| 실제 시장 input manifest SHA256 | `null` — 결속하지 못함 |
| rule SHA256 | `bc44ab07cc7e61e45a23b3044a13bff11bfd0a53f5152cadbc239f3a72729eee` |

`results/SOURCE_SAMPLE_VERIFICATION.json`은 종목별 receipt/raw/normalized 경로·SHA·가용시각을 모두 기록한다. `results/SOURCE_SAMPLE_ONLY.zip`에는 IDENTITY와 6×3개 정확한 원본 파일, 총 19개가 들어 있다. **전체 CURSOR 바이트는 보관하지 않았다.** live CURSOR 변경을 관측했으므로 live 경로 자체를 불변 스냅샷으로 선언하지 않았다.

다음 항목이 확인되지 않아 입력을 승인하지 않았다.

- 기존 승인된 **전체 불변 snapshot root + full CURSOR**와 모든 참조 파일의 hash chain.
- 240시간 warmup 및 닫힌 DEV 구간의 연속성·가용시각 전수 검증.
- 원본 tick metadata의 SHA, 종목별 tick size와 해당 구간 유효성.
- DEV 시작 전에 선언한 input freeze 및 독립 data attestation, 확정된 최대 31일 개발구간.
- 기존 D 공유 claim 디렉터리, 신규 결과 경로, 다른 호스트까지 포함한 후보 미소비 확인.

규칙 동결은 **2026-10-24T08:53:29.048Z**다. 규칙 시각만 고려한 첫 완성 가능한 hourly 구간은 [09:00,10:00) UTC지만, 09시 이전 input freeze/attestation 증거가 없다. **10시가 지나도 이 구간을 사후 선언해 사용할 수 없다.** 실제 DEV 시작/끝은 `null`로 남겼다. 미래 구간도 기존 입력 게이트의 모든 조건을 충족해야 한다.

검사 범위 내 불변 export/틱 원문 미확인이며 전체 파일시스템에 없다는 주장이 아니다. 제한된 export 파일명 조회 한 건은 MCP timeout으로 결과를 얻지 못했다. 초기 표본 진단에서 CSV.GZ를 JSON으로 읽은 오류는 정확한 바이트와 원래 loader로 바로잡았다. 원천 무결성 실패나 보안 거절로 취급하지 않았다. 거절된 57거래 원장과 다른 표현본은 읽지 않았다.

## 2. 실제 DEV 실행 여부 — NOT_RUN

HGL1 코드를 재작성하지 않았다. E 패키지 15개 manifest SHA와 패키지/의존 파일 Git blob을 확인했다. 기존 64개 시험이 모두 통과했다. 이것은 합성 반례 시험이며 실제 시장 전략 실행이 아니다.

작업 루트에서 실제 수행한 시험 명령:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s hgl_repo/research/campaigns/scalp7_20261024/holygrail_source_contract_v1 -p 'test_*.py' -v
```

실제 수행한 빈 template preflight 명령:

```bash
python -B hgl_repo/research/campaigns/scalp7_20261024/holygrail_source_contract_v1/dev_runner.py preflight \
  --repo-root /workspace/scratch/3e2cc5e613ac/hgl_repo \
  --manifest hgl_repo/research/campaigns/scalp7_20261024/holygrail_source_contract_v1/INPUT_TEMPLATE.json \
  --input-sha256 1c4a5f9222a6d05b4f230ff155e3a81d3fffed93f968763d7035c4ff7bcfee38
```

실측 결과는 **exit 2 / HOLD_MISSING_NEW_INPUT_BINDING**이다. 위 SHA는 빈 template의 SHA다. 시장 입력을 결속한 preflight PASS나 위 60행 표본을 DEV로 승인한 결과가 아니다. 정확한 실행 환경·명령·로그 SHA는 `results/PACKAGE_VALIDATION.json`, 전체 로그는 `results/PACKAGE_TEST_LOG.txt`와 `results/PREFLIGHT_LOG.txt`에 있다.

`results/OWNERSHIP_AUDIT.json`에 기존 D/A branch, owner, worktree 및 bounded process metadata를 기록했다. 발견한 D worktree는 완료된 K117 observer이며 HGL1 공유 claim을 대신하지 않는다. matching process/Actions 이름이 없다는 사실만으로 cross-host 미소비를 주장하지 않는다. claim을 새로 만들거나 다른 owner로 바꾸지 않았다.

이 Work의 시장 DEV 호출 **0회**, 경제 FULL **0회**. 실행 커맨드 `dev`는 호출하지 않았다. 실제 입력 SHA와 기존 D claim 경로가 없으므로 현재 실행 가능한 시장 DEV 명령을 꾸며서 인계하지 않는다. 조건을 충족한 뒤 사용할 원래 명령과 필드는 `upstream_receipts/WORK_D_HANDOFF.md`에 원문 그대로 보존했다.

## 3. 비용 후 경제결과 — NOT_MEASURED

| 지표 | 왕복 20bp | 왕복 40bp |
|---|---|---|
| 거래 수 | N/A — NOT_RUN | N/A — NOT_RUN |
| Net | N/A — NOT_RUN | N/A — NOT_RUN |
| PF | N/A — NOT_RUN | N/A — NOT_RUN |
| 승률 | N/A — NOT_RUN | N/A — NOT_RUN |
| 최대 연패 | N/A — NOT_RUN | N/A — NOT_RUN |
| DD | N/A — NOT_RUN | N/A — NOT_RUN |
| 큰 승리 의존도 | N/A — NOT_RUN | N/A — NOT_RUN |
| 일일 독립 진입 횟수 | N/A — NOT_RUN | N/A — NOT_RUN |

20/40bp는 원래 동결된 비용 가정이다. 거래 수/손익을 0으로 채우지 않는다. 현재 HGL1은 경제적으로 채택·기각되지 않았다. 실제 비용 2배 Net이 음수이면 동결 후보를 기각하고 재튜닝하지 않는다. 양수이면 A에 별도 검토 대상으로 넘기며 FULL/G5/실주문 허가로 해석하지 않는다.

## A 인계 및 보존 범위

이 HOLD는 **HGL1 D 입력·예약에만 한정**된다. A의 Squeeze 경제 FULL 및 다른 기존 Work의 승인된 진행을 막거나 슬롯을 예약하지 않는다. A owner ref `910f998b1d60ddec30a76366ba49253a4afaa8dd`는 변경하지 않았다.

기존 D `work/zel-portfolio-coverage-20261021`의 부모 `ab71035013e226bdc9409a5f36f2f22c7cde3320` 위에 이 새 디렉터리만 추가한다. 완료된 D/K117/KAMA/Grimes, E HGL1 코드, 기존 A/B/C, 경제 원장, 활성 실행 폴더, STARTED, B 관측기는 그대로다. 새 수집기·원천 쓰기·주문·Actions dispatch·guard·경제 FULL을 실행하지 않았다. 배포할 변경이 없으며 Actions 배포는 실행하지 않는다.

독립 검토는 `results/REVIEW.md`, 기계 판정은 `INPUT_ADMISSION.json`, 파일 무결성 목록은 `ARTIFACT_MANIFEST.json`이다. 이 추가 산출물은 자동 실행되지 않는다. 수정이 필요하면 후속 증거 커밋으로 정정하며 이전 완료 결과나 실행 claim을 되돌리지 않는다.
