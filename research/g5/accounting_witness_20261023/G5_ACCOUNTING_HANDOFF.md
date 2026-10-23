G5_ACCOUNTING_HANDOFF — 2026-10-23 Europe/Berlin

판정: 저장행 검산과 읽기 전용 표시 수선 완료. 5개 lane 모두 G5_ACCOUNTING_INPUT_BLOCKED. 정식 PASS·G5B 재사용 권한은 false다.

입력 기준 master `dd59cdb4fa5d6347cb40f55c8e014ef790c0fe63`. INPUT_MANIFEST.json의 30개 원본 파일 1,328,796 bytes를 검증하고 별도 출력 디렉터리에 원본 그대로 캐시한다. 전략 재생·신규 수집·heavy·claim·주문·master 변경은 없다.

| 원래 G5 lane | 저장 CLOSED / 원행 일치 | 모델 Net1x / Net2x (trade-bps) | 모델 PF1x / PF2x | 최초 차단 필드 |
|---|---:|---:|---:|---|
| Keltner Reclaim | 29 / 29 | -3,677.61 / -4,257.61 | 0.4197 / 0.3737 | `source.raw_sha256` |
| Supertrend Momentum | 26 / 26 | 4,429.42 / 3,909.42 | 2.4475 / 2.1579 | `source.raw_sha256` |
| Q0 Convex Channel Breakout | 17 / 17 | -1,543.14 / -1,931.88 | 0.5620 / 0.4927 | `entry_source_4h_open_row` |
| Squeeze-KR3 Unified | 3 / 3 | NOT_RUN / NOT_RUN | — / — | `raw_lifecycle_preimage` |
| TrendRider Unified | 0 / 0 | NOT_RUN / NOT_RUN | — / — | `completed_lifecycle_rows` |

모델 수치의 범위: Keltner/Supertrend는 원래 20bps 고정비용과 40bps 스트레스. Q0는 동결 fee·spread·impact·P95 펀딩 준비금과 기존 20bps 바닥을 적용한 원래 비용모델이다. 2x는 비용 두 배이며 레버리지 두 배가 아니다. 세 lane의 원본 native 순수 산술함수와 독립 Decimal 검산을 비교했다. 실제 계좌 수수료·signed funding·체결을 입증한 수익이 아니며, trade-bps 합계는 계좌 수익률이 아니다. 모델끼리 합산하거나 전략 독립성·portfolio 수익으로 해석하지 않는다.

Keltner/Supertrend: 개별 29/26행의 identity·거래ID·경계·시간·가격→gross→cost→net 일치. 원시 캔들 SHA/가용·수신시각이 없고 source_summary의 수량·끝점만 남았다. 끝점 수량상 결손 추정0을 실제 gap0으로 인정하지 않았다. 해당 종목의 봉 완료시각을 사용한다. 순차 연패는 7/4거래, 동일시각 청산을 합한 연속손실은 6/3그룹. 순차 DD는 5,282.34/2,165.08 trade-bps. 계좌 DD와 승리보존율은 null이다.

Q0: 46 event=19 signal+17 finalized+10 stop witness. 10건의 원본 1m 2,400행에서 gap/duplicate0 및 최초 stop crossing·가격·시각을 대조했다. 그러나 진입17건 중14건의 원본4h 시가, 일반청산7건의 원본4h 시가 전부, 보유구간 원본4h 154행이 부족하다. 그러므로 손절 witness 성공을 전체 lifecycle 원천검증으로 확대하지 않는다. open0/censored0은 engine 원행과 대조한 값이다. Q0 순차손실은 같은 청산시각을 합한 9그룹이며 DD 2,780.88 trade-bps; 계좌 DD는 null이다. 1m stop 시각은 60초 구간의 상한으로 보존되며 실제 체결시각이 아니다.

Squeeze: 3 finalized의 event/hash는 일치하지만 원본 lifecycle preimage·native 가중 legs/체결가격·source window·펀딩 내역이 없다. gross 요약만으로 net을 만들지 않았다. 6개 unresolved signal에는 censored=true가 남아 있다. 마지막 원천봉 시각은 2026-09-25T16:00:00Z; 지금 fresh하다고 주장하지 않는다. TrendRider Unified: 32개 신호, finalized0; 계좌 포지션 여부는 불명. 별도 A1 Trend Rider 256T, K117, Shadow와 구분한다.

증명된 표시 결함: 기존 monitor는 K/S fresh_open_T를 상수0, Squeeze/Trend 누락값을 기본0으로 표시한다. 이 add-only witness parser는 actual_open_T=null과 unresolved/censored를 분리한다. 기존 collector/monitor/전략/원장 파일은 수정하지 않았다. 기본0을 실제 open0으로 해석하는 반례와 censored→closed 혼입·identity·경계·해시·중복·비용·1m 결손을 시험했다.

기존 Actions archive 경로와 collector 출력 코드를 확인한 범위는 ARCHIVE_ROUTES.json에 기록했다. 모든 과거 archive를 검색했다는 주장은 하지 않는다. 불완전한 현재 archive를 새 시세로 메우거나 과거 fresh 원천으로 재분류하지 않는다. 원천 archive 복구가 필요하면 기존 source owner가 정확한 원본 바이트/시각을 제공해야 하며 이 Work는 새 수집기를 시작하지 않는다.

검증: 18 unittest + K/S 원본행·반례 4묶음. 원본 input30개 SHA before/after/cache 일치. frontend canonical validate PASS. 상세 수치와 환경·입력·명령·출력 해시는 G5_ACCOUNTING_HANDOFF.json, KS_WITNESS.json, Q0_WITNESS.json, ST_WITNESS.json, VALIDATION.json, OUTPUT_HASHES.json에 있다.

기존 A 인계: owner=CLOUD_WORK_COORDINATOR_ISSUE1358_V1. SSOT_READ_ONLY_REVIEW.json의 점유는 관측 당시 기록이며 현재 권한으로 재사용하면 안 된다. A가 formal 소비를 고려하기 전 owner ref/OWNER/소비 claim 및 실제 global-heavy jobs를 다시 읽고 해제를 확인해야 한다. 이 패킷은 정식 경제 claim을 소비하거나 PASS를 부여하지 않는다. 먼저 아래 안전한 읽기 재현만 실행 가능하다. 신규 결과 디렉터리는 checkout 밖에 생성해야 한다.

```bash
git fetch origin work/g5-accounting-witness-20261023
git worktree add --detach /tmp/zel-g5-witness-20261023 FETCH_HEAD
cd /tmp/zel-g5-witness-20261023
task_output="$(mktemp -d /tmp/zel-g5-witness-result.XXXXXX)"
PYTHONDONTWRITEBYTECODE=1 python research/g5/accounting_witness_20261023/run_witness.py --source-root . --output-dir "$task_output/result"
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s research/g5/accounting_witness_20261023 -p "test_*.py" -v
```

출판 후 최종 보고의 immutable commit을 사용해 FETCH_HEAD를 그 SHA와 대조한다. repo에는 이 전용 폴더의 새 파일만 add-only [skip ci]로 저장한다. master merge/CI dispatch/배포는 필요 없으며 이번 범위에서 실행하지 않는다. 롤백은 이 전용 진단 브랜치/폴더를 사용하지 않는 것으로 충분하다. 운영 상태에는 적용되지 않았다.
