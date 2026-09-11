**G5A_FAIL_NO_G5B_ACTIVATION — 정식 OOS의 기존 개발 노출로 활성화 차단**

| 정식 G5A gate | 결과 | 확인 범위 / 실패 이유 |
|---|---|---|
| P0 | FAIL | 기존 참고자료를 exact 후보의 독립 mechanistic 증명으로 자동 승격하지 않음 |
| P1 | PASS | 동결 코드와 결속한 진입 feature causal map만 통과; 수익성 판정 아님 |
| P2 | FAIL | 전체 종속 코드의 숫자별 provenance·정당화 영수증 미완비 |
| P3 | FAIL | canonical holdout의 기존 개발 노출; 정식 경제 지표 미실행 |
| P4 | FAIL | exact canonical negative controls·ablation 실행 증거 없음 |
| P5 | FAIL | 서로 다른 provider의 실제 검토 영수증 없음; 구현 subagent 리뷰는 대체 불가 |
| P6 | FAIL | 독립 분할·immutable 원본·후보 비용/무결성 결속 미완비 |

| 필수 경제 보고서 | complete | 실제 producer receipt SHA |
|---|---|---|
| base_replay | false | null |
| realistic_cost | false | null |
| cost2x | false | null |
| purged_oos | false | null |
| chronological_split | false | null |
| symbol_decomposition | false | null |
| regime_decomposition | false | null |
| parameter_neighbor_stability | false | null |
| negative_controls | false | null |

| G5A 경제 gate | 결과 |
|---|---|
| net expectancy / PF / cost2 net | null / null / null |
| purged_oos_pass / no_cherry_pick | false / false |
| negative_controls_superior / no_leakage / duplicate | null / null / null — 미실행 값을 0 또는 PASS로 대체하지 않음 |
| 실제 9보고서 hash parity | false; 보고서 미완료 9/9 |
| 후보·data·cost envelope identity parity | true; 경제 실행 증거의 존재를 뜻하지 않음 |

정식 자격심사는 **1회** 실행했다. 변경하지 않은 `a1_alpha_proof_gate_v1.evaluate_bundle()`을 실제 호출했고, 경제 재생 전에 provenance gate에서 거절됐다. FULL·신규 후보·재시도는 **0**이다. 전략 손익이 음수임을 새로 측정했다는 의미가 아니다. 기존 USED_DEV 손익을 정식 자격심사 결과로 대입하지 않았다.

직접 차단 사유는 `CANONICAL_PURGED_OOS_ALREADY_USED_FOR_CANDIDATE82_DEVELOPMENT`이다. canonical purged OOS `[1778169600000, 1788609600000)`의 725개 4h 봉 중 candidate82의 USED_DEV SEEN2026 `[1778198400000, 1788566400000)`와 **720개, 99.3103%**가 겹친다. 구간은 기존 계약과 부모 SPEC에서 그대로 읽었다. 재분할·재다운로드·재생으로 독립성이 복원되지 않는다.

canonical 데이터 SHA는 `3a17c13bf38ba83d11a9246b99750fcd9bf4a29ef377023812b1cfc08febbd5a`, 원본 data_ref는 `6d6335d1c9ad7ecb1e9597da85c2eb87635561e1`이다. 이 checkout에는 원본 development manifest가 없다. 또한 기존 26봉 embargo는 lookback20+hold6에 대한 계약으로, 무기한 SMA10 runner의 purge 충분성을 증명하지 않는다. canonical 연구 비용은 G5A에서 허용하며, production 실제 funding 요구와 구분했다.

| Lifecycle·회계 검증 | 결과 |
|---|---|
| 진입 identity / D3 시점·1/3 수량 | PASS |
| partial 실제 체결 전후 exit ownership | PASS |
| floor / BE / completed UTC daily SMA10 우선순위 | PASS |
| 실제 반환 capacity / 같은 시각 close-before-fill | PASS |
| 독립 lot / pending reservation / symbol qty≤1 | PASS |
| 미완결 mark·censor / 강제 terminal exit 없음 | PASS |
| campaign별 비용·signed funding·leg 검산 | PASS, 합성 fixture 범위 |
| future mutation prefix invariance | PASS |
| 기존 3개 lane dispatcher passthrough | PASS |

새 lifecycle 어댑터 합성 테스트 32개, production evidence 합성 테스트 29개, qualification 합성 테스트 17개가 통과했다. 새 어댑터를 저장된 **105 campaigns·3,081 held-close observations·133 exit fills**와 직접 대조했다. 이 비교는 이미 승인된 entry 이후 전이에 한정한다. 기존 저장 전용 검증기가 별도로 **105 campaigns·3,328 trace**의 진입 승인·portfolio capacity·현금 원장을 확인했다. 이 검증들은 formal fresh credit 0이며 경제 평가·튜닝이 아니다.

새 evidence 모듈은 entry/partial/final leg의 실제 base qty depth VWAP, fee authority SHA, 지연, signed funding settlement, completed 5m path를 검산한다. 같은 봉의 MFE/MAE 선후는 UNKNOWN으로 표시하고 양끝 부분봉의 미관측 구간을 명시한다. 누락 component는 null/BLOCK이다. append-only 원장은 hash chain·flock·fsync·입력 재검산을 사용하며 동일 signal의 lot/campaign 이름 변경으로 T를 추가할 수 없다. PARTIAL과 OPEN/CENSORED의 formal T는 0이다.

**Production end-to-end readiness는 false다.** 실제 fresh source/fee/depth/funding을 수집한 것이 아니며, 여러 lot이 같은 호가를 공유하는 전역 선행 체결 증명은 아직 구현되지 않았다(`CROSS_LOT_SHARED_BOOK_PREFIX_WITNESS_NOT_IMPLEMENTED`). 이 경우 후행 lot의 증거는 차단된다. campaign 내부 동시 partial/final 검증 PASS를 운영 multi-lot 통합 PASS로 해석하지 않는다.

| Source / production 준비 | 결과 |
|---|---|
| 마지막 저장 clean-runner | 2026-09-07T06:38:21.993Z |
| stale authority | 14,400,000 ms; 저장된 9월 7일 자료는 현재 fresh 증명이 아님 |
| 기존 cutover invariant | 저장 PASS 보존; 현재 freshness와 별도 |
| 실제 Squeeze depth / fee / funding / 5m path | 수집하지 않음; production readiness false |
| dedupe·회계 | 합성 검증 PASS; 실제 fresh receipt 없음 |

| 최종 lane 상태 | 값 |
|---|---|
| strategy / candidate | Squeeze Continuation v1 / C70_TM_CAPREUSE_V1 / candidate82 |
| lane | SQUEEZE_CONTINUATION_V1_G5B_FRESH |
| runtime_registered / fresh_collection_started | false / false |
| activation_id / cohort_id / boundary UTC | null / null / null |
| freeze_boundary 실제 호출 | 0 — G5A PASS 전 호출 금지 준수 |
| formal_fresh_T / open_T / preboundary credit | 0 / 0 / 0 |
| historical_backfill / selection / promotion | false / false / false |
| execution / order / live | NONE / BLOCKED / BLOCKED |
| G5B terminal / G6 | false / false |

T6는 diagnostic, T12는 provisional이며 terminal이 아니다. 별도의 reviewed same-lane terminal receipt 전 G6를 허용하지 않는다. N_effective 임계치를 새로 만들지 않았다. G5A 실패가 확정되어 기존 cadence/concurrency owner에 새 collector를 연결하거나 registry를 변경하지 않았다.

동결 strategy digest `5c63d3a69e1398dd1fae1076c9e8bdc29b8252a3188ac6b6a79571b363b22a16`, parent merge `73b1277b218a1f178e424790271aa161d8ee9365`, implementation code `57e687ddda322c8ee347ad8f7e32a92a1328b918`, entry SHA `0b11cfe382c202b8df1affd054e2ce1bc7e805f1d6132aaf9069219c4532fc82`, exit SHA `673f353408884a8d2510185c1544bcd2afab9fa1448eff25ccfebeffd552fc91`를 보존했다. 새 adapter source SHA는 별도 파일 해시이며 기존 전략 digest를 대체하지 않는다.

기존 코드·증거 **321개 파일**의 hash를 보존했다. 기존 governance/source/bridge 테스트 55개가 통과했다. 기존 만료 테스트의 production source 입력이 저장 registry보다 갱신되어 먼저 hash 오류를 내는 문제는 테스트 fixture만 격리해 해결했다. 실제 gate의 hash·freshness 규칙은 바꾸지 않았다. 누계는 **84후보 / 152평가** 그대로다.

독립 리뷰에서 동시 partial/final, fee SHA 결속, MFE/MAE 순서, 누락 증거의 후속 보완, 동일 signal 중복 T 문제를 수선했다. 78개 합성 테스트를 독립 재확인했다. 이것은 G5A P5의 서로 다른 provider 리뷰를 뜻하지 않는다.

정식 심사 source/authority를 원격 `05234827e4d468e06813fb3c26935569ad4f2a98`에 먼저 고정하고 bytes를 read-back했다. 단일 실패 receipt는 `6fee57568f37b0ef0fb4594fdea10155845a0f5f`에 보존했다. `--verify-only` 및 최종 CI는 qualification/gate/경제 실행을 재호출하지 않는다. `G5A_QUALIFICATION_ATTEMPT.json`은 시작된 슬롯을 소비하며 재시도를 차단한다.

관련 승인: [Issue #1270](https://github.com/leegkssk2000-commits/vultr-z/issues/1270). 준비 인계 [Issue #1268](https://github.com/leegkssk2000-commits/vultr-z/issues/1268)는 이 결과로 종료한다. exact merge와 CI·status read-back 결과는 같은 폴더의 `EXACT_MERGE_VERIFICATION.json`에 기록한다.

배포는 필요 없다. 되돌릴 범위는 새 어댑터·검증 코드/workflow와 테스트 fixture 변경이다. 기존 부모·3개 운영 lane·권한·boundary는 보존했다. 이 실패를 근거로 자동 재튜닝·재시험·새 창·새 후보를 실행하지 않는다.
