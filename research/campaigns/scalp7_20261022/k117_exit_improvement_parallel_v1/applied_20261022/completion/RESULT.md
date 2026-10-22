# K117 실제 C/D 시세 상태추적 완료

분류: ACTUAL_PASSIVE_TRACE_COMPLETE_NOT_NEW_ECONOMIC_IMPROVEMENT.

고정 baseline 8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8, 117거래·미결·경계·원래 신호·기회만료 사건의 정확한 재현을 각 관측기가 검증했다.
정책 변경·추가 경제비교·실주문·현행 Shadow 변경은 모두 0이다. 계측에 사용한 두 원형 재생은 신규 전략 성과가 아니다.

## 실제 결과
- C: 전체 117거래의 원래 EMA 접촉과 실제 완료봉 판단·청산 순서를 연결했다.
- D: 전체 117거래의 본전보호·다음 봉 손절 적용·부분익절·러너·최종 청산을 연결하고 Gross-Cost=Net을 검산했다.

C 집단별 관측: ```json
{
  "cost_cross": {
    "T": 28,
    "adverse_close_to_exit_minutes": {
      "maximum": 660.0,
      "median": 270.0,
      "minimum": 90.0,
      "n": 13
    },
    "no_completed_callback": 0,
    "with_adverse_completed_close": 13
  },
  "loss1x": {
    "T": 46,
    "adverse_close_to_exit_minutes": {
      "maximum": 720.0,
      "median": 120.0,
      "minimum": 30.0,
      "n": 43
    },
    "no_completed_callback": 2,
    "with_adverse_completed_close": 43
  },
  "winner1x": {
    "T": 71,
    "adverse_close_to_exit_minutes": {
      "maximum": 1470.0,
      "median": 540.0,
      "minimum": 90.0,
      "n": 35
    },
    "no_completed_callback": 0,
    "with_adverse_completed_close": 35
  }
}
```

D 집단별 관측: ```json
{
  "all117": {
    "T": 117,
    "be_arm_to_exit_minutes": {
      "maximum": 1320.0,
      "median": 120.0,
      "minimum": 0.0,
      "n": 64
    },
    "be_armed": 64,
    "partial_executed": 36,
    "runner_armed": 30
  },
  "cost_cross": {
    "T": 28,
    "be_arm_to_exit_minutes": {
      "maximum": 240.0,
      "median": 60.0,
      "minimum": 30.0,
      "n": 25
    },
    "be_armed": 25,
    "partial_executed": 1,
    "runner_armed": 0
  },
  "loss1x": {
    "T": 46,
    "be_arm_to_exit_minutes": {
      "maximum": null,
      "median": null,
      "minimum": null,
      "n": 0
    },
    "be_armed": 0,
    "partial_executed": 0,
    "runner_armed": 0
  },
  "winner1x": {
    "T": 71,
    "be_arm_to_exit_minutes": {
      "maximum": 1320.0,
      "median": 120.0,
      "minimum": 0.0,
      "n": 64
    },
    "be_armed": 64,
    "partial_executed": 36,
    "runner_armed": 30
  }
}
```

## 한계
불리한 종가 관측만으로 실패 구분이나 조기청산 이익은 증명되지 않는다. 원래 청산 이후 회복 여부 및 대체 정책의 순손익·놓친 승리는 별도 비교가 필요하다. 기존 K117 개발 손익은 변경하지 않았다.

모든 원시 호출 trace는 서버에 보존하고 파일별 해시를 TRACE_STORAGE_MANIFEST.json에 기록했다. GitHub에는 전체 117거래 연결 trace 두 개·실행 영수증·검산 결과를 저장했다.
완료 기록 생성 UTC: 2026-10-22T11:37:15.424250+00:00
