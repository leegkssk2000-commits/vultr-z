# TrendRider REST↔WS timestamp — Issue1280 결과

**단일 WS 세션은 로컬 ACK 분류 버그로 실패했다. 경제 평가는 실행하지 못했다.** 최종 상태는 `BLOCKED_REST_WS_TIMESTAMP_WITNESS`, 직접 원인은 `IMPLEMENTATION_ACK_CLASSIFICATION_FAILURE`다. 원문·고정 실행본·검증 공백을 보존하고 이번 범위를 REPORT_ONLY로 종료한다.

서버는 HTTP101로 연결을 열고 성공 코드0의 구독 ACK를 반환했다. 그 ACK의 `data:null`을 검증기가 처리하지 못해 kline을 기다리기 전에 종료했다. 이는 이번 구현과 사전 검토의 결함이다. 거래소가 잘못된 kline을 보냈거나 데이터를 제공하지 않았다는 증거도, REST time 의미가 틀렸다는 증거도 아니다. 전략의 경제적 REJECT 판정을 내리지 않았다.

## 실제 실행과 원인

| 항목 | 실제 |
|---|---|
| WS endpoint | wss://open-api-swap.bingx.com/swap-market |
| 구독 | BTC-USDT@kline_1h, 1회 |
| handshake | HTTP101 |
| 수신 frame | GZIP binary 1개, 104bytes |
| frame 종류 | 성공 구독 ACK |
| ACK id / code | trendrider-rest-ws-1280-v1 / integer0 |
| ACK dataType / data | 빈 문자열 / null |
| kline 관측 / REST 요청 | 0개 / 0회 |
| 세션 경과 | 14.241736초 |
| 구독→ACK / ACK→종료 | 184ms / 5ms |
| native/canonical 시각 witness | 없음 |

첫 frame을 해제한 원문은 다음과 같다. 제시된 메시지는 저장된 진단 응답이며 어떤 kline의 OHLC도 아니다.

```json
{"id":"trendrider-rest-ws-1280-v1","code":0,"msg":"","dataType":"","data":null}
```

동결 함수 `decode_ws`는 ACK를 판별할 때 `data` 키가 **없는 경우만** 허용했다. 실제 ACK에는 키가 있고 값이 null이므로 이 분기를 통과하지 못했다. 이어지는 kline 전용 `dataType` 검사에서 `REST_WS_CHANNEL_IDENTITY`가 발생했고, 소유 실행기는 즉시 종료했다. 기록된 오류 문자열만으로 거래소 채널 오류라고 해석하면 원인을 잘못 보고하게 된다.

사전 calibration 합성시험36개는 ACK→kline 순서를 포함하지 않았다. 성공 fixture는 kline 또는 Ping으로 바로 시작했고 FakeWS.send는 구독 ACK를 생성하지 않았다. root가 실행 전에 data:null 변형을 지적했지만 동결 구현·시험·독립 검토에서 이를 해소하지 못했다. `ACK_POSTMORTEM.json`과 `ACTUAL_SESSION_AUDIT.json`에 이 검증 공백을 명시했다.

필요한 최소 수선은 구독 control ACK 분류를 kline 검사보다 먼저 수행하고, 일치하는 id·정수 code0·data 없음/null을 구분하는 것이다. 이어 실제 ACK→kline→REST, ACK만 수신, 잘못된 id/code, 실제 kline의 채널 불일치를 각각 검증해야 한다. **이번 실제 실행 이후 동결 코드를 바꾸거나 재접속하지 않았다.** 실패한 실행본은 재현 증거로 보존한다.

## 원문과 사전 봉인

| 증거 | SHA256 또는 commit |
|---|---|
| WS GZIP 원문104bytes | `c2a99fa6fbc419b920094c7d7c82c005be42b55707687f076935ad6e23d61eaa` |
| REST 원문 | 없음: 요청0회 |
| REST_WS_TIMESTAMP_SEMANTIC_RECEIPT raw SHA | `2e96055dd29f965537138befbdb0b8bf744cd660e03cb4f7c5810337da0d1efe` |
| 사전 원격 commit | `52973ade72455bdc7211fb9da23f75277c2dbecd` |
| PREEXEC_FREEZE raw SHA | `36c688494f96b2a3c86bd6674762ee2159e0c319e9e51beb051d407c90f145fb` |
| PROBE_PROTOCOL raw SHA | `f9cc39e14a0d4d760391936ce42273de39f448dd40ffb109bdeed6795cd1e153` |
| OFFICIAL_REST_WS_AUTHORITY raw SHA | `33fa8b9fe2a5ffb5a23926c44efd0840cd5e36cd6572dd48b6162382329fe923` |

WS application 원문과 수신 metadata를 GZIP/JSON 해석 전에 기록했다. 연결·구독 요청도 전송 전에 기록했다. application Ping/Pong은 각각0회다. 원격 manifest를 다시 읽고 고정15개·보존108개 파일 SHA를 확인한 뒤 첫 세션을 시작했다. 실제 응답 이후에도 모든 해당 SHA가 그대로다.

시작 master는 `9542b7a45be7a6bafa7dced8df423ff77d81ebff`였다. 봉인 전에 추가된 기존 A1 기록 commit `d5faadf1fac37626d93dce3a9ef46fa4a955c4b3`를 fast-forward로 보존했다. 과거 PR1275/1277/1279 결과를 수정하거나 재실행하지 않았다.

## 외부 authority

공식 BingX commit `5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6`의 WS 문서는 `data.K.t`를 시작, `data.K.T`를 종료 시각으로 정의한다. 이 정의와 구독·GZIP·Ping/Pong 규약을 고정했다. 실제 kline은 관측하지 못했으므로 문서 정의를 live witness로 대신하지 않았다. [공식 WS 필드](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/skills/swap-ws-market/api-reference.md)

같은 공식 commit의 REST 문서는 배열 [0]/[6]을 시작/종료 시각으로 정의한다. 객체 `time`을 자동으로 동일시하지 않았다. [공식 REST 문서](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/skills/swap-market/api-reference.md)

보조 CCXT commit `2c12ed10599deebe19925645bf65491380607203`의 BingX adapter는 linear swap OHLCV를 v3 klines로 조회하고 객체의 time을 우선 사용한다. 같은 parser에 closeTime fallback도 있어 이것만으로 의미를 확정할 수 없다. 코드를 설치하거나 실행하지 않았다. [CCXT 고정 소스](https://github.com/ccxt/ccxt/blob/2c12ed10599deebe19925645bf65491380607203/python/ccxt/bingx.py)

공식 자료4개와 CCXT 소스1개의 commit·Git blob·UTF8 SHA를 검증했다. GitHub 읽기8회이며 시장 진단 예산과 구분했다. authority 영수증에 전체 경로·해시를 보존했다.

## Historical source와 경제 미실행

semantic PASS가 없으므로 source authorization과 DATA_FREEZE_V4를 만들지 않았다. 정규화 BTC/ETH 파일·per-symbol SHA·combined SHA도 없다. 준비된 V4 수집기는 실행하지 않았고, 준비된 경제 owner는 저장소 실행 코드에 넣지 않았다.

| 고정 항목 | 계약 | 실제 |
|---|---|---|
| BTC/ETH source | 각 exact1000, 1h | 미수집 |
| canonical open clock | 2026-07-19 08:00∼08-29 23:00 UTC | 미수집 |
| cutoff | 2026-08-30 00:00 UTC | 유지 |
| warmup | [0,64), 경제 credit0 | 미사용 |
| DEV_A | [64,532), 468개 시점 | 미실행 |
| DEV_B | [532,1000), 468개 시점 | 미실행 |
| normal / cost2 | 정적 DEV 14 / 28bps | 미평가 |

다음 표는 DEV_A와 DEV_B 모두에 적용된다. **N/A는 미실행이며 손익0 또는 거래0건의 실측 결과를 뜻하지 않는다.**

| 경제 지표 | P_COMMON | B_COMMON | U1 | U2 |
|---|---|---|---|---|
| eligible / completed / open-censored / unfilled | N/A | N/A | N/A | N/A |
| WR / net / expectancy / PF / payoff / cost2 | N/A | N/A | N/A | N/A |
| 평균 승리·손실 / worst / loss-tail / 연패 | N/A | N/A | N/A | N/A |
| closed·marked DD / exposure / conflict / top1 | N/A | N/A | N/A | N/A |
| overlap / P-only / B-only / feature·intent lineage | N/A | N/A | N/A | N/A |
| donor attribution / 승리 보존 / 추가 비용·점유 변화 | N/A | N/A | N/A | N/A |

B/P·G1~G6·비용·분할·진입/청산/크기·hard gates·Pareto 등 경제 계약16개 구획은 PR1275와 canonical bytes가 동일하다. DEV_A 선택·DEV_B 확인·U1/U2 FULL·최종 후보 선택을 하지 않았으며 새 후보 번호도 소비하지 않았다. 경제 실패 enum을 만들지 않았다.

Unified exact seal과 prospective G5A handoff는 없다. formal credit0, G6 승격 권한도 없다. 기존 prospective 기록이나 G5A/G5B 시간 경계를 변경하지 않았다.

## 예산·검증·종료

| 항목 | 상한 | 실제 |
|---|---:|---:|
| calibration session / WS subscribe | 1 / 1 | **1 / 1** |
| diagnostic REST | 2 | **0** |
| session duration | 180초 | **14.241736초** |
| common source attempts | 1 | **0** |
| BTC / ETH source pages | 각3 | **0 / 0** |
| controls | 4 | **0** |
| DEV_A screen / DEV_B confirmation | 6 / 2 | **0 / 0** |
| candidates / child FULL | 2 / 4 | **0 / 0** |
| retry / refetch / sweep / prospective decode | 0 | **0** |
| Squeeze data / paid AI / live / order / deploy | 0 | **0** |

사전 전체 시험215개와 frontend validate는 통과했다. calibration36·source36 통합 시험과 준비된 owner29개도 합성 입력으로 통과했으나 실제 ACK 호환성은 실패했다. **시험·CI PASS는 실패 증거의 일관성을 검증한다. 실제 연동이나 경제 성능 PASS를 뜻하지 않는다.** 읽기 전용 saved verifier는 실제 ACK를 독립 판독해 구현 오류를 확인하고 원문·예산·동결 이력을 검증한다. 새로운 WS·REST·경제 재생을 하지 않는다.

변경 범위는 신규 calibration/수집기/합성 테스트, 읽기 전용 저장 검증기/시험/workflow와 이번 증거다. 배포는 필요 없다. 기능 추가는 새 코드·workflow의 정상 revert로 되돌릴 수 있고 과거 실패 증거는 보존해야 한다. CI·자동 리뷰·정상 PR 병합·정확한 merge SHA 검증·최종 영수증 결과는 EXACT_MERGE_VERIFICATION.json에 결속한다.

Issue1280은 실패 시 terminal 종료와 retry0을 명시했다. 이번 세션 뒤 추가 연결·수집·평가·자동 successor는 실행하지 않았다. 조건부 잔여 예산은 terminal에서 종료한다.
