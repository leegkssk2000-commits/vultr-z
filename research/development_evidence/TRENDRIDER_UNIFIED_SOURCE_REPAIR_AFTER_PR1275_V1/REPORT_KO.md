# TrendRider source repair — Issue #1276

**최종 상태는 `BLOCKED_TIMESTAMP_SEMANTIC`이다. 신규 시세 수집과 경제 실행은 모두 0회이며, Unified 수익성은 평가하지 못했다.**

Issue #1276 §2와 첨부 WORK_NEXT는 native timestamp 의미를 신뢰성 있게 결론내릴 수 없으면 이 상태로 종료하도록 명시한다. 이번 scope만 REPORT_ONLY로 종료하며 자동 재수집·추가 successor는 만들지 않는다. 이 차단은 경제적 REJECT나 `NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY` 판정이 아니다.

## Timestamp 의미 판정

| 구분 | 확인된 사실 | 남은 한계 |
|---|---|---|
| PR1275 원문 | 객체형 행의 `time` 1,000개, 모두 유일하며 1시간 간격 | open인지 close인지 구별하는 별도 필드 없음 |
| 실제 native 범위 | 2026-07-19 09:00∼2026-08-30 00:00 UTC | 이것을 확정된 open 범위라고 부르지 않음 |
| 요청 endTime | 1788047999999, raw 최대 timestamp는 요청보다 1ms 큼 | 한 응답으로 inclusive·반올림 구현을 특정할 수 없음 |
| 내부 소비자 | raw time을 변환 없이 bar_open_ts로 전달, 완료 시각은 +1시간 | 제공자 원본 의미를 독립적으로 입증하지 못함 |
| 공식 market 문서 | 같은 v3 endpoint를 배열로 설명하고 첫 원소를 open time, 일곱째를 close time으로 정의 | 실제 객체 `time`과 첫 원소의 대응을 명시하지 않음 |
| 공식 분석 예제 | 객체 `time`을 변환 없이 datetime index로 사용 | 그 index가 open인지 close인지 지정하지 않음 |

[공식 market reference](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/skills/swap-market/api-reference.md)와 [공식 분석 코드](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/skills/bingx-technical-analysis/scripts/analyze.py)를 대조했다. 문서의 배열 설명으로 실제 객체 스키마의 공백을 덮지 않았다. 조사한 공식 파일의 고정 commit, UTF-8 byte SHA, 위치와 한계는 DOCUMENTARY_EVIDENCE.json에 기록했다.

첫 preflight는 로컬 원문·소스만 사용해 네트워크 0회였다. 그 후 Issue §2의 공식 문서 확인 허용 조항을 적용해 공식 문서를 읽었다. **전체 네트워크 호출이 0회였다고 주장하지 않는다.** 이 문서 조회에는 신규 market API 요청이 없었고 다운로드한 skill을 설치·실행하지 않았다.

open-stamped와 close-stamped 해석이 관측된 timestamp 배열만으로는 모두 가능하다. 따라서 실제 적용할 canonical transform과 cursor rule은 null로 봉인했다. 근거 없는 ±1시간 이동은 적용하지 않았다. 독립 검토도 같은 차단 결론이다. 해제에 필요한 것은 제공자의 객체 `time` 정의 또는 원시 open/close 대응 증거이며, 이번 scope에서 이를 추정으로 대체하지 않는다.

원문 SHA256: `098fa627689d58fe765b79242f01eba144e978eead6e0b6debea9154a7ed2fb9`.
TIMESTAMP_SEMANTIC_RECEIPT.json의 raw bytes SHA256: `4000ca24b14ec53086de5baa94e03c1c68f9999cb9f717bfbcce88492d6592b5`.

## 수집기 수선 전후

| 항목 | PR1275 V1 | 준비된 V2 |
|---|---|---|
| native 의미 확인 | 기존 open 해석을 상속 | 별도 PASS·명시적 native open·수집 허용·원문 SHA·무보정 규칙 없으면 GET 이전 차단 |
| window membership | 경계 밖 timestamp 즉시 실패 | timestamp만으로 target 선택, 한정된 guard 격리 |
| 다음 페이지 | strict 페이지의 earliest−1ms | 의미가 승인된 경우에만 U=min(admitted), endTime=U−1ms |
| limit | remaining | min(1000, remaining+1) |
| 최대 페이지 / 재시도 | 10 / 0 | 3 per symbol / 0 |
| guard OHLC | 정규화 없음 | 값 해석 없이 원문 보존, 경제 입력 0 |
| 성공 조건 | exact1000·동일 clock | 동일 조건, admitted duplicate/gap/malformed 0 |
| 실자료 결과 | BTC 경계 실패, ETH 미요청 | **미수집: 의미 gate에서 차단** |

V2는 raw bytes/hash/request metadata를 JSON decode 전에 저장하며 단일 attempt marker로 재호출을 막는다. 페이지 내부 중복은 guard라도 거부한다. 이전 페이지의 경계가 다음 페이지에 guard로 반복되어도 admitted dataset에는 중복되지 않는다. lower extra guard는 남은 target 전체가 채워지는 마지막 추가 슬롯만 허용한다. 시간값 자체는 이동하지 않는다. 이 규칙은 합성 데이터에서만 시험했으며 실제 endpoint 수선 성공을 주장하지 않는다.

## 고정 계약과 평가 상태

기존 정책·엔진·G1∼G6·비용·분할·게이트·Pareto를 변경하지 않았다. PR1275 계약 SHA는 `b8e37cd4ebd58425c9e13917d77230994f5dec1b48dc57543bd2d0d4a409e813`이다. 기존 코드와 증거 65개 파일을 PRESERVED_FILES.json으로 결속했다. 시작 master `708c222c95c43162908ea86278385876c27e5f28`과 이후 이력을 보존한다.

고정 target clock은 각 symbol 1,000개: 2026-07-19 08:00∼2026-08-29 23:00 UTC이다. 그러나 BTC/ETH normalized bytes·data SHA·DATA_FREEZE_V2는 **없다**. 미수집을 빈 데이터셋의 실측 결과로 표시하지 않는다.

| 구간 | index | signal UTC 범위 | 상태 |
|---|---|---|---|
| Warmup | [0,64) | 2026-07-19 08:00∼07-22 00:00 | 계약만 유지, 경제 credit 0 |
| DEV_A | [64,532) | 2026-07-22 00:00∼08-10 12:00 | 미실행 |
| DEV_B | [532,1000) | 2026-08-10 12:00∼08-30 00:00 | 미실행 |

각 경제 구간의 signal timestamp는 468개이며 구간별 flat 시작, 구간 밖 next-open 진입 금지는 그대로다. 공통 정적 DEV 비용 14bps와 정확한 2배 비용 28bps도 유지한다.

다음 표는 **DEV_A와 DEV_B 모두**에 적용된다. N/A는 미실행이며 손익 0의 실측치가 아니다.

| 공통 지표 | P_COMMON | B_COMMON | U1 | U2 |
|---|---|---|---|---|
| eligible / completed / open / unfilled | N/A | N/A | N/A | N/A |
| WR / terminal net / expectancy / PF / payoff / cost2 | N/A | N/A | N/A | N/A |
| 평균 승리·손실 / worst / loss-tail / 연패 | N/A | N/A | N/A | N/A |
| closed·marked DD / exposure / conflict / top1 | N/A | N/A | N/A | N/A |
| overlap / P-only / B-only / donor attribution | N/A | N/A | N/A | N/A |
| feature·intent lineage / 승리 보존 / 추가 비용 | N/A | N/A | N/A | N/A |

Stage1 DEV_A 6개 screen, 최대2 생존자 봉인과 DEV_B confirmation, U1/U2 FULL 및 final selection은 모두 미실행이다. 기존 Primary/Broad 성적을 공통 경제표에 옮겨 넣지 않았다. Unified exact seal·prospective G5A handoff는 없으며 formal credit 0이다. G5A/G5B 미래 데이터 경계나 기존 prospective 원장도 변경하지 않았다.

## 실행 예산과 검증

| 항목 | 승인 상한 | 실제 |
|---|---:|---:|
| successor acquisition | 1 | 0 |
| BTC / ETH HTTP pages | 각 3 | 0 / 0 |
| controls | 4 | 0 |
| DEV_A screen / DEV_B confirmation | 6 / 2 | 0 / 0 |
| candidates / child FULL | 2 / 4 | 0 / 0 |
| retry / sweep / prospective decode | 0 | 0 |
| paid AI / live / order / deploy | 0 | 0 |

신규 V2 수집기의 합성 테스트가 PASS했다. inclusive guard 보충, strict endpoint, 마지막 lower extra guard, 3페이지 상한, gap·중복·malformed, semantic/hash 차단, raw 우선 저장, HTTP 오류·timeout 재시도 금지와 단일 attempt를 검사했다. 기존 common 회귀와 새 저장 검증도 실행하며, 확정 테스트 수와 PR CI·자동 리뷰·정상 병합·정확한 merge SHA 결과는 별도 EXACT_MERGE_VERIFICATION.json에 결속한다. 저장 검증 CI는 모든 master PR/push에서 실행하고 실자료 취득·경제 재생을 하지 않는다.

변경 범위는 신규 source V2, 합성 테스트, 읽기 전용 저장 검증기·workflow와 이번 차단 증거다. 경제 owner 준비 코드는 이번 PR에 포함하지 않았다. 배포는 필요 없다. 신규 연구 코드와 workflow의 정상 revert로 기능 추가를 되돌릴 수 있다. native 의미와 실자료 window 수선은 여전히 미검증이며, 새 실행에는 별도 후속 권한과 증거가 필요하다.
