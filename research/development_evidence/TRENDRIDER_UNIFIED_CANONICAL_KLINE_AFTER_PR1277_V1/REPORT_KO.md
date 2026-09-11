# TrendRider canonical kline calibration — Issue #1278

**실제 진단 요청 2회를 완료했다. 최종 판정은 `BLOCKED_CANONICAL_KLINE_SCHEMA`이며 common source·경제 실행은 0회다.**

두 응답 모두 객체형이고 `time`은 각각 요청한 hour와 일치했다. 그러나 공식 배열의 openTime/closeTime과 객체 `time`을 연결하는 독립 witness는 없었다. Issue1278 §2의 사전 고정 조건에 따라 이 일치만으로 open mapping을 승인하지 않았다. 이 판정은 경제적 실패나 유전자 REJECT가 아니다. 이번 scope만 REPORT_ONLY로 종료한다.

## 공식 authority와 사전 봉인

공식 repository `BingX-API/api-ai-skills`의 시작 시점 main은 `5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6`이었다. 고정된 3개 문서의 UTF-8 bytes로 Git blob SHA와 tree byte count를 직접 검증했다.

| 공식 문서 | Git blob SHA | 확인한 내용 |
|---|---|---|
| [swap-market/api-reference.md](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/skills/swap-market/api-reference.md) | `53e345a26fe6b79a448c6f848124834ad2c3c404` | v3 klines 배열 [0]=open time, [6]=close time |
| [swap-market/SKILL.md](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/skills/swap-market/SKILL.md) | `d7f19cb5a99a1d94c29b53933959f5df3068d5b5` | 같은 배열 순서의 common-call 예제와 X-SOURCE-KEY |
| [README.md](https://github.com/BingX-API/api-ai-skills/blob/5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6/README.md) | `d8b4c04f27fd61751f68a1c35cd19d82df7b1584` | swap-market의 API key 없는 공개 조회 허용 |

모듈의 서명 요구 문구와 README의 공개 조회 허용은 서로 일치하지 않아 그 한계를 함께 기록했다. API key·서명을 요청하거나 대체 인증을 시도하지 않았다. 공식 문서의 header가 응답 형태를 바꾼다는 주장도 하지 않았다. 공식 문서 조회는 5회이며 시장 진단 요청과 분리했다.

| 결과 전 봉인 | SHA |
|---|---|
| 원격 commit | `f24b303a7f9e813ce9264b903d0323caa622cc42` |
| PREEXEC_FREEZE raw SHA256 | `9ecb6ad6aca051a4a87026abd283d9e36bccbb526f8ba15aad6dc1027389d1d9` |
| PROBE_PROTOCOL raw SHA256 | `fcb3024af37eba7f2646db3413b8315b93778952b8e385e60711cb3c06169776` |
| 공식 schema receipt raw SHA256 | `5fda7a4b18fdb288e33ff2b0373211a0d52687fb4b03a49fcd7ae63d003077b6` |

신규 코드·테스트·계약·protocol·출처 등 9개 파일을 결과 전에 봉인했다. 원격 manifest를 다시 읽어 일치를 확인했고, 실제 요청 직전에 해당 9개와 기존 보존 파일 80개의 SHA를 검증했다. 시작 master `38d550c05b7b42c2874556dd7bb823c513263189`와 이후 이력은 보존한다.

## 실제 probe 결과

공통 endpoint는 `https://open-api.bingx.com/openApi/swap/v3/quote/klines`다. 두 요청 모두 BTC-USDT·1h·limit3이며 startTime=T, endTime=T+3,600,000−1ms로 고정했다. 두 시간은 경제 target 이전이다.

실제 명시 헤더는 `Accept: application/json`, `X-SOURCE-KEY: BX-AI-SKILL`, `User-Agent: Python-urllib/3.12`, `Accept-Encoding: identity`, 해당 Host와 Connection close다. urllib의 header 정규화 표현도 별도로 저장했다. 요청 URL/query·헤더를 GET 전에, 원문 bytes·status/header·SHA를 JSON decode 전에 저장했다. 응답 헤더는 mapping으로 기록하여 중복 헤더 값이 투영될 수 있음을 명시했다.

| 항목 | Probe A | Probe B |
|---|---|---|
| 요청 hour UTC | 2026-07-18 00:00 | 2026-07-18 01:00 |
| startTime ms | 1784332800000 | 1784336400000 |
| endTime ms | 1784336399999 | 1784339999999 |
| HTTP / API code | 200 / 0 | 200 / 0 |
| 실제 행 수 | 1 | 1 |
| 실제 schema | object | object |
| 시각 필드 | time만 존재 | time만 존재 |
| 실제 time ms | 1784332800000 | 1784336400000 |
| 공식 배열 [0]/[6] 직접 관측 | 없음 | 없음 |
| raw bytes / 잘림 | 139 / 없음 | 139 / 없음 |
| 판정 | cross-schema witness 없음 | cross-schema witness 없음 |

| 원문 | SHA256 |
|---|---|
| Probe A | `4e7593e554612a4e724cf63dd0b0df2ee5cfb4c1377fc61f9142cee02b8cac8c` |
| Probe B | `d51d63a1b8a785c76d9ca7f39f23652c45a2c2096a2c97a9b098abfbba3f75d9` |
| CANONICAL_KLINE_TIMESTAMP_RECEIPT raw bytes | `cb87ac92de860cf3465ef94f67428ca1c0204977d4064a18f1cf8720da501bc7` |

요청한 hour와 객체 time의 일치는 이번 두 표본에서 확인했다. 이 사실은 별도의 array/object 대응을 증명하지 않는다. 따라서 open/close transform·native close convention·source lane을 모두 null로 남겼고 source acquisition 권한을 false로 기록했다. price continuity·수익·feature로 시각 의미를 역추정하지 않았다.

사전 규칙은 배열 응답의 native close−open이 3,599,999ms 또는 3,600,000ms이며 모든 행과 두 probe에서 같은 규약일 때만 허용했다. guard는 목표 전후 1시간만 허용했고 가격값은 해석하지 않았다. 실제 응답은 객체형이라 이 배열 PASS 분기는 사용되지 않았다. ±1시간 보정, header 변경, 추가 probe, fallback·재시도는 모두 0이다.

## Source·경제 계약과 미실행 항목

BTC/ETH common dataset 취득은 시작하지 않았다. DATA_FREEZE_V3·normalized bytes·combined dataset SHA는 없다. probe 원문은 timestamp 진단 증거이며 경제 입력이 아니다.

| 고정 항목 | 계약 | 실제 |
|---|---|---|
| 각 symbol open clock | 2026-07-19 08:00∼08-29 23:00 UTC, exact1000 | 미수집 |
| cutoff | 2026-08-30 00:00 UTC | 유지 |
| Warmup | index [0,64), 경제 credit0 | 미사용 |
| DEV_A | [64,532), 07-22 00:00∼08-10 12:00 UTC | 미실행 |
| DEV_B | [532,1000), 08-10 12:00∼08-30 00:00 UTC | 미실행 |
| 비용 normal / cost2 | 정적 DEV 14 / 28bps | 유지, 미평가 |

B_COMMON, P_COMMON, G1∼G6, 진입·청산·크기·분할·게이트·Pareto 등 16개 경제 계약 구획은 PR1275와 정확히 동일하다. 원래 정책과 PR1275/1277 코드·증거 80개 파일도 해시로 보존했다. 이번 차단으로 새로운 후보 번호나 경제 성적을 생성하지 않았다.

다음 표는 DEV_A와 DEV_B 모두에 적용된다. **N/A는 미실행이며, 실측 손익 0 또는 거래 0건의 결과가 아니다.**

| 공통 경제 지표 | P_COMMON | B_COMMON | U1 | U2 |
|---|---|---|---|---|
| eligible / completed / open-censored / unfilled | N/A | N/A | N/A | N/A |
| WR / net / expectancy / PF / payoff / cost2 | N/A | N/A | N/A | N/A |
| 평균 승리·손실 / worst / loss-tail / 연패 | N/A | N/A | N/A | N/A |
| closed·marked DD / exposure / conflict / top1 | N/A | N/A | N/A | N/A |
| overlap / P-only / B-only / feature·intent lineage | N/A | N/A | N/A | N/A |
| donor attribution / 승리 보존 / 추가 비용·점유 변화 | N/A | N/A | N/A | N/A |

Stage1 screen·생존자 선택·DEV_B confirmation·U1/U2 FULL·final Pareto는 미실행이다. 따라서 NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY 또는 TREND_RIDER_UNIFIED_NOT_EARNED_COMMON_REPLAY라는 경제 판정을 내리지 않았다. Unified exact seal과 prospective G5A handoff는 없고 formal credit0이다. 기존 prospective ledger·G5A/G5B 시간 경계는 수정하지 않았다.

## 실행수·검증·종료

| 항목 | 상한 | 실제 |
|---|---:|---:|
| timestamp diagnostic REST probes | 2 | **2** |
| common source attempts | 1 | **0** |
| common source BTC / ETH pages | 각3 | **0 / 0** |
| controls | 4 | **0** |
| DEV_A screen / DEV_B confirmation | 6 / 2 | **0 / 0** |
| candidates / child FULL | 2 / 4 | **0 / 0** |
| retry / sweep / arbitrary OOS / prospective decode | 0 | **0** |
| Squeeze data / paid AI / live / order / deploy | 0 | **0** |

사전 probe 합성 테스트 **24개 PASS**. 배열 close 규약·guard·객체/혼합 schema·중복/오류·원문 우선 저장·요청 header·단일 attempt·2회 상한·HTTP 실패와 대기 중 입력 변조 차단을 포함한다. 독립 리뷰의 대기 구간 변조 P2는 결과 전에 수정했다. 기존 회귀·저장 검증·frontend 검증과 PR CI·자동 리뷰·정상 병합·정확한 merge SHA의 최종 결과는 EXACT_MERGE_VERIFICATION.json에 결속한다.

변경 파일은 신규 probe/합성 테스트, 읽기 전용 saved verifier/테스트/workflow와 이번 증거다. calibration이 차단되어 V3 source collector와 준비된 경제 owner는 이번 PR에 넣지 않았다. CI는 모든 master PR/push에서 저장 증거와 합성 입력만 확인하며 실제 시장 요청·경제 재생을 하지 않는다.

배포는 필요 없다. 신규 연구 코드와 검증 workflow를 정상 revert하면 기능 추가를 되돌릴 수 있다. 잔여 조건부 실행 예산은 이 terminal 판정으로 종료하며 자동 successor를 만들지 않는다. 향후 필요한 것은 객체 time과 공식 array openTime을 직접 연결하는 독립 source 증거 또는 실제 공식 array 응답이며, 이번 2회 권한을 넘어 이를 추가 수집하지 않았다.
