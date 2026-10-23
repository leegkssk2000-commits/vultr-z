# 독립 코드 검토

검토 결론: **현재의 동결 저장증거 검증·회고 집계 범위에서 미해결 blocking 결함 없음.** 경제 개선, 원천 시세의 인과성 또는 실행가격의 정확성을 승인한 검토가 아니다.

검토한 파일 SHA256:

| 파일 | SHA256 |
|---|---|
|receipt_guard.py|`6591289def36d6e9f0dd76ff923b2017dd51f953e1724b35aa37f12e479a498a`|
|attribution.py|`4ab5329f3abcdec339583e06fba266d949865a76267bcf91c03b9f5ee79d7641`|
|PINNED_INPUTS.json|`41cce7c4cccda2af05a66871b0c58cb841c921dcd9090b661f1c90c1dee879fe`|

검토에서 발견한 native-parent 혼합 문제가 수정됐다. 처음에는 synthetic pin까지 바꾼 다른 native parent가 boundary 일치만으로 통과했고 지정 음성시험이 실제 실패했다. 수정본은 source metadata·execution snapshots 일치, 고유 native intent, parent_intent와 parent_entry 연결, 보존된 policy/feature/config/cost/geometry 필드까지 비교한다. 진짜255/최신256 입력은 각각 통과하고 다른 native parent 대체는 거부한다.

산술·시간 음성시험이 먼저 long-subset 불일치에서 끝나는 문제도 수정됐다. 수정된 시험은 child와 해당 delayed-parent 행을 함께 바꾸어 깊은 검증 경로를 시험한다. 저장 Gross/Net 수식과 비정상 숫자·시간을 확인했고, 합성 forged-PASS hardening으로 원래 observer의 혼합 허용과 새 guard의 거부를 재현했다. 이 관측 함수 시험에는 시장조회·가격경로 평가·native main 실행이 없다.

독립적으로 실행한 수정 후 지정시험은 다음4개이며 모두 PASS다. 전체 패키지 시험수와 결과는 별도 검증 영수증을 따른다.

- 진짜 두 코호트의 별도 검증과 권한 차단.
- 다른 실제 parent/native-parent 대체 거부.
- 잘못된 경제 필드·숫자·시간 거부.
- 원래 observer의 합성 혼합 반례와 새 guard의 거부.

집계 코드도 읽어 확인했다. 비용2x는 `Gross−2×원래 비용`이며 비용/펀딩을 다시 더하지 않는다. Decimal 재계산과 저장 float Net 잔차를 구분한다. 원문 순서·exit-bar 개별 순서·동시 exit cohort의 DD/연패를 나누고, same-time tie·봉 시작 timestamp·zero-span 점유의 한계를 표시한다. top winner/LOOG는 사후 민감도이며 원문 전행과 모든 승리 거래를 유지한다. 두 snapshot의 변화는 공통행 변화+추가−제거로 정확히 대사하며 독립 forward 수익이나 후보 개선으로 주장하지 않는다.

남아 있는 입력 한계는 정확히 노출돼 있다: FeatureSnapshot 본문/가용시각0, H4 내부 raw control vector 미보존, H5 regime은 별도 fetch 진단, 원래 SL geometry와 실제 기록 exit의 불일치, 큰/일반/회복 승리 정의·경로 미확인, account NAV/DD 없음. native-parent 연결은 저장된 필드와 archive를 검증할 뿐 raw feature·실제 fill을 인증하지 않는다. 특히255의10개 SL 불일치를 강제 삭제하거나 재가격화하지 않는 처리가 적절하다.

검토 중 기존 D historical256·K117 원장은 다시 평가하지 않았다. 파일 수정은 이 검토문만 했으며 경제 FULL/native replay/시장 API/원격 변경/권한 변경0이다. CLI 출력은 새 결과 경로를 지정한다. guard 정상 종료는 `PASS_PINNED_RECEIPT_BINDING`과 `CURRENT_TRENDRIDER_NO_CAUSAL_CHILD` 증거 검증이며 경제·Shadow PASS가 아니다.
