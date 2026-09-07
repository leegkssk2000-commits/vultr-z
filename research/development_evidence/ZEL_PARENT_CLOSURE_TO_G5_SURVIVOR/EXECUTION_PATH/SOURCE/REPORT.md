# STEP7 후속 원천 연결 구현

기존 snapshot 1/1은 유지한다. 추가 allocation `STEP7_PR1209_EXECUTION_PATH_SOURCE_V1` 하나만 root가 영속 예약하고 고정 merge 첫 push에서 호출한다. 이 담당자는 실제 시세를 읽거나 API를 실행하지 않았다.

실행 명령:

```sh
python -m backend.research.rebuild.step7_source_sequence_v1 --out-dir out/step7-sequence --allocation <root가 저장한 추가 allocation JSON> --run-id STEP7-SEQUENCE-${GITHUB_RUN_ID}-${GITHUB_SHA}
```

원래 7종목의 400개 요청 4시간봉 prefix·펀딩과 깊이 호가 3회차를 총 35 GET 이내로 수신한다. 첫 오류에서 중단하며 재시도하지 않는다. 요청·최대 wire bytes 예약은 원장 fsync 이후 HTTP보다 먼저 끝난다. 미확정 요청/중단 뒤 새 실행 ID도 같은 저장 경로에서 다시 호출하지 않는다. 180초 실시간 SIGALRM·요청/원시저장 한도가 강제 정지한다. 별도 24시간 대기는 만들지 않는다.

원시 bytes와 native state는 source artifact 내부에 둔다. stdout은 실제 요청수·bytes·원천 cursor·시간·누락·parity·신호/참조 수량만 공개한다. 펀딩 부호·가격·P&L은 공개하지 않는다. 90일 보존은 이 비정식 연결시험에만 적용하며 정식 검증 보존 적격성을 뜻하지 않는다.

35 GET 짧은 계획은 완료 4시간봉 prefix를 한 번만 읽는다. 두 번의 깊이 호가 cursor 증가가 관측되어도 완료봉의 신규 진행은 0으로 별도 표시한다. source `NO_SIGNAL`은 승인 불충분과 구분하며, 과거 시가 체결·현재 시장 실제 체결을 생성하지 않는다. full formal source ready는 false이다.

11개 신규 경계/재시작/무시세 출력 시험의 실제 결과와 수정 이력은 IMPLEMENTATION_RECEIPT.json에 있다. 전체 native 통합은 S2 명령과 root CI에서 수행한다.
