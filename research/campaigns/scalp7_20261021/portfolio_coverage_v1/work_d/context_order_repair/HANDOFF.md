# CONTEXT_FIT_CHANGED 입력 순서 수선 인계

수신: **CLOUD_WORK_COORDINATOR_ISSUE1358_V1**. 상태는 코드·회귀시험·실제 문맥 동일성 검증 완료이며, 원격 설치와 경제계산은 수행하지 않았다. 기존 D 완료 커밋 `e4c875213951ff0c9442bd9b2496478b6e71a903`와 집계표를 그대로 보존한다.

## 확정 원인과 수선 범위

진단 커밋은 `114714730fd685761ce7b3e8e0660424b2fe99b3`이다. 게시 직전 연구 브랜치도 이 커밋이며, D 브랜치는 기존 완료 커밋이다. 읽기 전용 원격 점검에서 해당 stage 로더는 아래 원본 SHA 그대로였다. 후속 수선 커밋이나 적용된 로더를 확인하지 못했으므로 중복 수선 없이 이 패치를 준비했다. 적용 시점에는 owner가 후속 진행 여부를 다시 확인한다.

`guarded_once.py::run_cached`에서 캐시 JSON 순회 대신 동결 `scalp7_source_data_v2.SYMBOLS` 순서로 프레임을 공급한다: **BTC, ETH, SOL, XRP, LINK, DOGE**. 누락·추가 종목과 중복 JSON 키를 거부하고, 기존 gzip SHA, round-trip CSV SHA, 원본 binding SHA, 17,519행 검사를 유지한다. 이 함수 밖의 AST는 동일하다. 원본 시세·기간·기대 해시·동결 엔진·전략·비용·청산·소수점 처리는 변경하지 않았다.

| 항목 | SHA256 |
| --- | --- |
| `guarded_once.patch` | `40fd99e17f2565abf33984865ceae4480a9ae83be99ea5539c244cd3fb3c6278` |
| 원본 `guarded_once.py` | `a86934fed27bde13c94cf6bc11cdfca1169b6a024fa0048f2c4b68e4700dfb27` |
| 적용 후 `guarded_once.py` | `dd54d017df362f51e587fa5feaa215bb1bf711430f4e5b7e8cd3bd6fe3efdd57` |

## 실제 검증과 한계

기존 Vultr 캐시 **6종목 × 17,519봉**을 원본 검사를 유지한 패치 로더에 공급했다. 로더는 메모리에서 AST로 추출했고 경제 runner 대신 프레임 수집 stub만 사용했다. 동결 엔진 ref는 `6f7a42171dab54ff1be544304f44ee06fdd8f056`이다.

- 원래 종목 순서의 문맥 해시: `168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c` — 기존 기대값과 정확히 일치.
- 캐시 정렬 순서 BTC,DOGE,ETH,LINK,SOL,XRP 음성대조: `7f56091f7671215dc96ebf5c02f5f815dcfe18e54f0b5d262d1821b9d17769c3` — 기존 실패 재현.
- 10개 문맥창 중 5개가 순서에 따라 달라진다. CSV 자체는 동일하다.
- 원본 로더·STARTED·실행 로그·상태·캐시·binding·windows 파일의 전후 SHA가 같다. 세부 값은 `CONTEXT_PARITY_RECEIPT.json`에 있다.
- 로더 회귀시험 13개와 별도 attempt 준비기 시험 2개, 합계 **15개 PASS**. 순열, JSON sort_keys, 누락·추가·중복 종목, gzip/CSV/binding 손상, 행수 검사를 포함한다.

```bash
python -m unittest discover \
  -s research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/context_order_repair \
  -p 'test_*.py' -v
```

이는 문맥 동일성과 코드 인계 근거이다. 126거래 제어군 재생·후보 replay·경제 FULL·guard·Actions·주문은 모두 0회다. 실제 원격 stage에 패치를 설치하거나 새 attempt를 만들지 않았다.

## 별도 attempt 적용 명령 — 경제 owner용

수신 기록에 적힌 불변 전달 커밋의 이 디렉터리를 사용한다. 아래 명령은 해당 저장소 checkout 루트 기준이다. 실행용 기존 checkout을 전환할 필요 없이, 전달 커밋을 별도 디렉터리에 `git archive`로 추출해 그 루트에서도 사용할 수 있다. 정확한 전달 커밋은 #1358 인계 댓글에 기록한다.

```bash
REPAIR_DIR="$PWD/research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/context_order_repair"
PYTHONDONTWRITEBYTECODE=1 /home/z/z/venv/bin/python -B "$REPAIR_DIR/prepare_attempt.py" \
  --source-stage /home/z/z/runtime/k_winner_handoff_20261021T1230Z \
  --attempt-dir /home/z/z/runtime/k_winner_handoff_context_order_attempt2_20261021
```

준비기는 원본 코드·캐시·freeze·patch SHA를 먼저 검사하고, 존재하지 않는 별도 디렉터리에 입력과 동결 코드만 복사한다. 새 복사본에 `patch --batch --forward --fuzz=0 -p1`을 적용하고 결과 SHA를 검사한다. 기존 STARTED·실패·로그·lock·READY·결과를 복사하거나 삭제하지 않는다. 원본 코드와 원본 디렉터리는 그대로 두고, 새 경로에 `CONTEXT_ORDER_REPAIR_PREPARED.json`을 남긴다. 이미 존재하는 경로 또는 달라진 원본 SHA는 거부한다. 거부 시 기존 시도의 기록을 읽고 owner가 판단하며, 기존 경로를 삭제해 재시도하지 않는다.

준비 후 문맥만 다시 검증하려면:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  /home/z/z/venv/bin/python -B "$REPAIR_DIR/verify_context_readonly.py" \
  --loader /home/z/z/runtime/k_winner_handoff_context_order_attempt2_20261021/guarded_once.py \
  --stage /home/z/z/runtime/k_winner_handoff_context_order_attempt2_20261021 \
  --baseline /home/z/z/runtime/k_winner_timeout_20261021T1142Z \
  --repo /home/z/worktrees/zel-work-b-retry-6f7a4217-20261020
```

이 검증기는 문맥만 계산한다. 출력의 `remote_patch_installed: false`는 검증기 자체가 설치 작업을 하지 않는다는 뜻이다. 설치 상태는 별도 준비 영수증과 적용 후 로더 SHA로 확인한다.

## 경제 owner가 이어받을 경계

기존 실패 원본 `STARTED.json`과 로그, owner claim, 기존 allocation 및 시도 기록을 유지한다. 새 경로는 예산이나 재시도 권한을 갱신하지 않는다. `CODE_FREEZE.json`은 로더를 고정하지 않으므로 변경할 필요가 없고, 기존 READY의 원본 로더 해시도 바꾸지 않는다. 별도 수선 영수증이 원본/패치/적용 후 해시를 연결한다.

**게시 경로 주의:** 복사된 `persist_addonly.py`는 여전히 이전 `winner_handoff_20261021T1230Z` 결과 prefix를 사용한다. loader-only 수선 범위를 지키기 위해 그대로 보존했다. 경제 owner는 이후 guard/report 실행 전에 새 attempt 결과의 별도 게시 경로와 중복 방지를 먼저 확정해야 한다. 준비 완료가 기존 guard의 즉시 실행 허가를 뜻하지 않는다.

이 Work는 활성 stage, B 관측기, 원본 경제 원장, A/B·C 코드에 쓰지 않는다. 후속 126거래 제어군과 후보 계산은 기존 경제 owner가 기존 권한·점유·배정에 따라 담당한다.
