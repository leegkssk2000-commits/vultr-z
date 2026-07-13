from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SEVERITY_RANK = {None: 0, "m": 1, "M": 2, "C": 3}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def issue(code: str, severity: str, detail: str, metric: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail, "metric": metric}


def read_ledger_snapshot(path: Path) -> tuple[list[dict[str, Any]], str, list[dict[str, str]]]:
    if not path.exists():
        return [], "", [issue("LEDGER_MISSING", "C", str(path), "ledger_exists")]
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        return [], digest, [issue("LEDGER_ENCODING_INVALID", "C", str(exc), "ledger_integrity")]
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(issue("LEDGER_JSON_MALFORMED", "C", f"line={line_no}:{exc.msg}", "ledger_integrity"))
            continue
        if not isinstance(row, dict):
            problems.append(issue("LEDGER_ROW_NOT_OBJECT", "C", f"line={line_no}", "ledger_integrity"))
            continue
        rows.append(row)
    return rows, digest, problems


def feature_is_valid(key: str, value: Any, feature: Mapping[str, Any], allowed: Mapping[str, Any]) -> bool:
    if key == "observer_only":
        return value is True
    if key in {"htf_bias", "swing_sequence", "premium_discount_side", "session_window"}:
        options = allowed.get(key)
        return isinstance(value, str) and isinstance(options, list) and value in options
    if key == "dealing_range_position":
        number = finite_number(value)
        return number is not None and 0.0 <= number <= 1.0
    if key == "ote_depth":
        number = finite_number(value)
        return value is None or (number is not None and 0.0 <= number <= 1.0)
    if key in {"ote_0_5_0_79", "ltf_reversal_confirm"}:
        return isinstance(value, bool)
    if key == "invalidation_swing_price":
        number = finite_number(value)
        return number is not None and number > 0.0
    if key == "invalidation_swing_distance_pct":
        number = finite_number(value)
        return number is not None and number >= 0.0
    return key in feature


def validate_feature_payload(
    phase: str,
    feature: Mapping[str, Any],
    loc: str,
    required: Sequence[str],
    allowed: Mapping[str, Any],
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    for key in required:
        if key not in feature:
            problems.append(issue("FEATURE_FIELD_MISSING", "C", f"{loc}:{phase}:{key}", f"{phase}_{key}"))
            continue
        if not feature_is_valid(key, feature.get(key), feature, allowed):
            problems.append(issue("FEATURE_FIELD_INVALID", "C", f"{loc}:{phase}:{key}={feature.get(key)}", f"{phase}_{key}"))

    position = finite_number(feature.get("dealing_range_position"))
    premium_discount = feature.get("premium_discount_side")
    if position is not None and premium_discount in {"discount", "premium"}:
        expected = "discount" if position < 0.5 else "premium"
        if premium_discount != expected:
            problems.append(issue(
                "PREMIUM_DISCOUNT_INCONSISTENT",
                "M",
                f"{loc}:{phase}:position={position}:actual={premium_discount}:expected={expected}",
                f"{phase}_premium_discount_side",
            ))

    depth = finite_number(feature.get("ote_depth"))
    ote_flag = feature.get("ote_0_5_0_79")
    if isinstance(ote_flag, bool):
        expected_ote = depth is not None and 0.5 <= depth <= 0.79
        if ote_flag != expected_ote:
            problems.append(issue(
                "OTE_FLAG_INCONSISTENT",
                "M",
                f"{loc}:{phase}:depth={feature.get('ote_depth')}:flag={ote_flag}",
                f"{phase}_ote_0_5_0_79",
            ))
    return problems


def validate_rows(
    rows: Sequence[Mapping[str, Any]],
    ssot: Mapping[str, Any],
    producer_status: Mapping[str, Any],
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    expected_epoch = str(ssot["expected_epoch"])
    expected_namespace = str(ssot["expected_namespace"])
    expected_source = str(ssot["expected_source"])
    expected_measurement_source = str(ssot["expected_measurement_source"])
    required = [str(value) for value in ssot.get("required_feature_fields", [])]
    allowed = ssot.get("allowed_values") if isinstance(ssot.get("allowed_values"), dict) else {}

    if ssot.get("feature_filter_must_remain_disabled") is True and producer_status.get("feature_filter_enabled") not in (False, None):
        problems.append(issue(
            "FEATURE_FILTER_ENABLED",
            "C",
            f"feature_filter_enabled={producer_status.get('feature_filter_enabled')}",
            "feature_filter_enabled",
        ))

    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        event_id = str(row.get("event_id") or "")
        loc = event_id or f"row={index}"
        if not event_id:
            problems.append(issue("EVENT_ID_MISSING", "C", loc, "event_id"))
        elif event_id in seen:
            problems.append(issue("DUPLICATE_EVENT_ID", "C", loc, "event_id"))
        seen.add(event_id)

        if row.get("epoch_id") != expected_epoch or row.get("measurement_namespace") != expected_namespace:
            problems.append(issue("FEATURE_EVENT_IDENTITY_MISMATCH", "C", loc, "event_identity"))
        if row.get("source") != expected_source:
            problems.append(issue("FEATURE_EVENT_SOURCE_MISMATCH", "C", f"{loc}:{row.get('source')}", "source"))
        if row.get("measurement_source") != expected_measurement_source:
            problems.append(issue(
                "FEATURE_MEASUREMENT_SOURCE_MISMATCH",
                "C",
                f"{loc}:{row.get('measurement_source')}",
                "measurement_source",
            ))
        if row.get("feature_observer_only") is not True:
            problems.append(issue("FEATURE_OBSERVER_FLAG_MISSING", "C", loc, "feature_observer_only"))
        if str(row.get("mode") or "").lower() != "shadow" or row.get("shadow") is not True:
            problems.append(issue("FEATURE_EVENT_NOT_SHADOW", "C", loc, "mode"))
        for key in ("paper_enabled", "live_enabled", "order_enabled"):
            if row.get(key) is not False:
                problems.append(issue("UNSAFE_EVENT_FLAG", "C", f"{loc}:{key}={row.get(key)}", key))
        if finite_number(row.get("realized_R")) is None:
            problems.append(issue("REALIZED_R_INVALID", "C", loc, "realized_R"))

        for phase in ("entry", "exit"):
            payload = row.get(f"{phase}_features")
            if not isinstance(payload, dict):
                problems.append(issue("FEATURE_PAYLOAD_MISSING", "C", f"{loc}:{phase}", f"{phase}_features"))
                continue
            problems.extend(validate_feature_payload(phase, payload, loc, required, allowed))
    return problems


def coverage_report(rows: Sequence[Mapping[str, Any]], ssot: Mapping[str, Any]) -> dict[str, Any]:
    required = [str(value) for value in ssot.get("required_feature_fields", [])]
    allowed = ssot.get("allowed_values") if isinstance(ssot.get("allowed_values"), dict) else {}
    report: dict[str, Any] = {}
    total = len(rows)
    for phase in ("entry", "exit"):
        fields: dict[str, Any] = {}
        complete = 0
        for row in rows:
            feature = row.get(f"{phase}_features")
            if isinstance(feature, dict) and all(
                key in feature and feature_is_valid(key, feature.get(key), feature, allowed) for key in required
            ):
                complete += 1
        for key in required:
            present = 0
            valid = 0
            for row in rows:
                feature = row.get(f"{phase}_features")
                if not isinstance(feature, dict) or key not in feature:
                    continue
                present += 1
                if feature_is_valid(key, feature.get(key), feature, allowed):
                    valid += 1
            fields[key] = {
                "present_count": present,
                "valid_count": valid,
                "coverage_pct": round(valid / total * 100.0, 6) if total else None,
            }
        report[phase] = {
            "row_count": total,
            "complete_count": complete,
            "complete_coverage_pct": round(complete / total * 100.0, 6) if total else None,
            "fields": fields,
        }
    return report


def bucket_metrics(values: Sequence[float], minimum_sample: int) -> dict[str, Any]:
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    profit_factor = None
    if negatives:
        profit_factor = sum(positives) / abs(sum(negatives))
    return {
        "sample_count": len(values),
        "cumulative_R": round(sum(values), 8),
        "average_R": round(sum(values) / len(values), 8) if values else None,
        "win_rate_pct": round(len(positives) / len(values) * 100.0, 6) if values else None,
        "profit_factor": round(profit_factor, 8) if profit_factor is not None else None,
        "minimum_sample": minimum_sample,
        "minimum_sample_met": len(values) >= minimum_sample,
        "decision": "OBSERVE_ONLY",
    }


def numeric_bucket(value: Any, edges: Sequence[float]) -> str:
    number = finite_number(value)
    if number is None:
        return "missing"
    for index in range(len(edges) - 1):
        low = float(edges[index])
        high = float(edges[index + 1])
        inclusive = index == len(edges) - 2
        if low <= number <= high if inclusive else low <= number < high:
            right = "]" if inclusive else ")"
            return f"[{low:g},{high:g}{right}"
    return "out_of_range"


def attribution(rows: Sequence[Mapping[str, Any]], ssot: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    minimum_sample = int(ssot.get("minimum_bucket_sample") or 30)
    categorical = [str(value) for value in ssot.get("categorical_attribution_fields", [])]
    numeric = ssot.get("numeric_attribution_bins") if isinstance(ssot.get("numeric_attribution_bins"), dict) else {}
    overall: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_strategy: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for row in rows:
        realized_r = finite_number(row.get("realized_R"))
        feature = row.get("entry_features")
        if realized_r is None or not isinstance(feature, dict):
            continue
        strategy = str(row.get("strategy_id") or "unknown")
        for field in categorical:
            value = feature.get(field)
            bucket = "true" if value is True else "false" if value is False else "missing" if value is None else str(value)
            overall[field][bucket].append(realized_r)
            by_strategy[strategy][field][bucket].append(realized_r)
        for field, raw_edges in numeric.items():
            if not isinstance(raw_edges, list) or len(raw_edges) < 2:
                continue
            edges = [float(value) for value in raw_edges]
            bucket = numeric_bucket(feature.get(field), edges)
            overall[str(field)][bucket].append(realized_r)
            by_strategy[strategy][str(field)][bucket].append(realized_r)

    overall_out = {
        field: {bucket: bucket_metrics(values, minimum_sample) for bucket, values in sorted(buckets.items())}
        for field, buckets in sorted(overall.items())
    }
    strategy_out = {
        strategy: {
            field: {bucket: bucket_metrics(values, minimum_sample) for bucket, values in sorted(buckets.items())}
            for field, buckets in sorted(fields.items())
        }
        for strategy, fields in sorted(by_strategy.items())
    }
    return overall_out, strategy_out


def severity_of(problems: Sequence[Mapping[str, Any]]) -> str | None:
    severity: str | None = None
    for problem in problems:
        candidate = str(problem.get("severity") or "m")
        if SEVERITY_RANK.get(candidate, 1) > SEVERITY_RANK.get(severity, 0):
            severity = candidate
    return severity


def violation_fingerprint(problems: Sequence[Mapping[str, Any]]) -> str | None:
    if not problems:
        return None
    normalized = sorted(
        (str(item.get("code")), str(item.get("severity")), str(item.get("metric")), str(item.get("detail")))
        for item in problems
    )
    raw = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run(args: argparse.Namespace) -> int:
    ssot = load_json(args.ssot.resolve())
    producer_status = load_json(args.producer_status.resolve())
    rows, ledger_sha256, problems = read_ledger_snapshot(args.ledger.resolve())
    problems.extend(validate_rows(rows, ssot, producer_status))

    coverage = coverage_report(rows, ssot)
    overall_attribution, strategy_matrix = attribution(rows, ssot)
    severity = severity_of(problems)
    fingerprint = violation_fingerprint(problems)
    prior: dict[str, Any] = {}
    if args.violations.exists():
        try:
            prior = load_json(args.violations.resolve())
        except Exception:
            prior = {}
    prior_severity = prior.get("severity") if isinstance(prior.get("severity"), str) else None
    notify = bool(problems) and (
        fingerprint != prior.get("fingerprint")
        or SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(prior_severity, 0)
    )

    report = {
        "schema": "q4r3_exact25_ict_feature_attribution_report_v1",
        "status": "HOLD" if problems else "PASS",
        "verdict": "FEATURE_INTEGRITY_VIOLATION" if problems else "ICT_FEATURE_OBSERVER_HEALTHY",
        "action": "hold",
        "next_action": "INVESTIGATE_FEATURE_INTEGRITY" if problems else "ACCUMULATE_FORWARD_FEATURE_ROWS",
        "updated_at": now_iso(),
        "epoch_id": ssot.get("expected_epoch"),
        "measurement_namespace": ssot.get("expected_namespace"),
        "ledger_path": str(args.ledger.resolve()),
        "ledger_snapshot_sha256": ledger_sha256,
        "ledger_row_count": len(rows),
        "feature_filter_enabled": producer_status.get("feature_filter_enabled"),
        "feature_observer_only": True,
        "historical_backfill_allowed": False,
        "attribution_decision_enabled": False,
        "strategy_promotion_enabled": False,
        "minimum_bucket_sample": int(ssot.get("minimum_bucket_sample") or 30),
        "coverage": coverage,
        "overall_entry_feature_attribution": overall_attribution,
        "strategy_entry_feature_matrix": strategy_matrix,
        "violation_count": len(problems),
        "violation_severity": severity,
        "violation_notify": notify,
        "violation_fingerprint": fingerprint,
        "comparison_ready": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }
    violation_payload = {
        "schema": "q4r3_exact25_ict_feature_violations_v1",
        "updated_at": report["updated_at"],
        "state": "VIOLATION" if problems else "CLEAR",
        "severity": severity,
        "notify": notify,
        "fingerprint": fingerprint,
        "count": len(problems),
        "violations": problems,
        "action": "hold",
    }
    atomic_json(args.report.resolve(), report)
    atomic_json(args.violations.resolve(), violation_payload)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--producer-status", type=Path, required=True)
    parser.add_argument("--ssot", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--violations", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
