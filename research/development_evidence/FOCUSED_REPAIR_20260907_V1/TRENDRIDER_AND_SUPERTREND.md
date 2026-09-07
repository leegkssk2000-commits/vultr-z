# TrendRider 연결 검산 1묶음 / Supertrend 저장 손실 분해

## 역사와 현재의 최초 의미 차이

| 항목 | 역사 Primary16 | 역사 Broad30 | 현재 native Primary / Broad |
|---|---:|---:|---|
| 승/완결 | 13/16 (81.25%) | 21/30 (70%) | 97/412 (23.54%) / 102/457 (22.32%) |
| 저장 순손익 trade-bps | +23297.76943728 | +34960.57723837 | −11678.35957741 / -14081.64292892 |
| 저장 전체 비용 | 246.56 | 450.69 | 최소20bps/포지션과 보유 펀딩 |
| 역사 entry→last exit | 2026-08-17T02→08-23T04 UTC | 2026-08-16T20→08-21T11 UTC | 기사용 DEV 2024-12-19T08→2025-12-29T08 UTC |
| 방향 | long16 | long28 / short2 | closed long363/short49 · long398/short59 |
| 청산 | TIMEOUT13 / SL3 | TIMEOUT21 / SL9 | P SL307/343 및 기존 timeout |
| 동일 종목 기존 보유 중 추가된 행 | 13/16 | 25/30 | 종목별 실제 점유1 + cooldown |
| 최대 동일 종목 중첩 | 8 | 12 | 1 |
| 저장행에만 현재 점유를 적용 | 5건/4승/+4732.60695722 | 6건/4승/+4812.37323226 | 전체 시장 재생과 구분 |
| 저장순서 DD→exit순서 DD | 219.06777383→동일 | 413.79296961→523.97074280 | 현재 DD는 달력 미완결 평가 포함 |

Primary의 첫 모집단 차이는 선택 단계다. 역사16은 transition parent 완료25 중 첫24에서 선택된 집합이며 현재는 후속 chase child를 전체 DEV 달력에 적용한다. 실제 체결 의미의 첫 입증 차이는 과거 evaluator가 동일 종목 점유·cooldown을 적용하지 않은 것이다. 당시 evaluator는 intent 중복만 차단하고 모든 적격 신호를 독립 SL/TIMEOUT 경로로 계산했다. 현재 evaluator에는 no-pyramiding/blocked_until/cooldown/open reservation이 있다. 이는 이미 수선된 구현 차이이며 이번에 다시 수정하지 않는다.

최초 중첩: Primary ETH entry1786953600000는1786932000000 거래 보유 중 진입. Broad BTC entry1786935600000도1786932000000 거래 보유 중 진입. Primary/Broad 역사 중15개가 동일 경제 경로이며 그 net +23516.83721111을 두 번 독립 증거로 세지 않는다.

역사 원래 행의 gross/net/cost는 직접 재합산 일치, duplicate intent0, gross 산술 최대오차 약1.14e-12. Broad stored-row subset 계산 중 cooldown 등호를 원본과 대조하여 entry_ts<=blocked_until 차단으로 정정했다. 최초 임시 +4818.68576394는 폐기하고 +4812.37323226을 사용한다. 이것은 저장행 부분집합 계산이며 새 후보/전체 실행 가능한 수정 baseline이 아니다. 제외됐던 원래 signal tape가 없으므로 실현 가능한 거래집합·원래 승률을 복원했다고 주장하지 않는다.

## 코드·원천 연결과 미확인

- 역사 확인 run32640190665, head cd4cc066273b1d4a83821e711a5da52c508f0f76.
- 당시 a1_exact25_generic_evaluator_v1.py Git blob21bfc8423d2bd3b4d3f2b529a1cead884ae07d40: 실제 점유 gate 없음.
- 현재 같은 파일 Git blob5da6ed21eab6d5482602bc1b856537f74f268a15: ownership_blocked 및 실제 예약 코드 포함.
- 원문: https://github.com/leegkssk2000-commits/vultr-z/blob/cd4cc066273b1d4a83821e711a5da52c508f0f76/backend/research/rebuild/a1_exact25_generic_evaluator_v1.py
- 역사 Primary16: backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json, SHA256 f0b992200c73e8a4fa6fcf8f4c5e60aabc8f5bbbe0807aea7ee88ddc45435848.
- 역사 Broad30: backend/research/rebuild/a1_trend_rider_broad_wr7000_upstream_source_receipt_v1.json. SHA와 exact 재합산은 TRENDRIDER_STORED_ROWS.json에 있다.
- native 정책·시세·비용 SHA 및 source path는 보호된 TOP5_MECHANISM_B_20260907_V1/SPEC.json 그대로다.
- 역사 evidence_sha6e03a200...는 commit이 아니라 evidence_packet JSON git blob이다. 역사 receipt는 exact evaluator SHA를 직접 결속하지 않아 run head 원문과 연결했다.
- artifact9493430326은2163bytes attribution summary이며 workflow upload도 summary JSON 하나다. 다운로드 참조 발급 후 HTTP403으로 바이트 해독 불가. 정확한 당시 raw OHLC·warmup·전체 탈락 signal tape·funding settlement rows를 확보하지 못했다.
- 역사 기본비용13bps(10fee+1spread+2impact) 위 잔여합은 Primary38.56/Broad60.69. 해당 당시 funding settlement rows가 없어 signed funding 재현은 불가.

따라서 같은 입력 전체 재현0, 정정 baseline 시장 재현0, 역사→현재의 기간/선별/점유/비용 상호작용 잔여는 UNRESOLVED. 현재 부모부터 낮은 승률이므로 TPR1/TBR1 timeout 연장 탓으로 격차를 귀속하지 않는다. 현재 입증된 새 코드 결함 수정0. 역사 수치 자체를 소급 무효/현재 formal Survivor로 바꾸지 않는다.

## 기존 native SL 경로의 구조

| 손절 전 관측 분류 | Primary | Broad |
|---|---:|---:|
| SL 전체 | 307 / −45241.70658783 | 343 / −51074.15430555 |
| 진입 봉 SL, 장중순서 미확인 | 17 | 22 |
| 이전 완료봉은 있지만 유리한 진행 관측 없음 | 1 | 1 |
| 유리한 H/L만 있고 양수 완료종가 없음 | 68 | 89 |
| 손절 전 양수 완료종가 관측 | 221 | 231 |
| 손절 전 ≥20bps 완료종가 관측 | 175 | 186 |
| 이전 완료봉이 있는 거래 중 첫 보유봉 종가 역행 | 154/290 | 182/321 |
| SL전 완료봉수 중앙값 | 8 | 7 |
| 실제 entry→SL risk 중앙값 bps | 116.82687166 | 116.82687166 |

risk 중앙값은 각 lane의 저장 SL·entry 가격으로 계산했다. SL 잘못된 방향0. 공통 SL229건 net−34480.09793798, Primary 고유78건−10761.60864985, Broad 고유114건−16594.05636757. 합집합421건으로 한 번 집계한다.

검산은 각 저장 SL 경로의 entry_index:exit_index 이전 완료봉과 SL 봉 open만 사용했다. SL 봉 HLC·이후 봉은 관측에 넣지 않았다. 원래 저장 mfe/mae는 SL 봉 전체 HLC가 포함된다는 한계가 있어 이를 손절 전 MFE로 재해석하지 않았다. 관측 이익은 지정 시점·체결 명세 없이 회수 가능 수익이 아니다.

초기 역행과 이익 반납이 모두 있다. trailing flag 미구현만으로 전체 적자를 설명할 수 없고 SL 확대/새 진입 필터의 근거도 확정되지 않았다. 다음 판단은 역사 격차 귀속에 대해서는 원천 부재로 미확정, 현재 매매 관리에 대해서는 단일 trailing 상태/trigger/갱신/체결 계약을 먼저 정의해야 하는 상태다. 이 계약 정의와 정책 실측은 별도 승인 대상이며 이번 TR2/퓨전/신규 실측0. 기존 역사 관측기·운영본은 보존한다.

## Supertrend: 원형 손실과 SR1 부작용

| 저장 분해 | 2025 | 기사용2026 |
|---|---:|---:|
| P→FIXED 순증분 | −414.54927662 | +3985.64252476 |
| gross 변화 | −14.92493277 | +4163.79144942 |
| 추가 비용 | 399.62434385 | 178.14892466 |
| FULL 점유 잔여 | −112.26333136 | +759.84757778 |
| FULL 총증분 | −526.81260798 | +4745.49010254 |
| 원형 손실 | 137건/−59304.38557636 | 45건/−16091.51233097 |
| 비연장으로 완전히 그대로인 원형 손실 | 124건/−58110.92450558 | 40건/−15454.69515936 |
| 연장 일반승리 도움/피해 | 28건/+12189.80263057 ·56건/−13176.66849862 |10건/+6631.61721659 ·20건/−4156.17740740 |
| 연장 큰승리 도움/피해 |7건/+4236.52251671 ·4건/−2430.69662245 |3건/+1166.10629213 ·1건/−66.34072649 |
| FIXED 승리→손실 |21 |6 |

원형 손실은 원래 H12 진입 후 보유구간의 손실이므로 진입만의 인과 문제로 단정하지 않는다. SR1 2026 이득과2025 피해를 함께 보존한다. 기존 연장조건 안에 도움/피해가 섞여 다음 보유수선의 실행 가능한 판별축은 미확정이다. 후속 우선순위는 원형 진입 및 기존 H12 보유구간 손실 구조의 진단이며 새 보유 조건이나 진입 재설계 규칙을 이번에 확정·실측하지 않았다. Supertrend 신규시장실측0, Q0 자격심사/ablation0.
