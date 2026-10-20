# PR #1347 이후 SR 체크포인트 복구 증거

이 디렉터리는 기존 SR 두 identity 배치의 복구 기록이다. 새 후보나 추가 FULL 승인이 아니다. 기존 owner, 승인, 원장, STARTED 이벤트, 중단 증거를 보존한다.

## 회수한 기준

- PR #1347 head: `8c9dbf5768ffdeaf45555b050be2bb44095f7aad` (현재 draft/open).
- 조회한 master: `1a3af5081b4319f3fcfca9a6bda49b98066365e4`.
- 기존 고정 실행 코드 11개와 두 SR freeze 파일은 로컬 원본에서 해시 일치. master의 후속 수정에는 해당 frozen Python 파일과 measurement campaign 변경이 없다.
- PR 원래 CI: run `36996778044`, 원래 28개 합성시험 PASS. 새 실행기 연결/시험의 CI 통과 증거로 사용하지 않는다.
- 전체 승계 문서 SHA-256: `dd74f71f450979b090f4c1e536222c0c54271d5621ae319f3c2378d1efca82b9`.

## 승인 및 예산

`CONTINUATION_PERMIT.json`은 이번 사용자의 명시적 복구 지시를 기록한 외부 허가다. frozen 전략 계약의 `new_full_authorized=0` 필드는 변경하지 않는다. 허가의 canonical JSON SHA-256은 `d0ba67ca56c89a67027300534e364d10cbf49b83ff7ff983ac78a0ac8cb1ac52`이다.

`RECOVERY_PINS.json`의 원장 핀은 기존 read-only Actions run `36994022990`, job `110796496337`의 2026-10-02 10:10:58.751610 UTC 관측에서 독립 회수했다. 최신 서버 DB를 읽은 뒤 새 핀을 계산해 통과시키지 않는다. 원본 승인은 파일 bytes SHA-256 `fc361441c437070bd73812f52cae0d4b298d92627e305dec651aa8a6cf4c0967`로 검증하며 body 재직렬화로 원본 파일을 대체하지 않는다.

해당 과거 관측은 CONTROL RUNNING, RETEST RESERVED, CONTROL STARTED 1개, COMPLETED 0개였다. 현재 상태를 의미하지 않는다. 현재 서버를 대조하기 전 실행하지 않는다.

CONTROL 첫 구간은 기존 artifact `11220809030`에서 정상 다운로드로 회수했다. 56,323,124 bytes, SHA-256 `c1bf466c0afbc44119c6b95f3892cba926a492a4f196aeb99bdb38d4fe371f79`. 이 구간을 다시 계산하지 않는다. 미완료 두 번째 CONTROL 구간은 기존 STARTED를 보존하고 RECOVERY_STARTED를 추가하여 처리한다. RETEST는 CONTROL의 실제 최종 파일과 COMPLETED receipt가 유효할 때 원래 admission gateway에서 한 번만 시작한다.

## 접근 차단과 정식 조치

현재 Remote Desktop Commander의 `vultr` 장치 (`18e0412c-ac50-4e46-99ed-5c78a36cbd94`)는 Offline이다. 지정 장치의 기존 worker.log 읽기 요청도 `INVALID_ARGUMENT: No Desktop Commander device is currently online`으로 실패했다. 따라서 최신 프로세스, flock 소유자, 원장, 결과 파일은 아직 확인하지 못했다.

GitHub와 Remote Desktop Commander 앱의 권한 설정은 이미 Allow all actions로 조회됐으며 변경하지 않았다. 이 설정은 이전 자동 승인 검토 거부를 해제하는 증거가 아니다. 이전 SSH 수집 workflow 등록과 pinned adapter 업로드의 거부 기록은 승계하지만 정확한 원래 거부 사유/대상 SHA는 회수되지 않았다. 다른 도구, 경로, 인코딩으로 같은 작업을 재시도하지 않았다.

필요한 정식 조치는 기존 Vultr 장치의 정상 연결을 관리 경로(`https://mcp.desktopcommander.app/`)에서 회복해 Online 상태를 제공하는 것이다. 이번 Work는 서비스 시작/재시작/설정 변경을 실행하지 않는다. 그 후 최신 원장·예약·잠금·프로세스·결과를 먼저 읽어 기존 실행을 승계해야 한다. 실제 실행기 전송은 정확한 파일 SHA/대상을 명시한 원래 도구의 정식 승인 검토를 통과해야 한다. 기존 배치 예산 승인을 다시 요구하지 않는다.

## 경제 해석과 남은 범위

저장 결과만 독립 검산한다. 비용 2배는 동일 체결/수량의 비용 재계산이며 추가 FULL이 아니다. 각 구간은 별도 계좌다. 펀딩은 UNKNOWN_NOT_ZERO(제외 연구 손익), DD는 LAST-price 표본 기준이다. 미완결 구간의 전체 WR/PF/DD와 승리 훼손을 확정하지 않고 확정 체결 집합 진단과 구분한다. 구간을 연결한 12개월 계좌 수익/DD는 만들지 않는다.

원래25개와 미완료19개는 그대로 유지한다: alpha_combo, anchor_vwap_trend, bb_revert, break_and_continue, ema_ribbon_scalp, fvg_revert, grid_rebalance, keltner_trend, mfi_rsi_div, obv_trend, pivot_reversal, rbreaker_like, rsi_swing_fail, scalp_snap, squeeze_break, trend_ma_macd, turtle_trend, vol_spike_fade, vwap_revert.

이 복구는 기존 두 identity 배치만 대상으로 하며 G4 전체 완료, 수익성 PASS, 공식 승격을 뜻하지 않는다. 새 후보, 전략 재튜닝, 기존5개 재실행, 추가 FULL, 유료 지출, 서비스 변경, 배포, 실주문, LIVE는 실행하지 않는다.

## 회수 코드와 추가 수선

기존 artifact11220809030에서 SR 산술 검산기·저장 결과 검수기·19-case 시험 원문을 회수했다. 기존 Exact25 helper는 정식 repo 원본과 byte-identical이다. 산술 검산기는 동결 producer SHA/child closure/AST literal로 고정 수량 정책5필드를 확인하고, 양쪽 모든 admitted opportunity 중복을 보존하도록 수선했다. 원래19개+신규15개 assertions는 표준라이브러리 직접 실행으로34/34 통과했다. 이는 pytest 실행 결과와 구분한다.

최종 강화 검산기로 기존 첫 CONTROL 체크포인트의403,016개 검사를 다시 수행했고 오류0이며 경제 수치는 불변이다. 실제 데이터 loader/strategy replay/FULL은0이다. 새 core에는 publication 후 원장-only reconciliation API와34개 경계 시험을 추가해 원28개와 함께62개가 통과했다. 실제 runtime caller 통합시험과 독립 리뷰 결과는 LOCAL_VALIDATION.json에 별도 기록한다.

회수한 첫 CONTROL 체크포인트를 `results/SR_CONTROL.common_contiguous_1.checkpoint.json.gz`에 원본 bytes 그대로 압축 보존했다. gzip SHA-256 `608ad1b9037d2f80529e3f9aafa9f8c016564192b988c3a69a5ac478be234e86`; 압축 해제56,323,124 bytes SHA-256은 원래 `c1bf466c…71f79`과 동일하다. 이것은 첫 구간 체크포인트 보존이며 outer 최종 결과/전체 배치 완료를 뜻하지 않는다.

최종 caller 시험39개와 core62개를 합친101개 unittest가 통과했다. 독립 검토에서 잠금 inode 교체 및 RETEST 완료 event payload 불일치 두 문제를 재현·수선했고 미해결 사항0이다. 고정 수량/ambiguity 시험34개는 로컬 표준라이브러리 assertions 통과이며, 정식 pytest CI는 source PR에서 별도 확인한다. 실제 서버 연결/재개/배치 완료는 아직 미확인이다.
