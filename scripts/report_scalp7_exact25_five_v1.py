#!/usr/bin/env python3
"""Report completed saved results only; never import models, loaders, or runners."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
compare_matched = importlib.import_module(
    "backend.research.rebuild.scalp7_exact25_model_comparison_v1"
).compare_matched

LABELS = ("ST_CONTROL", "ST_TRAIL", "SR_CONTROL", "SR_RETEST", "NOISE_BASELINE")
REQUEST = (
    ROOT
    / "research/campaigns/scalp7_20260920/model_closure_v1/PREPARED_EXECUTION_REQUEST.json"
)
SCOPE = "G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1"
DAY = 86_400_000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def display_path(path):
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def read_result(directory, row):
    paths = [directory / (row["label"] + suffix) for suffix in (".json", ".json.gz")]
    existing = [path for path in paths if path.is_file()]
    if not existing:
        return None, None
    payloads = []
    for path in existing:
        stored = path.read_bytes()
        raw = gzip.decompress(stored) if path.suffix == ".gz" else stored
        payloads.append((path, raw, sha(stored)))
    if len({sha(raw) for _, raw, _ in payloads}) != 1:
        raise ValueError("CONFLICTING_SAVED_RESULTS:" + row["label"])
    path, raw, storage_hash = payloads[-1]
    result = json.loads(raw)
    if result["identity_key"] != row["identity"]:
        raise ValueError("RESULT_IDENTITY_MISMATCH:" + row["label"])
    if result["binding_sha256"] != row["binding_sha256"]:
        raise ValueError("RESULT_BINDING_MISMATCH:" + row["label"])
    if (
        result.get("data_kind") != "GENUINE_RAW_HISTORY"
        or result.get("full_execution_performed") is not True
    ):
        raise ValueError("COMPLETED_GENUINE_RESULT_REQUIRED:" + row["label"])
    meta = {
        "source_file": display_path(path),
        "source_file_sha256": sha(raw),
        "source_storage_sha256": storage_hash,
        "source_storage_bytes": path.stat().st_size,
        "source_uncompressed_bytes": len(raw),
    }
    return result, meta


def comparison_input(directory, row):
    """Retain only comparator fields; discard large account curves immediately."""
    result, _ = read_result(directory, row)
    return {
        "identity_key": result["identity_key"],
        "binding_sha256": result["binding_sha256"],
        "authority": result["authority"],
        "execution": {
            "executions": [
                {"order": execution.get("order")}
                for execution in result["execution"]["executions"]
            ]
        },
        "cost_scenarios": {
            scenario: {
                "windows": result["cost_scenarios"][scenario]["windows"],
                "episodes": result["cost_scenarios"][scenario]["episodes"],
            }
            for scenario in ("1x", "2x")
        },
    }


def utc(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("NUMERIC_VALUATION_REQUIRED")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("FINITE_VALUATION_REQUIRED")
    return value


def curve_interval(curve, initial_cash, start, end):
    prior = [point for point in curve if point["ts_ms"] < start]
    points = [point for point in curve if start <= point["ts_ms"] < end]
    if not points:
        return None
    baseline = numeric(prior[-1]["equity_usdt"]) if prior else numeric(initial_cash)
    peak, dd = baseline, 0.0
    for point in points:
        equity = numeric(point["equity_usdt"])
        peak = max(peak, equity)
        if peak > 0:
            dd = max(dd, 100 * (peak - equity) / peak)
    return {
        "sample_count": len(points),
        "first_sample_ts_ms": points[0]["ts_ms"],
        "last_sample_ts_ms": points[-1]["ts_ms"],
        "initial_interval_equity_usdt": baseline,
        "last_sample_equity_usdt": numeric(points[-1]["equity_usdt"]),
        "sampled_DD_pct": dd,
    }


def curve_summary(result, scenario, binding):
    saved = result["cost_scenarios"][scenario]
    account = saved.get("account")
    curve = account["valuation"]["curve"] if account else []
    if any(a["ts_ms"] >= b["ts_ms"] for a, b in zip(curve, curve[1:])):
        raise ValueError("SAVED_CURVE_NOT_STRICTLY_CHRONOLOGICAL")
    first, last = (
        binding["windows"][0]["start_ts_ms"],
        binding["windows"][-1]["end_ts_ms"],
    )
    # Whole-account valuation includes the terminal snapshot at the frozen end.
    measured = (
        curve_interval(
            curve, binding["initial_cash_usdt"], first, curve[-1]["ts_ms"] + 1
        )
        if curve
        else None
    )
    saved_dd = numeric(account["valuation"]["max_drawdown_pct"]) if account else None
    if measured and not math.isclose(
        measured["sampled_DD_pct"], saved_dd, rel_tol=1e-10, abs_tol=1e-10
    ):
        raise ValueError("SAVED_ACCOUNT_DD_CURVE_MISMATCH")
    full = (
        bool(measured)
        and result["unknown_execution_count"] == 0
        and "PREFIX_ONLY" not in saved["account_status"]
        and curve[-1]["ts_ms"] >= last
    )
    return {
        "account_status": saved["account_status"],
        "source_json_pointer": "/cost_scenarios/"
        + scenario
        + "/account/valuation/curve",
        "saved_DD_json_pointer": "/cost_scenarios/"
        + scenario
        + "/account/valuation/max_drawdown_pct",
        "terminal_sample_included": bool(curve) and curve[-1]["ts_ms"] >= last,
        "valuation_basis": "SAVED_SAMPLED_LAST_PRICE_NAV_REFERENCE_COST_EXCLUDING_FUNDING",
        "full_sampled_DD_pct": saved_dd if full else None,
        "prefix_sampled_DD_pct": saved_dd if measured and not full else None,
        "full_period_available": full,
        "sample_summary": measured,
        "not_trade_sum_DD": True,
    }


def aggregate_resolved(episodes):
    ordered = sorted(episodes, key=lambda row: row["outcome_available_ts_ms"])
    nets = [numeric(row["net_reference_usdt"]) for row in ordered]
    gains = sum(x for x in nets if x > 0)
    losses = -sum(x for x in nets if x < 0)
    streak = maximum = 0
    for value in nets:
        streak = streak + 1 if value < 0 else 0
        maximum = max(maximum, streak)
    return {
        "T_resolved": len(nets),
        "WR_resolved_pct": (
            100 * sum(value > 0 for value in nets) / len(nets) if nets else None
        ),
        "gross_resolved_usdt": sum(numeric(row["gross_usdt"]) for row in ordered),
        "cost_resolved_usdt": sum(numeric(row["cost_usdt"]) for row in ordered),
        "net_resolved_reference_usdt": sum(nets),
        "net_per_trade_resolved_reference_usdt": (
            sum(nets) / len(nets) if nets else None
        ),
        "PF_resolved_reference": gains / losses if losses else None,
        "PF_no_losses": bool(nets) and losses == 0,
        "MaxLS_resolved": maximum if nets else None,
    }


def pooled_rolling(result, scenario, binding):
    saved = result["cost_scenarios"][scenario]
    windows = [window for window in binding["windows"] if window["kind"] == "ROLLING"]
    start, end = windows[0]["start_ts_ms"], windows[-1]["end_ts_ms"]
    if len(windows) != 9 or any(
        a["end_ts_ms"] != b["start_ts_ms"] for a, b in zip(windows, windows[1:])
    ):
        raise ValueError("FROZEN_NINE_CONTIGUOUS_ROLLING_WINDOWS_REQUIRED")
    episodes = saved["episodes"]
    closed = [
        row
        for row in episodes
        if start <= row["entry_ts_ms"] < end
        and row["closed"]
        and row["outcome_available_ts_ms"] < end
    ]
    crossing = [
        row
        for row in episodes
        if start <= row["entry_ts_ms"] < end
        and (not row["closed"] or row["outcome_available_ts_ms"] >= end)
    ]
    carried = [
        row
        for row in episodes
        if row["entry_ts_ms"] < start
        and (not row["closed"] or row["outcome_available_ts_ms"] >= start)
    ]
    later_window_outcomes = []
    for row in closed:
        entry_window = next(
            window
            for window in windows
            if window["start_ts_ms"] <= row["entry_ts_ms"] < window["end_ts_ms"]
        )
        if row["outcome_available_ts_ms"] >= entry_window["end_ts_ms"]:
            later_window_outcomes.append(row)
    unknown = [
        row
        for row in result["execution"]["executions"]
        if row.get("state", row.get("status")) == "UNRESOLVED"
        or row.get("unresolved") is True
    ]
    affected = [row for row in unknown if row.get("unresolved_from_ts_ms", 0) < end]
    complete = not (crossing or carried or affected)
    metrics = aggregate_resolved(closed)
    account = saved.get("account")
    curve = account["valuation"]["curve"] if account else []
    measured = curve_interval(curve, binding["initial_cash_usdt"], start, end)
    full_curve = complete and result["unknown_execution_count"] == 0 and bool(measured)
    return {
        "name": "rolling_245d_retrospective_resolved_cohort",
        "kind": "DESCRIPTIVE_POOLED_ROLLING_NOT_AN_EXTRA_EXECUTION",
        "start_ts_ms": start,
        "end_ts_ms": end,
        "calendar_days": (end - start) / DAY,
        "T_per_day_resolved": metrics["T_resolved"] / ((end - start) / DAY),
        **metrics,
        "cross_boundary_or_open_count": len(crossing),
        "carry_in_count": len(carried),
        "affected_unknown_execution_count": len(affected),
        "complete_window": complete,
        "net_complete_reference_usdt": (
            metrics["net_resolved_reference_usdt"] if complete else None
        ),
        "actual_historical_net_usdt": None,
        "funding_status": "UNKNOWN_NOT_ZERO",
        "DD_pct": measured["sampled_DD_pct"] if full_curve else None,
        "DD_status": (
            "SAVED_SAMPLED_ACCOUNT_CURVE" if full_curve else "FULL_PERIOD_UNAVAILABLE"
        ),
        "prefix_sampled_account_DD_pct": (
            measured["sampled_DD_pct"] if measured and not full_curve else None
        ),
        "prefix_sample_last_ts_ms": (
            measured["last_sample_ts_ms"] if measured and not full_curve else None
        ),
        "later_window_resolved_episode_count": len(later_window_outcomes),
        "later_window_resolved_episode_ids": [
            row["episode_id"] for row in later_window_outcomes
        ],
        "sum_saved_rolling_window_T_resolved": sum(
            window["T_resolved"]
            for window in saved["windows"]
            if window["kind"] == "ROLLING"
        ),
        "cohort_warning": "Includes trades whose entry-window end precedes outcome availability; not as-of-window OOS, not sum of nine window reports, not a tuning input.",
        "incomplete_resolved_subset_is_not_total_performance": not complete,
    }


def quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    offset = (len(ordered) - 1) * q
    lo, hi = math.floor(offset), math.ceil(offset)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (offset - lo)


def distribution(episodes, nets, axis):
    grouped = {}
    total_positive = sum(max(0.0, net) for net in nets)
    for row, net in zip(episodes, nets):
        if axis == "month":
            label = datetime.fromtimestamp(
                row["outcome_available_ts_ms"] / 1000, timezone.utc
            ).strftime("%Y-%m")
        elif axis == "session":
            hour = datetime.fromtimestamp(row["entry_ts_ms"] / 1000, timezone.utc).hour
            label = ("UTC_00_08", "UTC_08_16", "UTC_16_24")[hour // 8]
        else:
            label = str(row["symbol"])
        group = grouped.setdefault(
            label,
            {"T": 0, "net_reference_usdt": 0.0, "positive_trade_profit_usdt": 0.0},
        )
        group["T"] += 1
        group["net_reference_usdt"] += net
        group["positive_trade_profit_usdt"] += max(0.0, net)
    for group in grouped.values():
        group["trade_count_share_pct"] = 100 * group["T"] / len(episodes)
        group["positive_profit_share_pct"] = (
            100 * group["positive_trade_profit_usdt"] / total_positive
            if total_positive
            else None
        )
    return {
        "groups": grouped,
        "largest_trade_count_share_pct": max(
            (group["trade_count_share_pct"] for group in grouped.values()), default=None
        ),
        "largest_positive_profit_share_pct": max(
            (
                group["positive_profit_share_pct"]
                for group in grouped.values()
                if group["positive_profit_share_pct"] is not None
            ),
            default=None,
        ),
        "profit_share_denominator": "SUM_OF_POSITIVE_NET_TRADES_USDT_NEGATIVE_GROUPS_PRESERVED",
    }


def risk_cohort(episodes, window):
    start, end = window["start_ts_ms"], window["end_ts_ms"]
    selected = [
        row
        for row in episodes
        if start <= row["entry_ts_ms"] < end
        and row["closed"]
        and row["outcome_available_ts_ms"] < end
    ]
    nets = [numeric(row["net_reference_usdt"]) for row in selected]
    losses = sorted(value for value in nets if value < 0)
    holds = [(row["exit_ts_ms"] - row["entry_ts_ms"]) / 60_000 for row in selected]
    if any(value < 0 for value in holds):
        raise ValueError("NEGATIVE_SAVED_HOLD_DURATION")
    losing_count, all_count = math.ceil(len(losses) * 0.05), math.ceil(len(nets) * 0.05)
    positive_sum = sum(value for value in nets if value > 0)
    return {
        "name": window["name"],
        "start_ts_ms": start,
        "end_ts_ms": end,
        "complete_window": window["complete_window"],
        "resolved_cohort_only": True,
        "T_resolved": len(selected),
        "T_per_day_resolved": len(selected) / ((end - start) / DAY),
        "loss_tail": {
            "worst_trade_usdt": min(nets) if nets else None,
            "worst_5pct_losing_trades_mean_usdt": (
                sum(losses[:losing_count]) / losing_count if losing_count else None
            ),
            "worst_5pct_losing_trade_count": losing_count,
            "expected_shortfall_5pct_all_trades_usdt": (
                sum(sorted(nets)[:all_count]) / all_count if all_count else None
            ),
            "all_trade_tail_count": all_count,
        },
        "hold_mean_min": sum(holds) / len(holds) if holds else None,
        "hold_median_min": quantile(holds, 0.5),
        "hold_p95_min": quantile(holds, 0.95),
        "largest_winner_contribution_pct": (
            100 * max(nets) / positive_sum if positive_sum else None
        ),
        "concentration": {
            axis: distribution(selected, nets, axis)
            for axis in ("month", "symbol", "session")
        },
    }


def descriptive_risk(result, scenario, pooled):
    saved = result["cost_scenarios"][scenario]
    return {
        "windows": [
            risk_cohort(saved["episodes"], window) for window in saved["windows"]
        ],
        "pooled_rolling": risk_cohort(saved["episodes"], pooled),
    }


def summarize_result(result, meta, row, binding):
    if (
        binding["identity_key"] != row["identity"]
        or binding["binding_sha256"] != row["binding_sha256"]
    ):
        raise ValueError("FROZEN_REQUEST_BINDING_MISMATCH")
    expected = [
        window
        for window in binding["windows"]
        if window["kind"] not in {"CONTEXT", "TRAIN"}
    ]
    for scenario in ("1x", "2x"):
        observed = result["cost_scenarios"][scenario]["windows"]
        if len(observed) != len(expected):
            raise ValueError("SAVED_WINDOW_COUNT_MISMATCH")
        for actual, frozen in zip(observed, expected):
            if any(
                actual[key] != frozen[key]
                for key in ("name", "kind", "start_ts_ms", "end_ts_ms")
            ):
                raise ValueError("SAVED_WINDOW_BOUNDARY_MISMATCH")
    unknown = [
        row
        for row in result["execution"]["executions"]
        if row.get("state", row.get("status")) == "UNRESOLVED"
        or row.get("unresolved") is True
    ]
    pooled = {
        scenario: pooled_rolling(result, scenario, binding) for scenario in ("1x", "2x")
    }
    return {
        **meta,
        "identity_key": result["identity_key"],
        "binding_sha256": result["binding_sha256"],
        "freeze_path": row["freeze_path"],
        "model_id": row["model_id"],
        "data_kind": result["data_kind"],
        "full_execution_performed": result["full_execution_performed"],
        "unknown_execution_count": result["unknown_execution_count"],
        "unknown_execution_evidence": [
            {
                key: item[key]
                for key in (
                    "state",
                    "status",
                    "reason",
                    "events",
                    "unresolved_from_ts_ms",
                    "unresolved_observed_ts_ms",
                )
                if key in item
            }
            for item in unknown
        ],
        "saved_windows": {
            scenario: copy.deepcopy(result["cost_scenarios"][scenario]["windows"])
            for scenario in ("1x", "2x")
        },
        "pooled_rolling_resolved": pooled,
        "descriptive_risk": {
            scenario: descriptive_risk(result, scenario, pooled[scenario])
            for scenario in ("1x", "2x")
        },
        "account_curve_summary": {
            scenario: curve_summary(result, scenario, binding)
            for scenario in ("1x", "2x")
        },
        "noise_independent_baseline_not_gmma_child": row["label"] == "NOISE_BASELINE",
        "fresh_T": result["fresh_T"],
    }


def fmt(value, digits=3):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def economic_row(label, scenario, row):
    fields = (
        "T_resolved",
        "T_per_day_resolved",
        "WR_resolved_pct",
        "gross_resolved_usdt",
        "net_resolved_reference_usdt",
        "net_per_trade_resolved_reference_usdt",
        "PF_resolved_reference",
        "DD_pct",
        "MaxLS_resolved",
        "cross_boundary_or_open_count",
        "carry_in_count",
        "complete_window",
    )
    return (
        "| " + " | ".join([label, scenario] + [fmt(row[key]) for key in fields]) + " |"
    )


def table_header():
    return [
        "| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]


def concentration_cell(distribution_row, field):
    value = distribution_row[field]
    if value is None:
        return "null"
    group_field = (
        "positive_profit_share_pct"
        if field == "largest_positive_profit_share_pct"
        else "trade_count_share_pct"
    )
    labels = sorted(
        label
        for label, group in distribution_row["groups"].items()
        if group[group_field] == value
    )
    return ",".join(labels) + " " + fmt(value) + "%"


def risk_markdown(report):
    lines = [
        "",
        "## 확인된 종료 거래의 tail·hold·집중도",
        "",
        "각 값은 해당 비용 시나리오의 결과 확인 종료 거래만 사용한다. 미해결·미종료 거래는 포함하지 않으므로 불완결 구간의 전체 위험으로 해석하지 않는다. 1x/2x는 체결·보유시간이 같고 비용 차이에 따라 손실·승리 분류와 이익 기여도가 달라진다.",
        "정의: 최악 거래=min(Net). 손실 tail=음수 거래 중 가장 나쁜 ceil(5%) 평균. ES5=모든 거래 중 가장 나쁜 ceil(5%) 평균. hold는 (실제 종료시각−진입시각)/분이며 p95는 (n−1)×0.95 위치의 선형보간이다. T/day는 달력 일수 기준이다. 통계 정의는 기존 scalp7_metrics_v2를 따르되 이번 단위는 USDT이며 이번 동결 진입시각 코호트를 사용한다.",
        "집중도는 개별 양수 Net의 합을 분모로 사용하며 음수 집단도 JSON에 보존한다. 월은 결과 확인 시각 UTC, 세션은 진입 UTC의 00–08/08–16/16–24시 구분이다. 아래는 validation과 rolling 사후 합산이며 9개 원래 창의 세부 통계·모든 그룹은 ECONOMIC_COMPARISON.json의 descriptive_risk에 있다.",
        "",
        "| Identity | 구간 | 비용 | 완결 | T/day | 최악 Net USDT | 손실 tail5 USDT | ES5 USDT | 평균 hold 분 | 중앙 hold 분 | p95 hold 분 | 최대승리 이익기여 % |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = []
    for label, item in report["results"].items():
        for scenario in ("1x", "2x"):
            saved = item["descriptive_risk"][scenario]
            for row in [w for w in saved["windows"] if w["name"] == "validation"] + [
                saved["pooled_rolling"]
            ]:
                period = (
                    "validation30d"
                    if row["name"] == "validation"
                    else "rolling245d 사후합산"
                )
                rows.append((label, period, scenario, row))
                values = [
                    label,
                    period,
                    scenario,
                    fmt(row["complete_window"]),
                    fmt(row["T_per_day_resolved"]),
                    fmt(row["loss_tail"]["worst_trade_usdt"]),
                    fmt(row["loss_tail"]["worst_5pct_losing_trades_mean_usdt"]),
                    fmt(row["loss_tail"]["expected_shortfall_5pct_all_trades_usdt"]),
                    fmt(row["hold_mean_min"]),
                    fmt(row["hold_median_min"]),
                    fmt(row["hold_p95_min"]),
                    fmt(row["largest_winner_contribution_pct"]),
                ]
                lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "| Identity | 구간 | 비용 | 최대 심볼 이익기여 | 최대 월 이익기여 | 최대 세션 이익기여 | 최대 심볼 거래비중 |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, period, scenario, row in rows:
        conc = row["concentration"]
        values = (
            [label, period, scenario]
            + [
                concentration_cell(conc[axis], "largest_positive_profit_share_pct")
                for axis in ("symbol", "month", "session")
            ]
            + [concentration_cell(conc["symbol"], "largest_trade_count_share_pct")]
        )
        lines.append("| " + " | ".join(values) + " |")
    return lines


def markdown(report, attestation=None):
    display_status = (
        "저장 결과 독립 검산 완료 (경제 JSON 원본 보존)"
        if attestation
        else report["report_status"]
    )
    display_audit = "PASS" if attestation else report["audit_status"]
    lines = [
        "# 동결 5개 identity: 저장된 경제검증 결과",
        "",
        "- 결과 상태: " + display_status + ". 독립 검산: " + display_audit + ".",
        "- 저장 결과 확보: "
        + str(report["results_count"])
        + "/5; 미확보: "
        + (", ".join(report["missing_results"]) or "none")
        + ".",
        "- 펀딩 제외 연구 손익이며 단위는 USDT다. 펀딩은 미확인이고 0으로 간주하지 않는다. 과거 OHLC 체결모형과 기준 비용을 적용한 결과로, 실제 계좌 실현손익이 아니다.",
        "- 비용 2x는 동일 체결·수량의 비용 재평가이며 추가 FULL 실행이 아니다. Gross·Net·Net/T의 단위는 USDT이므로 이전 일부 캠페인의 bps 값과 직접 혼용하지 않는다.",
        "- T·WR·Gross·Net·Net/T·PF·MaxLS는 결과가 확인된 종료 거래만 집계한다. 완결=no이면 일부 확인 거래의 성과이고 전체 성과는 확정하지 않는다. null은 미확인·산출 불가 상태를 보존한다.",
        "- DD는 저장된 last-price 계좌 평가곡선의 표본에서 산출한다. 거래 손익 누적합으로 대체하지 않는다. 초반 일부 곡선만 있으면 전체 DD는 null이고 해당 구간 DD를 따로 표시한다.",
        "- 이미 검토된 개발용 과거자료이며 fresh T=0이다. 원래 25개와 미완료 19개를 보존한다. 이번 배치 완료는 원래 25개 또는 G4 전체 완료가 아니다.",
        "- NOISE_BASELINE은 독립 대조군이다. GMMA/TrendRider 부모 대비 개선으로 해석하지 않는다. 주문·LIVE·공식 승격은 계속 차단한다.",
        "",
        "## Validation 30일",
        "",
    ]
    if attestation:
        lines[3:3] = [
            "- 독립 감사: "
            + attestation["audit_file"]
            + "; 경제 JSON SHA256="
            + attestation["economic_comparison_sha256"]
            + "; 감사 SHA256="
            + attestation["audit_file_sha256"]
            + ".",
            "- 경제 JSON의 PENDING 표시는 검산 전 생성단계를 보존한 값이다. 동일 JSON 해시에 결속된 별도 독립 감사 PASS를 확인한 뒤 이 문서만 갱신했다. 미확보 결과는 계속 미완료다.",
        ]
    lines += table_header()
    for label, item in report["results"].items():
        for scenario in ("1x", "2x"):
            for row in item["saved_windows"][scenario]:
                if row["kind"] == "VALIDATION":
                    lines.append(economic_row(label, scenario, row))
    lines += [
        "",
        "## Rolling 245일: 종료 결과를 사후 확인한 진입 거래 집합",
        "",
        "이 합산에는 진입한 창의 종료 시점에는 열려 있었고 이후 창에서 종료된 거래도 포함된다. 각 창 종료 시점에 알 수 있던 OOS 성과나 9개 창의 단순 합계로 해석하지 않는다. 경계 통과·미종료 거래와 미해결 실행은 별도 보존하고 결측 결과를 0으로 바꾸지 않는다.",
        "",
    ]
    lines += table_header()
    for label, item in report["results"].items():
        for scenario in ("1x", "2x"):
            lines.append(
                economic_row(label, scenario, item["pooled_rolling_resolved"][scenario])
            )
    lines += [
        "",
        "| Identity | 비용 | 이후 창 종료 포함 | 9개 창 T 합계 | 사후 합산 T | 미해결 실행 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for label, item in report["results"].items():
        for scenario in ("1x", "2x"):
            row = item["pooled_rolling_resolved"][scenario]
            lines.append(
                f"| {label} | {scenario} | {row['later_window_resolved_episode_count']} | {row['sum_saved_rolling_window_T_resolved']} | {row['T_resolved']} | {row['affected_unknown_execution_count']} |"
            )
    lines += ["", "## 원래 동결된 Rolling 9개 창", ""]
    first = next(iter(report["results"].values()), None)
    if first:
        for window in [
            row for row in first["saved_windows"]["1x"] if row["kind"] == "ROLLING"
        ]:
            lines += [
                "",
                "### "
                + window["name"]
                + ": "
                + utc(window["start_ts_ms"])
                + " to "
                + utc(window["end_ts_ms"])
                + " (종료 시각 제외)",
                "",
            ]
            lines += table_header()
            for label, item in report["results"].items():
                for scenario in ("1x", "2x"):
                    row = next(
                        row
                        for row in item["saved_windows"][scenario]
                        if row["name"] == window["name"]
                    )
                    lines.append(economic_row(label, scenario, row))
    lines += risk_markdown(report)
    lines += [
        "",
        "## 저장된 계좌 평가곡선의 DD",
        "",
        "| Identity | 비용 | 전체 DD % | 확인된 초반 구간 DD % | 마지막 평가 시각 UTC | 평가 표본 수 |",
        "|---|---|---:|---:|---|---:|",
    ]
    for label, item in report["results"].items():
        for scenario in ("1x", "2x"):
            row = item["account_curve_summary"][scenario]
            sample = row["sample_summary"]
            lines.append(
                f"| {label} | {scenario} | {fmt(row['full_sampled_DD_pct'])} | {fmt(row['prefix_sampled_DD_pct'])} | {utc(sample['last_sample_ts_ms']) if sample else 'null'} | {sample['sample_count'] if sample else 0} |"
            )
    lines += [
        "",
        "## 동결된 대조군 비교와 승리 훼손",
        "",
        "승리 훼손은 부모·자식이 모두 완결된 원래 창에서만 계산한다. 이익 보존율에는 자식의 양수 이익만 들어가므로 손실 전환·진입 부재도 함께 표시한다. SR은 고정 일별 기준을 공유하는 셋업으로 대응하며 진입 시각이 같다는 뜻은 아니다. 불완결 창의 합산 승리 훼손은 산출하지 않는다.",
        "",
        "| 비교 | 비용 | 창 | 완결 | ΔT | ΔWR %p | ΔNet USDT | ΔDD %p | 부모 승리 | 자식 양수·음수·부재 | 승리집합 ΔNet USDT | 양수 이익 보존 % |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for pair, comparison in report["matched_comparisons"].items():
        for scenario, windows in comparison["cost_scenarios"].items():
            for row in windows:
                metrics, damage = row["metrics"], row["winner_damage"]
                counts = (
                    "/".join(
                        str(damage[key])
                        for key in (
                            "child_positive_same_setup",
                            "child_negative_same_setup",
                            "child_absent_same_setup",
                        )
                    )
                    if damage
                    else "null"
                )
                values = [
                    pair,
                    scenario,
                    row["name"],
                    fmt(row["complete_pair_window"]),
                    fmt(metrics["T_resolved"]["delta"]),
                    fmt(metrics["WR_resolved_pct"]["delta"]),
                    fmt(metrics["net_resolved_reference_usdt"]["delta"]),
                    fmt(metrics["DD_pct"]["delta"]),
                    str(damage["parent_winners"]) if damage else "null",
                    counts,
                    fmt(damage["winner_net_delta_usdt"]) if damage else "null",
                    (
                        fmt(damage["positive_winner_profit_retention_pct"])
                        if damage
                        else "null"
                    ),
                ]
                lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "## 저장 근거",
        "",
        "| Identity | 원본 JSON SHA256 | 저장 파일 |",
        "|---|---|---|",
    ]
    for label, item in report["results"].items():
        lines.append(
            f"| {label} | {item['source_file_sha256']} | {item['source_file']} |"
        )
    return "\n".join(lines) + "\n"


def render_attested(output, audit_path):
    comparison_path = output / "ECONOMIC_COMPARISON.json"
    report_bytes = comparison_path.read_bytes()
    report = json.loads(report_bytes)
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)
    expected_sources = {
        label: row["source_file_sha256"] for label, row in report["results"].items()
    }
    if (
        audit.get("scope_key") != SCOPE
        or report.get("scope_key") != SCOPE
        or audit.get("status") != "PASS"
        or audit.get("error_count") != 0
        or audit.get("errors") != []
        or audit.get("check_count", 0) <= 0
        or audit.get("economic_comparison_sha256") != sha(report_bytes)
        or audit.get("source_result_sha256") != expected_sources
        or audit.get("completed_saved_results") != report["completed_saved_results"]
        or audit.get("missing_results") != report["missing_results"]
    ):
        raise ValueError("MATCHING_INDEPENDENT_ECONOMIC_AUDIT_PASS_REQUIRED")
    attestation = {
        "audit_file": display_path(audit_path),
        "audit_file_sha256": sha(audit_bytes),
        "economic_comparison_sha256": sha(report_bytes),
    }
    (output / "ECONOMIC_REPORT.md").write_text(markdown(report, attestation))
    if comparison_path.read_bytes() != report_bytes:
        raise ValueError("ECONOMIC_COMPARISON_CHANGED_DURING_ATTESTATION")
    print(
        json.dumps(
            {
                "markdown_audit_status": "PASS",
                "results_count": report["results_count"],
                "economic_json_unchanged": True,
                **attestation,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--attest-audit",
        type=Path,
        help="Verify matching independent PASS and update Markdown only; never change economic JSON.",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Report only atomically completed JSON files; never open .partial files.",
    )
    args = parser.parse_args()
    if args.attest_audit:
        render_attested(args.output, args.attest_audit)
        return
    if args.results is None:
        parser.error("--results is required unless --attest-audit is used")
    request = json.loads(REQUEST.read_text())
    rows = {row["label"]: row for row in request["identities"]}
    if tuple(rows) != LABELS:
        raise ValueError("EXACT_FIVE_FROZEN_IDENTITIES_REQUIRED")
    report = {
        "schema": "scalp7.exact25.five_report.v1",
        "scope_key": SCOPE,
        "audit_status": "PENDING_INDEPENDENT_AUDIT",
        "authorized_identity_total": 5,
        "additional_full_runs_by_report": 0,
        "original25_complete": False,
        "original25_total": 25,
        "remaining19_preserved": True,
        "g4_complete": False,
        "funding_status": "UNKNOWN_NOT_ZERO",
        "actual_historical_net_usdt": None,
        "formal_promotion": "BLOCKED",
        "authority": {"live": "BLOCKED", "order": "BLOCKED", "promotion": False},
        "descriptive_risk_definitions": {
            "statistical_method_source": "backend/research/rebuild/scalp7_metrics_v2.py",
            "statistical_method_source_sha256": sha(
                (ROOT / "backend/research/rebuild/scalp7_metrics_v2.py").read_bytes()
            ),
            "cohort": "SAVED_RESOLVED_CLOSED_EPISODES_ENTRY_IN_WINDOW_OUTCOME_BEFORE_END",
            "tail": "WORST_TRADE_MIN_NET; LOSING_TAIL_MEAN_WORST_CEIL_5PCT_NEGATIVE_TRADES; ALL_TRADE_ES_MEAN_WORST_CEIL_5PCT_ALL_TRADES",
            "hold": "EXIT_TS_MINUS_ENTRY_TS_MINUTES; P50_P95_LINEAR_INTERPOLATION_AT_N_MINUS_ONE_TIMES_Q",
            "concentration": "SYMBOL; OUTCOME_AVAILABLE_UTC_MONTH; ENTRY_UTC_8H_SESSION; POSITIVE_PROFIT_SHARE_DENOMINATOR_SUM_POSITIVE_NET",
            "units": "NET_AND_TAIL_USDT; HOLD_MINUTES; SHARES_PERCENT",
            "not_full_incomplete_risk": True,
            "cost_2x_uses_identical_fills_and_holds": True,
        },
        "units": {
            "gross": "USDT",
            "net": "USDT",
            "net_per_trade": "USDT/trade",
            "DD": "percent",
            "WR": "percent",
            "T": "resolved_closed_trades",
        },
        "limitations": [
            "Funding excluded; unknown not zero.",
            "Historical OHLC model fills and reference costs; not realized performance.",
            "Already inspected development history; no genuine fresh forward observations.",
            "Resolved subsets do not establish incomplete total performance.",
            "Pooled rolling includes later-window outcomes; not as-of-window OOS.",
            "Sampled last-price DD is not intrabar or mark-price liquidation risk.",
            "Noise is independent, not a matched GMMA child.",
            "This five-run batch does not complete original 25 or G4.",
        ],
        "results": {},
        "matched_comparisons": {},
        "missing_results": [],
    }
    for label in LABELS:
        row = rows[label]
        result, meta = read_result(args.results, row)
        if result is None:
            report["missing_results"].append(label)
            continue
        binding = json.loads((ROOT / row["freeze_path"]).read_text())
        report["results"][label] = summarize_result(result, meta, row, binding)
        del result
    if report["missing_results"] and not args.partial:
        raise ValueError(
            "MISSING_COMPLETED_RESULTS:" + ",".join(report["missing_results"])
        )
    for pair in request["matched_pairs"]:
        if (
            pair["parent"] not in report["results"]
            or pair["child"] not in report["results"]
        ):
            continue
        parent = comparison_input(args.results, rows[pair["parent"]])
        child = comparison_input(args.results, rows[pair["child"]])
        pb = json.loads((ROOT / rows[pair["parent"]]["freeze_path"]).read_text())
        cb = json.loads((ROOT / rows[pair["child"]]["freeze_path"]).read_text())
        comparison = compare_matched(parent, child, pb, cb, axis=pair["axis"])
        report["matched_comparisons"][
            pair["parent"] + "_vs_" + pair["child"]
        ] = comparison
        del parent, child
    report["completed_saved_results"] = list(report["results"])
    report["results_count"] = len(report["results"])
    report["report_status"] = (
        "PARTIAL_SAVED_RESULTS_PENDING_INDEPENDENT_AUDIT"
        if report["missing_results"]
        else "SAVED_RESULTS_COLLECTED_PENDING_INDEPENDENT_AUDIT"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ECONOMIC_COMPARISON.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (args.output / "ECONOMIC_REPORT.md").write_text(markdown(report))
    print(
        json.dumps(
            {
                "results_count": report["results_count"],
                "missing": report["missing_results"],
                "audit_status": report["audit_status"],
                "output": display_path(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
