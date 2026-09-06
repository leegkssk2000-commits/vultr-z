# Frozen M1 design, one candidate after M

M remains the partial development workcopy. P/D/N/M rules and verdicts stay immutable.

This document adopts the attached execution instruction below verbatim as the precise research design. Numerical economic and uncertainty criteria are inherited from parallel_exit_metrics_v1.GOAL; no new tolerance, risk threshold or optimization grid is introduced. Report 2025 preserved net amounts and fractions plus terminal base/cost2 positivity, and separately 2026 closed/terminal base/cost2 deficit reduction. Report risk and winner-preservation tradeoffs without automatic workcopy replacement. Use the original two calendars and seven symbols; no future source or observer prices.

Implementation: one thin synchronous scoped path overlay, one study runner, one synthetic test file. The immutable M causal clock runs unchanged and alone selects admissions. A full replay is checked against a separate fixed-all-M-entry comparison. Actual M1 fills never release reference opportunities; all virtual economics are zero. Existing D geometry and funding/cost/20bps floor accounting and existing UTC-day uncertainty are reused.

Counterevidence: PR1186 Supertrend signal-low exit fixed-entry delta -4809.587903 trade-bps, cut winner profit11973.979751 and17 winner-to-loss conversions; DEV_REJECT. This is the same primitive on a different M reclaim/D-exit/N-selection/causal-reservation parent, not independent proof of benefit. The old Supertrend full replay admitted replacements; M1 must admit none.

The previous M workflow remains sealed. Its missing direct-dependency triggers (P2) are covered by the existing external-evidence workflow's narrow M1 companion routing. Unrelated legacy economic replay is not invoked for M1 changes. New trial31 is consumed before any M1 economic counterfactual; partial attempts count. Reproductions retain the same attempt and are logged by PID/UTC/run ID/duration/hash, not charged as new candidates. One writer, at most one reviewer,45-minute Work checkpoint cap,15-minute stalled-progress diagnosis once; finish immediately after required evidence is verified. No new scheduler, paid AI, production deployment or authority changes.

## User execution instruction

[CONTINUE — PR #1198 M 보존 / 잔여 손실 수선 1회 / 완료 후 즉시 종료]

0. 목적과 권한
이 파일을 사용자가 같은 Work에 전송하면 아래 범위의 연구용 후속 후보 최대 1개를 별도로 승인한다.
목표: M의 2025 개선을 보존하면서 2026 비용 후·미완결 포함 손실을 줄일 수 있는지 실제 계산한다.
M은 PARTIAL_DEVELOPMENT_WORKCOPY_RETAINED이며 운영 또는 공식 PASS 기준본이 아니다.
수익 개선을 보장하지 않는다. 목표를 못 넘으면 결과와 M을 보존한다.
원격 변경 승인은 이 연구의 최소 코드·테스트·사전등록·결과에 대한 push→필수 CI→PR→병합→master 검증까지다.
실거래·실계좌 sizing·운영 교체·formal credit·유료 외부 AI·새 스케줄러는 승인하지 않는다.

1. 시작점 — 재실행하지 말고 가장 먼 실제 진행 지점에서 이어간다
Repo: leegkssk2000-commits/vultr-z
PR1198 merge: 580b382e09ccc443632d68e1f7079711c82f22fc
M evidence: research/development_evidence/KELTNER_OPPORTUNITY_RESERVATION_20260906_V1/
M result seal: b86757d2271190ffa85d78f01879b3fce57365b6ce03b46f78aff73e011199fe
M durable SHA256: 677605ef91ca7f5b0930c207d4953d5f88cefcabb12ac8e828a233db02e347e8
M source: backend/research/rebuild/keltner_opportunity_reservation_adapter_v1.py
D source: backend/research/rebuild/parallel_exit_keltner_v1.py
N source: backend/research/rebuild/keltner_cumulative_entry_adapter_v1.py

current branch/HEAD/미커밋 변경/origin/master/동일 목적 PR만 확인한다.
기존 로컬 작업이 있으면 보존·재사용한다. reset --hard/clean/강제 덮어쓰기 금지.
M 결과가 이미 완료됐으면 M 개발·경제시험·봉인 전수감사를 반복하지 않는다.
현재 명시적 읽기 범위는 위 M의 REVIEW/RESULTS/SPEC/receipt/두 기간 원장과 필요한 직접 의존 코드다.
Q0 미래 가격·경제 원장·관측 결과는 읽지 않는다. 운영 상태가 변경되지 않았는지 내용 해시 검증만 허용한다.

2. 이번 수선의 근거와 한계
M REVIEW의 2026 잔여 분해:
- unchanged exit, loss: 34건, gross -8756.64, cost 743.39, net -9500.03 trade-bps.
- 이 중 33건은 비용 전부터 손실이며 EMA invalidation 없이 ORIGINAL_TIME_STOP_CLOSE까지 보유했다.
- 미완결 4건 net mark -616.99는 위 34건 및 완결 75건과 별개다.
- 전체 완결 net -397.90, cost2 -1998.21; 가상 terminal net -1014.88, cost2 -2695.19.
이 숫자는 고정 명목금액의 연구용 합계다. 계좌 수익률·회수 가능한 이익·실행 조건으로 쓰지 않는다.

이미 계산된 이 분해를 다시 수행하는 것만으로 이번 작업을 완료하지 않는다.
반드시 같은 분류의 2025 자료와 일반/큰 승리 거래도 함께 다룬다.

알려진 반대 증거: PR1186 Supertrend signal-low exit는 fixed-entry delta -4809.59로 실패했다.
새로운 만능기법으로 재포장하지 않는다. 동일 primitive의 다른 부모(M)에 대한 별도 적용이다.
M의 reclaim 진입/기존 D 청산/N 선별/참조 점유와 당시 Supertrend의 차이를 명시한다.
이 반대 증거는 승리 훼손을 반드시 계산할 이유다. 성공 증거가 아니다.
같은 M parent·규칙·기간으로 이미 측정한 후속 결과가 발견되면 재실행하지 않는다.

3. 후보 M1 — 사전에 정한 단일 가설만
이름은 제안된 연구 ID이며 SSOT enum 또는 이미 존재하는 후보로 취급하지 않는다.
가설: EMA20>EMA50이 남아 있어도 진입 신호봉의 가격 범위를 잃으면,
그 시점의 조기 청산이 이후 timeout 손실을 줄일 수 있다. 승리 절단 손해와 함께 검증한다.

정확한 규칙:
- 실제 모형 진입을 만든 원래 완료 4h 신호봉의 low를 진입 전에 고정해 저장한다.
- 실제 모형 포지션 보유 중, 그 이후 완료 4h 봉의 close < 고정 signal_low가 처음 성립하면 다음 4h open 청산을 예약한다.
- equality는 발동하지 않는다. 봉 중 low 접촉만으로 체결하지 않는다.
- 신호봉 저가 갱신, trailing, ATR 배수, 손실% 기준, 연속봉 수 탐색을 추가하지 않는다.
- 수익 여부와 상관없이 모든 M 진입에 동일 규칙을 적용한다.
- 34건 timeout-loss, 2026, 특정 종목/거래ID는 사후 진단 라벨이다. 실행 시점 조건으로 사용하지 않는다.

새 규칙은 M의 기존 EMA 추세 소멸 청산/최대12봉 timeout에 조기 청산 하나를 추가한다.
기존 규칙을 취소하거나 늦추지 않는다. 초기 진입조건·체결시점·수량·비용 authority는 변경하지 않는다.
기존 모델에 별도 native protective SL이 없다는 사실을 숨기지 않는다.
이 close-confirmed research exit는 거래소에 상주하는 보호손절 주문이 아니다.

4. 가장 중요한 누적 보존 — 실제 청산과 참조 점유를 분리한다
M의 D 기반 인과적 reference clock은 완전히 그대로 유지한다.
M1의 실제 모형 포지션이 먼저 청산돼도 reference opportunity는 D 규칙으로 종료가 관측될 때까지 유지한다.
따라서 조기 청산이 새 대체 진입을 만들지 않아야 한다.
가상 참조에는 비용·funding·PnL·노출·실제 포지션 수를 부여하지 않는다.
실제 청산 이후의 비용·funding·시장노출은 실제 모형 포지션에서 중단한다.
참조 상태는 이후 관측봉으로만 진행한다. 과거 D 거래ID나 미리 계산한 최종 exit_ts를 실행 입력으로 읽지 않는다.

원래 M과 M1의 신호·진입ID·진입시각/가격·참조 예약/해제 이벤트는 일치해야 한다.
완결 수와 미완결 수는 조기 청산으로 달라질 수 있으므로 무조건 같은 closed_T를 강제하지 않는다.
P/D/N/M은 모두 고정 대조군/보존 자료다. 본체를 수정하거나 과거 판정을 덮어쓰지 않는다.

5. 실행시각과 경계
시가에서는 이미 직전 완료봉에서 예약된 청산만 처리한다.
이전 봉에서 예약된 청산은 현재 봉의 고저종가나 그날 뒤의 timeout을 미리 보지 않는다.
동일 시가에 기존 D 청산과 M1이 겹치면 기존 D의 reason/priority를 유지하고 한 번만 체결한다.
해당 봉의 종가에서 기존 timeout이 체결됐다면 그 종가로 M1을 새 예약하지 않는다.
다음 open의 gap도 관측된 open으로 체결한다. 발동 가격 체결·같은 close 체결 금지.
평가 끝의 실제 next open이 없으면 강제 청산하지 않고 pending/open mark를 따로 남긴다.
기존 strict-end timeout·가상 roundtrip 평가비용 convention을 바꾸지 않는다.

6. 데이터·회계
기간/7종목/원천 행/EMA seed/warmup은 M의 SPEC을 그대로 상속한다.
2025: 기존 Keltner [2024-12-19T08Z, 2025-12-29T08Z).
2026: [2026-05-08T00Z, 2026-09-05T00Z).
두 구간 모두 기사용 개발 자료이며 independent=false / formal_credit=0다.
2026-09-05T00Z 이후 가격, Q0 prospective archive/성과, 새로운 validation/OOS는 개발에 쓰지 않는다.

기존 비용 모형과 floor를 그대로 적용하고 바뀐 실제 보유시간으로 경과 funding을 재계산한다.
비용x2는 동일한 행동/체결에 전체 비용을 두 배 적용한다. 비용x2 전용 행동 최적화 금지.
손실절감 금액에 이미 반영된 비용 절감을 다시 더하지 않는다.
고정진입 비교뿐 아니라 전체 M reference clock+실제 포지션 재생으로 동일성을 확인한다.
닫힌 거래만 좋아 보이도록 미완결 손실을 누락하거나 끝에서 강제청산하지 않는다.

7. 계산 전 동결·제한
M1의 새 경제 결과나 payoff 집단을 보기 전에 규칙/부모/데이터/비용/코드/기준을 commit으로 고정한다.
미세 조건 변경이나 trial 외의 '진단용' 대안 경제 스캔을 금지한다.
사전 test는 합성 자료와 비활성화 시 M과의 정확한 회귀검사만 사용한다.

기존 30건은 불변이다. 이번 별도 연구 후보는 최대 1개다.
M1의 새로운 counterfactual 경제효과를 계산하기 시작하면 부분 계산이어도 후보31/attempt로 기록한다.
가격 경로/개입률을 보고 유리한 것만 정식 후보에 세지 않는다.
동일한 봉인 결과의 local/필수 CI/master 재현은 새 후보가 아니지만 실행 횟수/시간은 기록한다.
새 후보 비용 한도는 후보 수를 뜻하며 계정 사용량 0을 뜻하지 않는다.

8. 결과 해석 — M 보존과 최종 수익자격은 별개
이번 집중목표는 2026 비용 후·미완결 포함 결손 감소와 2025 개선 보존이다.
M1-M을 기간별로 따로 비교한다. 두 기간 합산 흑자로 2026 적자를 가리지 않는다.
기존 연구 기준/불확실성/large winner retention 정의는 M/SPEC 및 직접 상속 계약에서 읽는다.
새 SSOT 임계값이나 사후 허용오차를 만들지 않는다.

반드시 분리해 판정:
- 2026 closed/terminal/base/cost2 결손을 얼마나 줄였는가.
- 2025 terminal/base/cost2 흑자와 M 대비 순이익을 얼마나 보존했는가.
- 기간별 marked DD/최대 연패/노출은 개선·동일·악화 중 무엇인가.
- 기존 일반 승리와 큰 승리에서 잃은 금액은 얼마인가.
- 집중목표의 부분 성과와 절대 경제성·증거 충분성은 별개다.

M의 2025 성과를 크게 잘라 2026만 양수로 만드는 경우는 누적 개선으로 자동 채택하지 않는다.
모든 연구 기준을 못 넘더라도 실제 부분 성과가 있으면 수치와 tradeoff를 보존한다.
절대 economic REJECT를 PASS로 바꾸지 않는다. 후속 작업본 교체도 근거 없이 자동 진행하지 않는다.
후보가 불리하면 M1 결과를 남기고 M으로 되돌아간다. M부터 재구현하지 않는다.
중도 무개입 또는 명확한 불리함으로 종료해도 결과/근거/소비한1회는 남긴다.
추가 M2·다른 저가 기준·기간 조정·종목 제거는 이 작업에서 실행하지 않는다.

9. 필수 결과 — 숫자 먼저
P/D/N은 봉인된 참고값을 재사용하고 M/M1 실제 비교를 주표로 낸다.
필수: signal/entry/closed/open 수, 승률, 평균이익/손실, 실현 손익비, PF, net E,
closed/terminal/base/cost2 손익, marked DD, grouped loss, 노출, 회복/종료미회복,
일반 승리/큰 승리 보존, 월별·종목별/진입시점군 기여와 기존 불확실성 한계.

추가 필수:
- M 원장 전체에서 발동한 거래 수, 무발동 수, 각 기간의 발동시점.
- 34 timeout-loss 중 발동한 수/절약손실 및 같은 규칙에 걸린 원래 승리/큰 승리 손해.
- 기존 helpful/harmful early-exit와 신규 개입의 중첩·우선순위, 이중 계산 없음.
- 실제 early exit 후 reference가 계속 유지된 기간과 새로운 진입이 없다는 검증.
- 같은 거래/같은 calendar의 기여; 서로 다른 최대 낙폭의 차이를 원인으로 해석하지 않는다.
- 2026 terminal cost2의 -2695.19에서 실제로 얼마가 남았는지 먼저 표시한다.

10. 구현·검증 최소화
기존 M reference clock/D geometry/비용/회계/불확실성 모듈을 재사용한다.
새 백테스터·데이터 수집기·운영 observer·로드맵·공용 정책 플랫폼은 만들지 않는다.
새 모듈은 필요한 연구용 얇은 overlay와 테스트·한 evidence 디렉터리로 한정한다.
봉인된 M/N/D 모듈은 변경하지 않는다. disabled M1은 M의 원장/이벤트/비용과 정확히 일치해야 한다.
합성 테스트는 trigger prefix/no-lookahead/동률/next-open gap/timeout/이중청산/경계미완결/
reference 유지/가상비용0/재시작·중복/비활성 M parity를 포함한다.
기존 workflow의 본 후보·직접 의존 파일 변경이 필요한 테스트를 빠뜨리지 않는지 좁게 확인한다.
PR1198의 CI path-filter P2는 현재 수정 여부만 확인하고 관련 결함이 남으면 필요한 부분만 고친다.
필수 검사를 줄이거나 skip으로 숨기지 않되, 무관한 legacy 전략 경제 재실행은 하지 않는다.

11. 시간·반복 실행 통제 — 이번 Work 범위의 제한, 시장/SSOT 임계치가 아님
경제 실행 writer는 1개, 별도 검토자는 필요할 때 1개로 제한한다.
여러 에이전트가 같은 전체 경제실험/같은 코드 수정을 중복 수행하지 않는다.
관련 프로세스의 PID/run ID, 시작/마지막 새 로그, 결과 SHA를 남긴다.
동일 입력·코드·결과가 완료됐으면 기존 receipt를 사용하고 경제 실행을 다시 시작하지 않는다.
CI pending은 run ID를 남겨 제한적으로 확인한다. 무한 polling/정체된 대기 턴 반복 금지.
실행이나 검토에서 15분간 실질 새 로그/파일/상태 변화가 없으면 한 번만 진단한다.
진행 근거가 없으면 safe checkpoint를 저장하고 현재 상태 보고로 세션을 종료한다.
한 Work 실행은 45분을 상한으로 체크포인트를 남긴다. 필요한 검증을 생략해 완료라고 하지 않는다.
상한에서 진행 중인 원격 CI는 ID와 상태를 보존해 이후 이어받고 임의 취소·새 run 중복을 피한다.
이 숫자는 과금 보정이나 정상 처리시간의 공식 보장이 아니라 이번 사용자 승인 작업의 실행 예산이다.

경제 결과+필수 검증+원격 receipt가 준비되면 즉시 최종 답변으로 종료한다.
수익이 만족스러울 때까지 자동 재연구하거나, 완료한 검사를 반복하며 세션을 유지하지 않는다.
완료된 PR을 다시 요청받으면 결과만 읽어 보고하고 신규 소진0/재실험0으로 표시한다.

12. 최종 보고
첫 화면: M→M1의 두 기간 경제·위험 표, 2025 보존량, 2026 결손 감소량.
그다음: 발동 범위/줄인 손실/잘린 이익/참조 점유 동일성/개발·독립성 한계.
마지막: 실제 변경파일·CI·PR·merge SHA·receipt·후보누계·경제실행수·소요시간.
새 구현/측정이 없으면 '계획/진단'과 '실제 경제성과'를 명확히 구분한다.
G5B/Q0 미래 관측/운영본/실주문 차단은 변함없다.

근거:
- PR1198 REVIEW.md 및 M 구현, 고정 SHA 580b382e09ccc443632d68e1f7079711c82f22fc.
- PR1186 Supertrend signal-low 실패 기록. 성공 전이 근거가 아님.
- M1 규칙·한정 승인·실행 시간 예산은 이번 후속 연구 제안이며 검증 결과가 아님.
