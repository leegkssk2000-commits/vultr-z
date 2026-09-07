# STEP7 — KR3 정확한 후보에서 독립 검증으로 연결

주심사 후보는 KELTNER_KR3_PRIOR_SUPPRESSED_BREACH_EXTENSION_VETO_DEV_V1의 FULL이다. 기존44건·PR1207·API0/0·모든 부분 개선/실패를 승계하며 신규 전략/SL/TP/퓨전은 실행하지 않았다. session_status=CHECKPOINTED / REPORT_ONLY, implementation_and_data_status=IMPLEMENTATION_MERGED_REPRODUCED_SOURCE_SNAPSHOT_STORED_FULL_EVIDENCE_INCOMPLETE, economic_campaign_status=BLOCKED_AUTHORITY_AND_INDEPENDENT_EVIDENCE. G5A 자격과 새 G5B terminal은 모두 미달이다.

| KR3 저장 경제성 | 종료 | 승률 | PF | 손익비 | 종료 순손익 | 미완결 포함 terminal 가상 순손익 | 전체 cost2 가상 순손익 | DD | 미완결 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV2025 | 202 | 41.09% | 1.273 | 1.825 | +10,341.73 | +10,265.00 | +5,744.23 | 11,727.79 | 1 |
| 기사용 SEEN2026 | 75 | 33.33% | 1.426 | 2.853 | +5,363.56 | +4,746.58 | +3,002.13 | 4,093.69 | 4 |

단위 trade-bps 합계, 계좌수익률 아님. 위 수치는 기존 receipt에서 읽었으며 재합산/재생하지 않았다. 두 기간 모두 기존 TRADEOFF: 불확실성 하한과 미완결 문제가 남아 있다. 정식 G5A/G5B 경제성으로 재분류하지 않는다.

**부모 정의·계보.** LINEAGE.json에 native Primary/Broad·TPR1/TPP1/TPC1/TPQ1, KR3, Break V2/BR1/BR2, Q0 원본, Supertrend V2/SR1과 ATR 보고를 구분했다. Q0는 BREAK_CHANNEL_SOURCE 원본 Q와 SEEN2026 A_Q0이며 Q1 child receipt로 대체하지 않는다. Q0 86+34 재합산·Q_minus·기존자격심사·기존재현 모두 미실행이다. 기존 KR3 1469 checks/203 seals는 저장증거만 재사용했다.

**ATR.** 원본증거미확인으로 한정 종료했다. 보고17T/14W/82.35%는 원래 entry/SL/TP/timeframe/17receipt 연결이 없다. 별도 WR81.25, PR983 discovery, PR1164 Dynamic-HTF, ATR14 이름을 ATR17로 대체하지 않는다. 일부 과거 blob 검색은 network approval cancelled로 불완전이며 부존재 근거가 아니다. ATR 경제확대0·새후보0. 다음 회수에 필요한 원천은 당시 보고에 연결된 실제 PR/run/artifact, 생성 코드·정책, 원본17행 receipt다.

**실제 구현·시험.** 후보 계약은 KR1.replay 진입·점유와 KR3.path 청산의 파일/함수 AST 해시를 연결했다. 9종 producer/input/output 실제바이트 결속과 조건부 TIME_STOP_ONLY 오연결 거절을 구현했다. KR3의 초기SL/TP=None, cap24는 관측봉 index라는 점과 실제 D참조예약을 보존한다. Q0는 cap=None, trigger LAST/MARK/INDEX 및 정확한 intrabar 체결시각 미결을 그대로 차단한다.

검증 guard는 기존캠페인 독립1묶음, 고정후보/승인/정보격리/검토시각/조회예약을 구현했다. 제공된 봉인 원장을 대상으로 실제 label/reference overlap purge·embargo/runoff·창/종목/regime별 cost/cost2 계산 producer를 추가했다. cost2 누락/중복 재봉인 반례도 거절한다. 실제9종 native경제·대조군·neighbor replay producer 전체가 완성된 것은 아니다. 파생 합성결과는 SYNTHETIC_DERIVED_REPORT이며 실제시장/G5증거가 아니다.

**실제 원천.** 기존 forward caller는 g5_forward_real_evidence_bridge_v4이며 active V2용 TIME_STOP_ONLY 경로다. 본 작업은 이를 교체하지 않는다. 선택된7종목과 기존 canonicalsource계약을 비교하여 public depth·240개4h OHLC·funding각1회, contracts공통1회인 최대22GET/1묶음을 준비했다. 첫오류종료·retry0, stream+symbol cursor, 원본sha공유, 재시작gap격리, parse online/offline동일성, 가용시각과native 다음시가 참조 검사를 구현했다. 실제시그널·체결·원장 parity는 아직 미실행이며 현재 snapshot으로 과거호가/체결을 복원하지 않는다.

로컬 요청은 network approval cancelled before a decision was returned로 시장HTTP0. 승인된 기존 GitHubActions 실행환경의 고정merge push에서 root사전예약 source1묶음을 실제 실행·저장했다. 동일SHA 최초push run/run_attempt1만 허용하고 같은실험 새파일/재시도 우회는 차단한다. 실제원본은 가격이 개발자에 노출되지 않는 source artifact90일로 보존하고 공개메타/커서만 결과에 연결한다. 실제 결과는 아래 확정기록과 SOURCE/RUN_RECEIPT.json에 연결했다. 상시 수집기 추가나 Work시장대기는 없다.

**정식 승인안 하나.** AUTHORITY/APPROVAL_BUNDLE.json 및 .md의11항목은 PENDING_AUTHORITY다. 무보호SL 연구cohort와 ATR20 통계R(계좌risk-R 아님), KR1 actualFULL 승리금액 retention, 승인·source준비후 시작30일×3, 실제점유overlap purge와96h embargo/7일runoff종료검토, causalregime/UTC일·점유연결군집, 최소5bps/component·power80%·familywise alpha.05/7, 동일sealed자료의4개control과6개neighbor, 완료봉60s/BBO2s·수신1s/RTT2s/clock500ms 한계, 2종목이상/단일종목양의이익50%이하/최대승리제거후양수 제안이다. 기존G5A/G5B 수치와 errors/duplicate/censored_open/unknown_exit=0은 유지한다. 모두 미사용성과 전에 제안한 값이며 기존승인으로 위장하지 않았다.

S2 원형parameter목록은 EMA20/50,HOLD12다. 이웃6개 (19,50,12),(21,50,12),(20,49,12),(20,51,12),(20,50,11),(20,50,13)는 승인전비활성이다. 파생cap2HOLD·판단HOLD-1·D참조예약까지 전파하며 최적값선택/새전략승격은 금지한다. controls/neighbor는 동일sealed candidate/data/cost묶음에서 한 번 평가해야 하며 기사용DEV p값으로 대체하지 않는다. 미정실행의미/producer/source가 남으면 실행을 차단한다.

**G5 상태.** G5A exact application 연결은 구현됐지만 승인된P0~P6/9종독립실행·realisticcost provenance가 없어 qualified=false. 독립 검증0/1, 개발자의 봉인성과접근0. G5B 신규boundary/cohort등록0, 적격freshT0, terminal PASS0. G5A 검증분을 G5B fresh로 소급합치지 않는다. historical G4/DEV 자격과 신규G5B를 구분한다.

**담당 산출물.** Root 선택/원장/직렬실행/통합; S1 ATR한정회수 종료; S2 candidatecontract8개새시험 및정확parameter목록; S3 canonicalsource12개새시험; S4 preregistration/derivedproducer16개새시험·승인안. Rootsource dispatch3개시험. 개발자 S4는 후속sealed경제executor를 맡지 않는다. 실제 독립검증은 이설계·개발에 참여하지않은 별도권한담당이 맡아야 한다. 기존완료시험은 로컬에서 재실행하지 않고 관련새CI에만 포함한다.

**정확한 후속.** 승인묶음b6d453587b6899c0fbf3a19530e6c9b4f0609266f51a302375330a1ebea04132의 승인여부·noSL허용이 먼저 필요하다. root는 승인receipt를 실제사용자승인에결속하고 candidate_contract→preregister→영속reserve_access 순으로 이어간다. 판정에 필요한 source definition/비용규약 및 finitecontrol producer가 미정이면 sealed read를 시작하지 않는다. 이후 source담당은 기존승인서비스에서 동일canonicalstream/정확seed/entry-exit BBO·signedfunding을 수집하고 별도검증자가 고정review시각에 1묶음만 평가한다. 공식cohort는 기존freeze_boundary 요구가 실제PASS일때만 생성한다.

재현명령: `python -m backend.research.rebuild.step7_candidate_contract_v1 --selection research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/SELECTION.json --output research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/CONTRACT/APPLICATION.json --verify`와 `python -m backend.research.rebuild.step7_campaign_v1 --verify`. 이 명령은 이미 완료된 경제실험을 돌리지 않는다. 완료 후 명령을 반복하지 않는다.

외부AI 실제0, 공유기존사용/예약0/0과USD5·Gemini1/OpenAI1 한도를승계했다. G6/실주문/실계좌sizing/승격권한없음. 세션완료와 경제목표완료는 별도다. 경제미달/미래거래대기를 이유로 세션을 연장하지 않는다. Q0/G5B/기존수집/다른Work는 보존한다.


**확정 실행 결과와 종료.** PR #1209 병합 SHA d37dbfa30cd7624d2db8980bac2df7e5afa7ad14, PR CI run34154128727(신규39시험 PASS 및 관련8워크플로success), 고정merge master run34154220234 completed/success. Source job101842608877도 완료했다. 원천22GET/22저장,7종목 각각 완료4h239봉·depth5레벨 snapshot·funding3행과 공통contracts1179행을 확보했다.22receipt의 online/offline parse 동일, 수신구간 내 duplicate0/검출gap0이다. 이는 과거 전체구간 무결성이나 전략 시그널/체결 parity PASS가 아니다.

원본 artifact step7-source-34154220234, id10030394321,270475bytes, digest sha256:c1a9046d5fa3df93cf397746988d44d2b49ee6915409fea8b023baca2a9bc665, 만료2026-12-06T19:05:20Z. 개발자는 raw가격/신규성과를 열지 않고 sanitized메타만 연결했다. 마지막 실제 원천수신2026-09-07T19:05:52.003Z, source job 마지막로그2026-09-07T19:05:53.7275107Z. 상시수집 시작/과거BBO복원/실제체결/독립OOS 수행으로 보고하지 않는다.

현재239완료봉 snapshot은 exact native seed·실제 의사결정·진입청산 당시 BBO/비용 증거를 완성하지 못한다. 따라서 W3 잔여source연결, W4 승인/전체producer/독립평가는 BLOCKED다. 이 작업의 원천1/1은 소비됐으며 재시도/새이름으로 예산초기화하지 않는다. independent0/1, 후보44보존·신규0, Gemini0/OpenAI0, 유료사용/예약$0/$0을 기록했다.

세션은 CHECKPOINTED / REPORT_ONLY로 닫는다. 경제목표완료=false, G5A미충족, G5B새boundary0/freshT0/terminalPASS0. 불필요한 작업 소유 실행/대기 없음. S1~S4 산출물은 반영·종료됐으며 Q0/G5B/기존수집/다른Work는 건드리지 않았다. 미완료 작업별 담당·입력·잔여예산·조건부 다음명령과 아직 없는 실제경제실행 명령의 이유는 HANDOFF.json에 보존했다. 승인만으로 미완성 native/control/neighbor producer가 완성됐다고 취급하지 않는다.
