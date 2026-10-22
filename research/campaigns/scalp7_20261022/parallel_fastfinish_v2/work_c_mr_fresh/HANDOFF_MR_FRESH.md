# A / B handoff: frozen MR30m preparation only

새 default-OFF adapter 하나가 기존 native MR child callback을 호출한다. **Code preparation만 완료 대상이며, 실제 미래검증은 `NO_MR_FRESH_READY`**다. 실제 MR용 6개 symbol의 현재 source/cursor/clock receipt와 pair 예약을 이번 Work에서 전달받거나 인증하지 않았다. 기존 MR producer는 이미 등록되어 있고 `HOLD_FRESH_SOURCE_OR_IDENTITY` 상태였다. 새 producer나 collector를 시작하지 않는다.

## Identity / immutable source

- Branch: `work/zel-candidate-adapters-20261021`; 이전 C `8afdaf552e24041fdc681d6d99817d43a75c20c9`의 직접 후속 add-only commit. 정확한 게시 commit은 이 파일을 포함하는 commit이며 최종 remote readback에서 별도 보고한다.
- Native identity: `mr_reexpansion_bar4_30m_causal_control_v2`.
- Native source: `backend/research/rebuild/scalp7_mr_formation_v2.py`.
- Native SHA256: `1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5`.
- Native Git blob: `0f76134ace2701dcad17ac6d8427c0e84b9e1feb`.
- Source context: `d84623cdc7cf8a87022ab7448ae2624215321177`; 최신 master `1a5840fe32cc18ff91dea225f9713a63235a1f9a`에서도 source 15개 SHA 불변 확인.
- Economic owner: `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`; owner ref `910f998b1d60ddec30a76366ba49253a4afaa8dd` 보존.

`SOURCE_CONTRACT.json`과 `SOURCE_TO_RULE.md`에 전체 규칙·원문 SHA·입력 계약을 기록했다. Native pair 형성과 exit callback을 그대로 재사용한다. 61T legacy same-close exit와 선택한 native next-open exit request는 다른 실행 계약이다. Old 61T PnL parity를 주장하지 않는다.

## First reproducible commands

아래 명령은 해당 commit의 repository root에서 실행한다. Python과 기존 NumPy/Pandas 환경을 사용하며, network·시장 데이터·경제 replay를 호출하지 않는다. `synthetic_entry_snapshot.json`은 시험 코드가 만든 인공 가격·인공 receipt·인공 예약이다.

```bash
python -m unittest discover -s research/campaigns/scalp7_20261022/parallel_fastfinish_v2/work_c_mr_fresh -p test_mr_fresh_adapter.py -v

python research/campaigns/scalp7_20261022/parallel_fastfinish_v2/work_c_mr_fresh/mr_fresh_adapter.py

python research/campaigns/scalp7_20261022/parallel_fastfinish_v2/work_c_mr_fresh/mr_fresh_adapter.py --enable-preparation --snapshot research/campaigns/scalp7_20261022/parallel_fastfinish_v2/work_c_mr_fresh/synthetic_entry_snapshot.json
```

첫 CLI는 `DISABLED`; synthetic CLI는 source-code signal observation 하나만 낸다. 모든 output은 `executable=false`, `real_sources_verified=false`, `fresh_T=0`, `fills=[]`, `PnL=null`이다. `--enable-preparation`은 JSON 계산 허용이며 collector/관측 서비스/Paper/Live 활성화가 아니다. 실제 입력을 연결하는 실행 명령은 이번 인계에서 승인하지 않는다.

## Entry / exit as-of

| 항목 | 계약 |
|---|---|
| Entry 입력 | 고정 순서 BTC/ETH/SOL/XRP/LINK/DOGE USDT의 최소 21개 연속 완료 UTC 30m 봉. 모든 OHLC·availability·source receipt가 caller as-of 이하 |
| Pair | 현재/직전 6h leader·laggard 동일, spread≥0.03이며 contraction. laggard long 0.5 / leader short 0.5 |
| Entry reference | signal bar open + 1,800,000ms. 실제 decision/availability가 이미 지났으면 `LATE_MODEL_ENTRY_NO_RETROACTIVE_FILL` HOLD. Reference는 fill이 아님 |
| Exit 입력 | 원 진입 snapshot 및 hash, exact native signal, 원 pair와 spread, 원 예약, 연속 held-bar 시각, 현재 as-of·source proof |
| Exit rule | bar4부터 원 pair의 6h spread≥signal spread면 재확대 exit request; 그렇지 않으면 bar8 만료. bar8 동시 조건은 native 재확대 reason 우선 |
| Exit reference | 완료봉 close의 다음 공통 open 모델 reference. 늦거나 이미 지난 lifecycle 결정은 HOLD/unresolved; guessed fill·예약 해제 없음 |
| Stop / volume | native stop 없음. 임의 stop-first overlay 거부; gap은 unresolved. Volume은 native feature가 아니므로 UNKNOWN을 임의 단위로 바꾸지 않음 |
| Cost / capital | 6개 양수 finite 비용은 caller-supplied reference scenario만. 외부 계정 전체 자금 점유 및 exact pair 예약 필요; 미예약은 pending, 외부 예약 writer 없음 |
| Duplicate | 기존 fresh_forward canonical opportunity key 및 caller의 `seen_opportunity_keys` 사용. 기존 MR 등록/STATE/writer 변경 없음 |

Receipt self-hash는 전달된 bytes를 결속할 뿐 외부 거래소 원천을 인증하지 않는다. 현재 runtime의 최초 미충족 입력은 실제 MR 관측 source/cursor/as-of 증거이며 synthetic receipt로 대체할 수 없다. 외부 비용 사실·양쪽 leg 실행·계정 권한 역시 이 adapter가 부여하지 않는다.

## Evidence classification and owner boundary

`SYNTHETIC_RECEIPT.json`은 이번 유한 시험 결과다. 새로운 실제 T·Gross/Net/PF/WR/MaxLS/DD/큰 승리 보존/OOS 측정은 없으며, 모두 미실행이다. 저장된 이전 결과는 다음처럼 구분한다.

| 저장 결과 | T | Gross / Cost 1x / Net 1x (trade-bps) | Net 2x | 분류 |
|---|---:|---|---:|---|
| Legacy child | 61 | 원문에 gross/cost 분리 없음 / Net +386.379717 | 원문 미기재 | Old DEV; used hold 35T +145.526444 |
| 기존 causal child | 82 | 1226.901144 / 1216.828577 / +10.072568 | −1206.756009 | 기존 rolling diagnostic; fresh T=0 |

Later child 1x/2x PF=1.003888/0.627628, WR=48.7805%/43.9024%, MaxLS=6/6, DD=634.455006/1245.673322 **realized equal-notional trade-bps**다. 계좌 NAV 또는 open MTM DD가 아니다. 동일 parent 대비 child 1x Net/WR는 약해졌으며 2x 음수다. 경제 PASS나 수익 전략 확정 근거가 없다. 원문 bytes와 ledger SHA는 contract/inputs에 보존했다.

A는 기존 유일 owner 및 global-heavy≤1 아래 별도 허용 범위를 결정한다. B에는 입력 계약과 비활성 코드만 인계하며 PID374902의 4버전 writer/STATE 및 기존 older MR producer를 변경하지 않는다. 이 Work의 FULL·Actions dispatch·market API·새 collector·Paper/Live·실주문·owner/master/워크플로/원장 변경은 모두 0이다.

변경은 이 신규 디렉터리에만 추가된다. 비활성 기본값을 유지하면 기존 실행 경로에 영향이 없다. 되돌릴 때도 공유 브랜치를 force하거나 원본을 삭제하지 않고 이 add-only commit만 별도 revert 대상으로 검토한다. GitHub Actions deploy는 실행하지 않는다.
