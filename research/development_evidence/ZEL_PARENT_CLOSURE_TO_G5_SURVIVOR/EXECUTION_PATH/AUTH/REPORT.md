# STEP7 P1 승인 인증 수선

기존 PR1209 `preregister`는 승인 객체와 동일 호출자가 제공한 해시를 비교했다. 실제 STEP7 caller/workflow에서도 별도 인증 owner는 확인되지 않았다. P1 review `3952135407`의 문제는 **무결성 검사와 사용자 인증을 혼동한 것**이다.

이번 수선은 새 `step7_authorized_io_v1.dispatch(request, producer)`를 production 봉인 읽기·실행 진입점으로 둔다. 기존 동결 모듈은 변경하지 않으며 순수 정책 검사로만 내부 재사용한다.

## 실제 인증 경계

- 호출 인수나 환경변수로 trust path/key/principal/fixture mode를 받지 않는다.
- 고정 `/etc/zel/step7/authority-trust.json`을 외부 관리자가 독립 배포해야 한다. 파일·부모 모두 root 소유, group/world 쓰기 금지, symlink 금지다. 소스 파일도 같은 읽기 전용 조건이다.
- 실행 UID는 root가 아니어야 하며 외부 trust store의 validator UID와 일치하고 개발자 UID 목록에서 제외돼야 한다. 검증 주체도 signed roles와 일치해야 한다.
- 실제 승인권자 public key로 Ed25519 서명을 검증한다. principal 문자열만으로 인증하지 않는다. key/approval 철회, 유효기간, 정확한 scope/candidate/code/config/design/source/cost/data/window/조회예산 결속을 검사한다.
- 정확한 producer 모듈 바이트 해시와 함수 식별자도 서명 범위다. 전체 후보 dependency 검증은 해당 생산기의 동결 코드 검증과 함께 적용해야 한다.
- 검증된 외부 서명에서만 기존 정책 함수용 authority를 구성한다. 이 내부 authority의 해시는 사용자 인증 근거가 아니다.

## 실제 I/O 순서

`외부 trust/UID → Ed25519 승인 → 정확한 결속 → 기존 정책/독립성/검토시각 검사 → O_EXCL 영속 예약 → fsync(file, directory) → 봉인 파일 바이트/hash → 고정 producer → 결과 receipt`.

예약 파일은 campaign 고정 키다. request 파일명·approval ID·입력 경로를 바꿔도 다시 사용하지 못한다. 예약 이후 취소/불명/해시 불일치/producer 오류도 소모 상태를 남긴다. 모듈은 예약을 삭제하거나 초기화하지 않는다. 초기 캠페인 snapshot과 예약 이후 캠페인 상태를 같이 보존한다.

호스트 관리자와 배포 코드는 신뢰 대상이다. 임의 host root 공격까지 Python 코드로 막았다고 주장하지 않는다. 실제 별도 validator 계정·읽기 전용 source·예약 보존 운영주체가 필요하며, 개발자가 영속 원장을 지울 수 있는 환경을 정식 실행환경으로 인정하면 안 된다.

## 실제 실행 결과

```text
python -m unittest backend.research.rebuild.test_step7_authorized_io_v1 -v
Ran 13 tests — OK

python -m backend.research.rebuild.step7_authorized_io_v1 --preflight
BLOCKED_TRUST_ANCHOR_MISSING
sealed_reads=0 / dispatches=0 / independent_allocations_consumed=0
```

새 시험은 정상 fixture 서명, 위조 객체+자기 해시, 위조 signature, 다른 승인권자, candidate/design/scope/code/cost/budget 불일치, 만료·철회, 조회권 재사용, 취소 후 재실행, 데이터 hash 실패, fixture의 production 주입, caller trust/fixture switch, 실제 anchor 부재를 포함한다. 정상 fixture만 합성 바이트 한 묶음을 읽고 생산기를 호출했다. fixture 권한의 production 진입은 실제 읽기 전에 거절했다. PR1209 완료 시험과 경제 replay는 반복하지 않았다.

현재 실제 승인 anchor는 **없다**. 이번 구현 승인을 11항목 공식 승인으로 바꾸거나 개발자가 fixture 키를 실제 trust store에 설치하지 않았다. 실제 formal I/O는 계속 차단된다. 이 상태는 코드 P1 수선 결과와 분리한다.

의존성은 Python 표준 라이브러리와 Ubuntu의 기존 `openssl pkeyutl`뿐이다. 외부 API·새 pip 설치·유료 호출은 없다.

## 후속 실제 실행 전제

1. 사용자 정식 결정문을 독립 승인채널에서 identity 검증 후 서명한다.
2. 별도 관리자/validator 실행환경에 public trust state·source root·현재 누적 budget snapshot·private 영속 journal을 고정 배포한다. 개발자나 payload가 이 경로를 정하지 않는다.
3. S2 production CLI가 이 dispatch를 호출한다. unsigned metadata 사전검사는 가능하지만 봉인 원시자료는 dispatch 승인 전 읽지 않는다.
4. 정해진 검토시각에 단일 정식 bundle만 예약·실행한다. G5A/G5B PASS는 생산 결과를 통해 별도로 판단한다.
