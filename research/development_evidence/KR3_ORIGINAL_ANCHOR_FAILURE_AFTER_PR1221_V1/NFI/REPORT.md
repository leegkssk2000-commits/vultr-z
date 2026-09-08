# NFI 공개 원문 제한 검토

판정: **공개 구현·저장 백테스트 근거는 확인했지만, ZEL에 적격한 성과는 미검증이다. NFI 실측·도입은 이번 범위에 포함하지 않는다.** KR3 실행과 독립적으로 종료했다.

고정 원문: `iterativv/NostalgiaForInfinity`의 읽기 시점 main `3e94773c122eb0fb5e2a84ec2780d42254896f33` (2026-09-08 16:51:41 UTC). `NostalgiaForInfinityX8.py` v18.0.17, Git blob `733cd5dd62069d3d34a08600c97e1023c4db2c34`. 내려받은 원문 2,499,986바이트의 Git blob을 실제 검산했다. SHA256 `dcdae48eb278eac98d18e045f60a6d55a7c75a23af6265a51643fced51268ccd`.

| 항목 | 원문에서 확인한 내용 | ZEL 해석 |
|---|---|---|
| 봉·준비자료 | 본봉 5m, 종목별 보조봉 15m/1h/4h/1d, BTC 보조봉 4h. 기본 준비봉 800개; BingX 분기 499개 | 기존 4h 원천으로 5m 경로를 복구할 수 없다. 4h로 치환하면 원형이 달라진다 |
| 설정 예시 | dry-run, 10,000 USDT, 6슬롯, stake unlimited, 5m, 지정가 진입·청산, 거래소 이름 빈 문자열 | 예시는 실제 실행에서 해석된 설정이 아니다. venue·현물/선물·엔진·수수료를 별도 고정해야 한다 |
| 청산·점유 | stoploss −0.99, trailing false, custom stoploss false. 별도 custom exit, 포지션 조정·grinding·derisk 기능 사용 | −99% 하나만 보고 실제 손실 관리 전체를 설명할 수 없다. 추가주문·부분청산·잔고 경로가 KR3와 다르다 |
| 선물 분기 | 선물/margin이면 short 허용; 기본 선물 레버리지 3배. 소스에 BingX 준비봉 분기 존재 | 코드 분기는 BingX 선물 live 지원·체결 검증을 뜻하지 않는다 |
| 비용 | 사용자 지정 진입/청산 fee 기본 None, 거래 객체 fee를 사용 | resolved fee·funding·slippage·실제 체결 비용까지 연결되지 않았다 |

설정과 원형 의미의 출처: [X8 원문](https://github.com/iterativv/NostalgiaForInfinity/blob/3e94773c122eb0fb5e2a84ec2780d42254896f33/NostalgiaForInfinityX8.py), [공식 예시 설정](https://github.com/iterativv/NostalgiaForInfinity/blob/3e94773c122eb0fb5e2a84ec2780d42254896f33/configs/exampleconfig.json), [README](https://github.com/iterativv/NostalgiaForInfinity/blob/3e94773c122eb0fb5e2a84ec2780d42254896f33/README.md).

성과근거는 README가 가리키는 동일 commit의 GitHub Actions 댓글 20개를 회수했다. 이 회수에서 확인한 댓글은 Kucoin **현물** 월별 백테스트다. 다음은 게시된 값의 예시이며, 당사 재실행 결과·동일명목 KR3 비교·독립 OOS 성과가 아니다.

| 게시 기간 | 거래 수 | 게시 계정 순수익률 | 게시 PF | 지갑 평가 낙폭 | 출처 |
|---|---:|---:|---:|---:|---|
| 2025-02 | 30 | +7.35% | 4.80 | 6.27% | [댓글 199562646](https://github.com/iterativv/NostalgiaForInfinity/commit/3e94773c122eb0fb5e2a84ec2780d42254896f33#commitcomment-199562646) |
| 2025-05 | 1 | −0.87% | 0.00 | 1.21% | [댓글 199562657](https://github.com/iterativv/NostalgiaForInfinity/commit/3e94773c122eb0fb5e2a84ec2780d42254896f33#commitcomment-199562657) |
| 2026-03 | 2 | −0.74% | 0.22 | 2.00% | [댓글 199562706](https://github.com/iterativv/NostalgiaForInfinity/commit/3e94773c122eb0fb5e2a84ec2780d42254896f33#commitcomment-199562706) |
| 2026-08 | 12 | +1.72% | 0.00 표기¹ | 2.02% | [댓글 199562728](https://github.com/iterativv/NostalgiaForInfinity/commit/3e94773c122eb0fb5e2a84ec2780d42254896f33#commitcomment-199562728) |

¹ 2026-08 표는 12승·0패를 함께 보고한다. 손실 없는 표본의 PF 0.00 표기를 경제적 PF=0으로 해석하지 않는다. 일부 월은 극소 표본이고, 월별 값을 연결된 계정 곡선으로 합산하지 않았다. 손실월을 포함하므로 성공 전략이라고 사전 판정하지 않는다.

공개 CI는 Kucoin 현물·Binance 현물/선물을 별도로 실행하도록 작성돼 있다. 엔진 Docker 이미지와 시세 이미지가 가변 태그를 사용한다. 해당 실행의 실제 digest, 실행 시 설정, 원시 주문·비용 원장까지 연결하지 않았으므로 같은 commit만으로 완전한 재현성을 주장할 수 없다. 현재 댓글 회수에서 Binance 결과를 확인하지 못한 것을 Binance 실행 실패로 단정하지 않는다. [공식 CI 원문](https://github.com/iterativv/NostalgiaForInfinity/blob/3e94773c122eb0fb5e2a84ec2780d42254896f33/.github/workflows/backtests.yml)

향후 원형 비교에 필요한 원천은 지정 venue의 5m OHLCV·충분한 준비구간, 종목별 보조봉과 BTC4h, 고정 pairlist/blacklist·상장 상태, 엔진/설정 digest, 주문·추가매수·부분청산·지갑/미완결 원장, 수수료·선물 funding·체결 비용이다. 공식 다운로드 스크립트는 5m 및 1d/4h/1h/15m/1m 자료와 외부 historical archive를 가리킨다. **스크립트 읽기만 수행했으며 시세 저장소·시세 이미지는 내려받지 않았다.** [공식 자료 스크립트](https://github.com/iterativv/NostalgiaForInfinity/blob/3e94773c122eb0fb5e2a84ec2780d42254896f33/tools/download-necessary-exchange-market-data-for-backtests.sh)

종료: 공개 내용 원문 6종(README·전략·설정·CI·동일 commit 댓글 모음·자료 스크립트), commit/tree 메타데이터 확인. NFI 신규 경제평가 0회, 시장 요청 0회, 유료 AI 0회, 설치/배포 0회. 자료 확보나 NFI 실행을 KR3의 선행조건으로 만들지 않았다. 파일별 pin과 회수한 20개 댓글의 요약 연결은 `EVIDENCE.json`에 보존했다.
