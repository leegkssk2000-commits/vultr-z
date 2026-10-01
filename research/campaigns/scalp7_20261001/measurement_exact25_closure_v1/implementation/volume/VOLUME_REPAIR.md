# 거래량 공통 입력의 실제 수정과 남은 근거

범위: G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1.
신규 FULL은 0회이며 기존 5회 원장·원본 봉인은 수정하지 않았다.

## 저장 원천의 확인 결과

SOURCE_CONTRACT.json은 기존 readiness 조사에 결속된 원본 응답 2개의
실제 SHA256을 다시 대조하고 객체 필드만 조사한 결과다.
999행 및 204행 응답은 모두 close/high/low/open/time/volume 객체다.
quote volume 필드와 단위·계약 승수 메타데이터는 없다.
이는 전체 가격 기록에서 전략·신호·경제결과를 새로 계산한 작업이 아니다.

실제 canonical volume 단위는 여전히 UNKNOWN이다.
공식 문서의 다른 배열 응답 volume 설명, 다른 거래소 필드 설명,
정규화된 열 이름은 이 저장 객체의 역사 단위 증명이 아니다.
quote volume을 가격×unknown volume으로 만들지 않았다.
기존 가용시각은 봉 마감에 따른 모형이며 역사 전달 지연의 실측 증거가 아니다.
이번 수정으로 단위 근거가 복구되었다고 주장하지 않는다.

## 닫은 코드 연결 공백

backend/research/rebuild/scalp7_volume_contract_v1.py가 공통 입장 계약을 구현한다.

| 실제 기존 차이 | 이번 연결 |
| --- | --- |
| BBIII/OBV/MFI caller는 volume_unit=base를 요구하고 열 단위는 선택적으로만 확인 | 원천 단위·필드·자산·schema/revision/단위 권위 결속을 먼저 확인한다. UNKNOWN 및 config만의 BASE 선언은 차단한다. |
| AVWAP caller는 대문자 BASE, volume_base/volume_quote를 사용 | 실제 입장된 필드만 caller별 표기로 바꾸며 true AVWAP은 관측된 서로 다른 BASE/QUOTE 필드를 모두 요구한다. |
| 가격 시각 하나만으로 참여량 지표를 계산할 위험 | 가격과 필요한 거래량 필드의 가용시각 최대값을 사용하고 연속 구간 의존성의 누적 가용시각을 보존한다. |
| quote/base를 동일 열로 전달하거나 다른 자산 차원을 섞을 위험 | 열 별칭·단위·자산 차원·음수·비유한 값·미성숙 시각·혼합 행 단위를 거부한다. |
| source mark 가격을 last로 표기할 위험 | source row/attrs/binding의 price_type 및 price_basis 충돌을 검수하고 차단한다. |
| 거래량 proof 부재에 대한 호출부 결과가 분산됨 | evaluate_volume_component가 심볼별 BLOCKED_VOLUME_INPUT_CONTRACT와 원인을 반환한다. |
| AVWAP의 symbol_configs만으로 basis를 선택하면 top-level 사전 검수에서 거부됨 | 심볼 config 병합 후 basis와 필요 필드를 검수한다. top-level은 기본값이며 심볼별 override가 우선한다. 이질적 계약은 PER_SYMBOL로 보고하고 한 심볼의 단위·quote 권위를 다른 심볼에 적용하지 않는다. |
| Gajjala가 같은 검수된 참여량 입력을 재사용할 연결 부족 | admit_observed_base_frame은 지표·매매 계산 없이 검수된 BASE frame을 반환한다. |

기존 scalp7_exact25_indicators_v1과 scalp7_exact25_reference_v1의
수식, pivot, alert, reclaim, 원문 locator는 재사용하며 변경하지 않았다.
검수 adapter 자체는 선언한 구현 계약이다. 원저자의 전체 매매법이 아니다.

## 계약의 권위와 제한

binding은 venue/product/instrument/base_asset/quote_asset/price_unit,
실제 필드 이름 및 단위·자산·관측 여부·필드 가용시각,
source_revision_sha256/source_schema_sha256/source_unit_authority_sha256,
원천 권위 locator와 evidence_kind를 가진다.
세 SHA256은 frame.attrs의 독립 입력 결속과 정확히 일치해야 한다.
실측 history는 HASH_BOUND_SOURCE_SCHEMA 권위가 필요하고,
시험 데이터는 SYNTHETIC_FIXTURE/SYNTHETIC_UNIT_TEST_ONLY/
SYNTHETIC_TEST_ONLY를 명시해야 한다.

이 함수는 전달받은 검수된 계약을 검사한다. 임의 문자열의 의미를 증명하거나
파일·문서의 진위를 자동 조사하는 수집기가 아니다.
실측 caller는 그 frame의 실제 원본 파일 해시와 해당 source schema/단위 권위의
범위가 일치하는 것을 외부 입력 검수·봉인에서 먼저 확인해야 한다.
수집기/loader로 구현하지 않은 계약을 신규 genuine-history 경제 caller로
연결할 권한은 이번 작업에 없다. 현재 canonical UNKNOWN은 그대로 차단된다.
FIXED_CONTRACTS를 BASE로 변환할 승수 근거도 현재 없으며 자동 변환하지 않는다.

BASE_QUOTE_SUMS는 실제 quote/base를 계산한다.
HLC3_BASE_PROXY는 명시적으로 선택한 기존 근사 모드이며 trade_vwap_claim=false다.
근사 모드가 단위 수선을 대신하지 않는다. BASE 단위 입장은 동일하게 필요하다.
고정 anchor 선택·전체 관리·host 역할은 해당 기존 모델의 별도 공백으로 남는다.

## 인공 시험과 검증

tests/test_scalp7_volume_contract_v1.py는 실제 원천 파일을 읽지 않는다.
관측 필드→입장 adapter→기존 BBIII/OBV/MFI/AVWAP component caller를 연결한다.
검수 범위는 UNKNOWN 차단, 원천 해시 결속, quote/base 차원,
필드별 지연과 누적 가용성, 불필요한 quote 지연 제외,
prefix/future mutation 인과성, OBV 독립 손계산,
true AVWAP와 HLC3 근사의 독립 손계산, 물리 단절의 state 보존이다.
PR #1346 검토 후 회귀시험은 총 57개다. 추가 12개는 두 VWAP component의
심볼별 BASE_QUOTE_SUMS/HLC3_BASE_PROXY 혼합, top-level basis 생략,
기본값과 override, 독립 필드 mapping 및 quote 지연의 인과성,
UNKNOWN/quote ABSENT/basis 부재의 심볼별 차단을 실제 기존 caller까지 검증한다.
인공 손계산 42/4와 46/4를 구별하며 proxy에 끼워 넣은 quote 열은 입장되지 않는다.

최종 실행 증거는 synthetic_tests.txt와 루트 통합 검증 영수증을 참조한다.
단위시험 개수는 T/WR/PnL/DD 측정치가 아니다. 새로운 수익 측정은 미실행이다.
경제 독립매매·host 채택·LIVE·승격·배포는 승인되지 않았다.

## 남은 공백과 다음 판단

현재 해결된 것은 실행 가능한 공통 입력 검수 및 실제 기존 caller 연결이다.
미해소는 역사 객체 volume의 단위 권위와 실제 quote volume 원본,
자동 causal anchor 및 일부 완전 관리 정책이다.
AVWAP/BBIII/OBV/MFI를 단위 근거가 해결된 완전 전략으로 표시하지 않는다.
다음 경제배치의 identity·변경축·동일 자료/비용/기간 및 최소 횟수는
통합 보고가 한 번에 제시하며 이 파일은 신규 실행을 예약하지 않는다.
