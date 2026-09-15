"""Render the two required tables from saved research evidence only."""

from __future__ import annotations
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REPORT = Path(__file__).resolve().parent
RUNTIME = Path("/home/z/z/runtime/scalp7_broad_v2_20260915")
ALIASES = {
    "K.P": "scalp7_keltner_hg_parent_utc30m_v2",
    "R.C": "scalp7_rider_15m_impulse_pullback_reclaim_v2",
    "B.C": "scalp7_break_15m_anchored_retest_reclaim_v2",
    "ST.C": "scalp7_supertrend_native_impulse_pullback_30m_v2",
    "S.P": "scalp7_squeeze_panic_cost4_parent_utc30m_v2",
    "MR.P": "mr_cross_sectional_v1_30m_causal_control_v2",
    "Micro": "MICRO_OBSERVED_TRADE_RECLAIM_15M_V2",
    "K.TD075": "scalp7_keltner_hg_td075_utc30m_v2",
    "S.BE1R": "scalp7_squeeze_panic_cost4_be1r_utc30m_v2",
    "MR.BAR4": "mr_reexpansion_bar4_30m_causal_control_v2",
    "MR.FORM": "mr_btceth_weekly_formation_30m_v2",
    "R.P": "scalp7_trend_rider_opportunity_control_15m_v2",
    "B.P": "scalp7_break_and_continue_opportunity_control_15m_v2",
    "ST.P": "scalp7_supertrend_pullback_opportunity_control_30m_v2",
}
LABELS = {
    "K.P": "Keltner parent",
    "R.C": "Trend Rider rebuild",
    "B.C": "Break rebuild",
    "ST.C": "Supertrend rebuild",
    "S.P": "Squeeze parent",
    "MR.P": "MR V1 parent",
    "Micro": "Micro EDGE",
    "K.TD075": "Keltner TD0.75 child",
    "S.BE1R": "Squeeze BE1R child",
    "MR.BAR4": "MR re-expansion child",
    "MR.FORM": "MR weekly formation child",
    "R.P": "Rider causal control",
    "B.P": "Break causal control",
    "ST.P": "Supertrend causal control",
}


def number(value, digits=2):
    return "N/A" if value is None else f"{value:,.{digits}f}"


def pct(value):
    return "N/A" if value is None else f"{100*value:.1f}%"


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        + ["| " + " | ".join(map(str, row)) + " |" for row in rows]
    )


def main():
    data = json.loads((REPORT / "FINAL_COMPARISON_V2.json").read_text())
    now = dt.datetime.now(dt.timezone.utc)
    paper_path = RUNTIME / "observed_paper_clock_v3/STATE.json"
    paper_bytes = paper_path.read_bytes() if paper_path.exists() else b'{"trades":[]}'
    paper = json.loads(paper_bytes)
    fresh = collections.Counter(row["identity"] for row in paper["trades"])
    rows = []
    for alias, identity in ALIASES.items():
        if alias == "Micro":
            code = ROOT / "backend/research/rebuild/scalp7_micro_decision_v2.py"
            sha = hashlib.sha256(code.read_bytes()).hexdigest()
            rows.append(
                [LABELS[alias], "15m", alias + "@" + sha[:8]]
                + ["N/A"] * 13
                + [fresh[identity], "N/A", "N/A", "N/A", "실제 tape fresh; 역사 L2 N/A"]
            )
            continue
        row = data["rows"][identity]
        m = row["rolling1x"]
        s = row["rolling2x"]
        change = data["comparisons"].get(identity, {}).get("cost1x")
        delta = (
            (
                "T "
                + number(change["T"], 0)
                + ", WR "
                + number(change["WR_pct"])
                + "pp, Net "
                + number(change["Net_bps"])
                + ", DD "
                + number(change["DD_bps"])
            )
            if change
            else "frozen parent/control"
        )
        status = "순손실 · Core 불가"
        if alias in {"K.P", "S.P"}:
            status = "parent 보존 · 2x 양수 · fresh 미확증"
        elif alias == "MR.P":
            status = "1x 소폭 양수 · 2x 음수 · 보류"
        elif alias == "K.TD075":
            status = "parent 대비 악화 · 미채택"
        elif alias == "S.BE1R":
            status = "rolling 동일 · 별도 fresh"
        elif alias == "MR.BAR4":
            status = "DD 개선/Net 악화 · 미채택"
        elif alias == "MR.FORM":
            status = "formation 실패 · 미채택"
        concentrations = "/".join(
            pct(m["concentration"][axis]["largest_positive_profit_share"])
            for axis in ("month", "symbol", "session")
        )
        rows.append(
            [
                LABELS[alias],
                str(row["candidate"]["tf"]) + "m",
                alias + "@" + row["module_sha256"][:8],
                m["T"],
                number(m["T_per_day"], 3),
                number(m["WR_pct"]),
                number(m["Gross_bps"]),
                number(m["Net_bps"]),
                number(s["Net_bps"]),
                number(m["NetExp_bps_T"]),
                number(m["PF"], 3) + "/" + number(s["PF"], 3),
                number(m["DD_bps"]) + "/" + number(s["DD_bps"]),
                m["MaxLossStreak"],
                number(m["loss_tail"]["expected_shortfall_5pct_all_trades_bps"]),
                number(m["hold_median_min"], 0) + "/" + number(m["hold_p95_min"], 0),
                str(row["rolling_windows1x"]["positive_window_count"])
                + "/"
                + str(row["rolling_windows1x"]["window_count"]),
                fresh[identity],
                concentrations,
                pct(m["largest_winner_contribution"]),
                delta,
                status,
            ]
        )
    headers = [
        "CURRENT TOP7 / 고정 비교본",
        "TF",
        "Identity/SHA",
        "T",
        "T/day",
        "WR%",
        "Gross bps",
        "Net 1x bps",
        "Net 2x bps",
        "Net/T bps",
        "PF 1x/2x",
        "DD 1x/2x bps",
        "MaxLS",
        "loss tail ES5 bps",
        "hold median/p95 분",
        "rolling +window",
        "fresh T",
        "월/심볼/session 집중",
        "최대 winner 기여",
        "parent 대비",
        "최종 상태",
    ]
    assert all(len(row) == len(headers) for row in rows)
    material_rows = []
    assessment = {}
    for identity, value in data["materials"].items():
        m = value["cost1x"]
        s = value["cost2x"]
        p = data["rows"][value["parent"]]["rolling1x"]
        change = value["marginal_change"]
        family = identity.removesuffix("_30m_round1_v2")
        assessment[identity] = {
            "economic_rejection_reasons": [
                "NET_NONPOSITIVE",
                "PF_NOT_ABOVE_ONE",
                "NEGATIVE_ECONOMIC_MARGINAL",
                "DD_WORSE",
                "FRESH_VALIDATION_PENDING",
                "SUFFICIENT_SAMPLE_BOUNDARY_NOT_PREREGISTERED",
            ],
            "grade": "C",
            "fresh_T": fresh[identity],
            "B": False,
            "A": False,
        }
        material_rows.append(
            [
                "C",
                family
                + " control; T="
                + str(p["T"])
                + ", Net="
                + number(p["Net_bps"])
                + ", PF="
                + number(p["PF"], 3),
                "round1 @" + data["rows"][identity]["module_sha256"][:8],
                m["T"],
                number(m["WR_pct"]),
                number(m["Net_bps"]) + "/" + number(s["Net_bps"]),
                number(m["PF"], 3) + "/" + number(s["PF"], 3),
                number(m["DD_bps"]) + "/" + number(s["DD_bps"]),
                "ΔNet "
                + number(change["Net_bps"])
                + ", ΔDD "
                + number(change["DD_bps"]),
                number(value["parent_behavior_cosine"]["behavior_cosine"], 3),
                "T=" + str(fresh[identity]) + "; 미확증",
                "B=0/A=0; 경제조건 실패",
            ]
        )
    lead = [
        "**실행 결과: 수익형 7-lane 시스템은 아직 성립하지 않았다.** 고정 21 identity의 12개월 실제 원천 기반 실행을 완료했다. T·WR·Net·DD 동시 개선 0개, C→B 0개, B×B 시작 불가. order/live authority는 BLOCKED다.",
        "",
        f"Fresh 원장 확인 시각: {now.isoformat()}. 아래 경제 표는 rolling 245 calendar days만 사용한다. 초기 90일 문맥 학습, 30일 validation, 이후 9개 rolling window(8×30일+5일)를 분리했다. 과거를 본 뒤 설계한 구조이므로 chronological parameter-OOS이며 genuine fresh로 부르지 않는다.",
        "",
        "원천: 2025-09-15 00:00–2026-09-15 00:00 UTC. 6심볼 실제 1분봉 3,153,576개. 심볼별 4분(2026-02-13 20:32–20:35 UTC) 누락을 보존했다. 합성 봉·합성 L2·합성 체결은 없다. 24개월 자료는 확보되지 않았다.",
        "",
        "Gross/Net/DD는 동일 명목 거래 bps 합산이며 계좌 수익률이 아니다. DD는 완료 결과의 동시 시각 묶음 기준이며 MTM DD는 미산출이다. 1x/2x는 동일 고정 거래·배분에 비용만 1배/2배 적용한다. 현재 관측한 reference cost를 사용하며 역사 실제 수수료·펀딩·체결비용을 재현했다고 주장하지 않는다.",
        "",
        "집중도는 해당 축의 최대 그룹이 양수 net 거래 이익 총합에서 차지한 비중이다. 최대 winner도 같은 분모다. 손실 월·심볼·session별 net은 JSON에 모두 보존했다. ES5는 모든 거래 중 하위 5% 평균 net이다. 빈 rolling window도 양수 비율 분모 9에 포함한다.",
        "",
        "**표 1 — CURRENT TOP7.** 첫 7행은 사전 고정 primary set이다. 아래 비교본은 별도 frozen identity이며 결과에 맞춰 primary를 교체하지 않았다.",
        "",
        table(headers, rows),
        "",
        "**표 2 — MATERIAL/FUSION.** 각각 한 causal axis의 round1을 실행했다. 최대 3회라는 상한을 반복 튜닝의 목표로 사용하지 않았다. Round2/3는 동결·실행하지 않았다.",
        "",
        table(
            [
                "grade",
                "parent",
                "child",
                "T",
                "WR%",
                "Net 1x/2x bps",
                "PF 1x/2x",
                "DD 1x/2x bps",
                "marginal contribution",
                "parent behavior cosine",
                "fresh 상태",
                "B/A 승격",
            ],
            material_rows,
        ),
        "",
        "4개 child 간 behavior cosine: "
        + ", ".join(
            number(v["behavior_cosine"], 3)
            for v in data["material_peer_cosines"].values()
        )
        + ". 중복 기준 0.85 이상은 없지만 독립 B가 0개이므로 fusion 자격이 없다. C×C brute force와 Top7 이식은 수행하지 않았다.",
        "",
        "Rebuild 3개는 총손실·실현 DD·MaxLS를 줄였지만 T를 크게 잃었다. Supertrend는 WR과 Net/T도 개선됐으나 비용 후 음수다. 세 구조 모두 ES5 loss tail과 최대 winner 집중도는 악화됐고 Break는 Net/T도 악화됐다. 총손실 감소를 충분한 edge로 해석하지 않는다.",
        "",
        "Keltner·Squeeze parent는 rolling 2x에도 양수다. Keltner TD0.75는 부모보다 WR·Net·DD가 악화돼 미채택이다. Squeeze BE1R은 동일 결과다. MR bar4는 T·DD 개선과 Net·WR 저하가 함께 나타났고 proper formation child는 실패했다. 어느 child도 결과를 보고 역사 재튜닝하지 않았다.",
        "",
    ]
    for mode, label in [
        ("equal7", "동일 1/7 비중"),
        ("adaptive", "과거 완료 shadow health 기반 배분"),
    ]:
        x = data["portfolio"][mode]
        a = x["cost1x"]
        b = x["cost2x"]
        lead += [
            f"포트폴리오 {label}: T {a['T']}, T/day {a['T_per_day']:.3f}, WR {a['WR_pct']:.2f}%, Net 1x/2x {a['Net_bps']:.2f}/{b['Net_bps']:.2f}bps, PF {a['PF']:.3f}/{b['PF']:.3f}, DD {a['DD_bps']:.2f}/{b['DD_bps']:.2f}bps. 수익 시스템 채택 불가.",
            "",
        ]
    lead += [
        "Portfolio는 과거 완료·공개된 shadow 결과만 health에 사용하고, 같은 시각 이미 유효한 저장 opportunity에만 배분한다. 없으면 cash이며 replacement trade를 만들지 않는다. 최대 gross weight 1, 미해결 갭 포지션은 자본 점유. 입력은 독립 sleeve의 체결 및 미해결 opportunity 원장이므로 독립 sleeve 점유 중 빠진 모든 raw valid signal까지 포함한 완전한 opportunity pool은 아니다. 연구 window별 독립 flat 시작이며 연속 계좌 곡선이 아니다.",
        "",
        "Fresh 원래 시도는 2026-09-15 20:00 UTC 시작 후 native timestamp가 local receipt보다 1–4ms 앞선 관측에서 안전 중단됐고, 완료 거래·미결 포지션은 모두 0이었다. 원장과 V2 코드를 보존했다. 경제 규칙을 바꾸지 않은 V3 시각 검증을 21:00 UTC 전에 동결하고, 21:00 UTC부터 7 primary 및 별도 child/material의 공통 후속 관측을 시작했다. 원본 시각을 보존하며 실제 wall clock이 도달했다는 hash-linked 증명 후에만 자료를 사용한다. 5000ms 대기 한도·clock reversal·자료 누락은 HOLD다. Micro는 재연결 뒤 완전한 실제 15m bucket을 먼저 확보한다. 실제 공개 trade tape와 1분봉만 수집하며 decision은 15m/30m다. Paper는 실제 decision publication 후 새 요청으로 받은 호가만 사용한다. 신호 수를 fresh T로 세지 않는다. 실제 계좌 체결·주문·capacity 입증은 없다. Genuine fresh 검증에는 앞으로 도착할 자료가 필요하다.",
        "",
        "Validation 30일은 rolling 표에 합치지 않았다. identity별 validation T/WR/Net/PF/DD·2x는 CAMPAIGN_FINAL_RESULTS_V2.json의 window_receipts에서 partition=validation로 별도 보존한다. 초기 90일은 문맥 학습만 수행하고 train PnL을 만들지 않았다. Window 끝 미완료와 갭 미결 거래는 임의 종가 청산하지 않았다.",
        "",
        "최초 Rider/Break 대조군은 segment_id 문자열/정수 불일치로 모든 신호가 거절돼 실제 fill=0이었다. 두 시도는 기술 오류로 보존하며 성과에서 제외했다. 유효한 기존 4개 positive를 재실행하지 않고, 같은 lexical segment ID의 타입만 맞춘 별도 repair를 경제결과 전에 동결해 나머지 17개를 실행했다. 원래 전략·가격·갭·비용·규칙은 바꾸지 않았다.",
        "",
        "독립 saved 검증은 21개 identity의 raw fill 49,581개, rolling 완료 43,742개를 검산했다. 경계와 정확히 같은 outcome 8개는 제외한다. 보존된 Keltner parent32개/TD07529개 raw partial 거래는 개별 cashflow event가 빠져 있어 terminal entry/exit만으로 gross 전체를 독립 복원할 수 없다. net/cost 산술은 일치하고 유효 실험은 반복하지 않았다. 나머지 17개는 partial cashflow도 명시적으로 검산했다.",
        "",
        "현행 endpoint OPEN timestamp는 실제 전후 표본으로 확인했고 역사 1m→native 1h OHLC도 일치했다. 같은 endpoint의 과거 timestamp 해석은 추론이며 역사 delivery latency는 관측되지 않았다. 역사 available time은 bar close 모델이다. raw volume/quantity unit이 불명확해 방향이나 L2를 가정하지 않았다. Micro raw는 4GiB 용량 한도 내 실제 수집이며 무제한 수집 약속이 아니다.",
        "",
        "CI는 저장 원장 해시·산술과 causal fixture만 검증하며 경제 재실행을 하지 않는다. Active5 1h, TrendRider Broad, G4/G5 및 old Top3/Liquid6 성과는 이 표에 포함하지 않았다.",
        "",
        "Micro는 최초 역사 계약의 미구현 placeholder scalp7_micro_observed_tick_15m_v2를 경제 결과에 사용하지 않았다. 실제 frozen fresh identity MICRO_OBSERVED_TRADE_RECLAIM_15M_V2는 공통 시작 전 forward config의 external_micro에 결속했다. 이 명시적 연결은 MICRO_IDENTITY_BINDING_V2.json에 보존한다.",
        "",
        "표 alias의 exact identity (@는 모듈 SHA256 앞 8자리):",
        "",
    ]
    lead += [
        f"- {key}: " + chr(96) + identity + chr(96) for key, identity in ALIASES.items()
    ]
    lead += [
        "",
        "- [전체 경제 원장·2x·모든 월/심볼/session](FINAL_COMPARISON_V2.json)",
        "- [독립 saved 검증](../broad_v2/SAVED_RESULTS_INDEPENDENT_ARITHMETIC_V2.json)",
        "- [실제 candle 비교 — 간격 보정 표시본](anatomy_binding_repair/readable/)",
        "- [실제 fresh 시각·호가·원장 증거](FRESH_CLOCK_RUNTIME_WITNESS_V3.json)",
        "- [공통 fresh 고정](FRESH_FORWARD_FREEZE_V2.json)",
        "- [실제 호가 paper 후속 구간 고정](OBSERVED_PAPER_FREEZE_V3.json)",
        "",
        "Core/order/live 승격 없음. 프런트엔드 배포 불필요. Rollback은 해당 Scalp7 연구 service만 중지하고 기존 원장·freeze를 보존한다.",
    ]
    (REPORT / "SCALP7_BROAD_REBUILD_V2_FINAL_REPORT.md").write_text(
        "\n".join(lead) + "\n"
    )
    (REPORT / "FINAL_ASSESSMENT_V2.json").write_text(
        json.dumps(
            {
                "as_of_utc": now.isoformat(),
                "source_comparison_sha256": hashlib.sha256(
                    (REPORT / "FINAL_COMPARISON_V2.json").read_bytes()
                ).hexdigest(),
                "fresh_state_sha256": (
                    hashlib.sha256(paper_bytes).hexdigest()
                    if paper_path.exists()
                    else None
                ),
                "fresh_closed_by_identity": dict(fresh),
                "fresh_state_path": str(paper_path),
                "fresh_execution_profile": "POST_DECISION_OBSERVED_QUOTE_ACTUAL_CLOCK_BARRIER_V3",
                "fresh_common_start_utc": "2026-09-15T21:00:00Z",
                "original_v2_closed_trades": 0,
                "material_assessment": assessment,
                "strict_joint_improvements": data["strict_joint_improvement_count"],
                "profitable_seven_lane_system_established": False,
                "C_to_B": 0,
                "BxB_allowed": False,
                "order_authority": "BLOCKED",
                "live_authority": "BLOCKED",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "report": str(REPORT / "SCALP7_BROAD_REBUILD_V2_FINAL_REPORT.md"),
                "rows": len(rows),
                "material_rows": len(material_rows),
                "fresh_closed": dict(fresh),
            }
        )
    )


if __name__ == "__main__":
    main()
