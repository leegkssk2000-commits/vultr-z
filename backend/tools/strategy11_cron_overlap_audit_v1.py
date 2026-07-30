from __future__ import annotations

import itertools
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


class CronAuditError(ValueError):
    pass


def _expand_atom(atom: str, minimum: int, maximum: int, *, sunday_alias: bool = False) -> set[int]:
    atom = atom.strip()
    if not atom:
        raise CronAuditError("EMPTY_CRON_ATOM")
    base, slash, step_raw = atom.partition("/")
    step = int(step_raw) if slash else 1
    if step <= 0:
        raise CronAuditError(f"CRON_STEP_INVALID:{atom}")
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        start_raw, end_raw = base.split("-", 1)
        start, end = int(start_raw), int(end_raw)
    else:
        value = int(base)
        start = end = value
    if start < minimum or end > maximum or start > end:
        raise CronAuditError(f"CRON_RANGE_INVALID:{atom}:{minimum}:{maximum}")
    values = set(range(start, end + 1, step))
    if sunday_alias and 7 in values:
        values.remove(7)
        values.add(0)
    return values


def _expand_field(field: str, minimum: int, maximum: int, *, sunday_alias: bool = False) -> set[int]:
    values: set[int] = set()
    for atom in field.split(","):
        values.update(_expand_atom(atom, minimum, maximum, sunday_alias=sunday_alias))
    return values


def _parse(expression: str) -> dict[str, Any]:
    parts = expression.split()
    if len(parts) != 5:
        raise CronAuditError(f"CRON_FIELD_COUNT:{expression}")
    minute_raw, hour_raw, dom_raw, month_raw, dow_raw = parts
    return {
        "expression": expression,
        "minute": _expand_field(minute_raw, 0, 59),
        "hour": _expand_field(hour_raw, 0, 23),
        "day_of_month": _expand_field(dom_raw, 1, 31),
        "month": _expand_field(month_raw, 1, 12),
        "day_of_week": _expand_field(dow_raw, 0, 7, sunday_alias=True),
        "dom_wildcard": dom_raw == "*",
        "dow_wildcard": dow_raw == "*",
    }


def _matches(schedule: Mapping[str, Any], moment: datetime) -> bool:
    if moment.minute not in schedule["minute"] or moment.hour not in schedule["hour"]:
        return False
    if moment.month not in schedule["month"]:
        return False
    dom_match = moment.day in schedule["day_of_month"]
    cron_dow = (moment.weekday() + 1) % 7
    dow_match = cron_dow in schedule["day_of_week"]
    if schedule["dom_wildcard"] and schedule["dow_wildcard"]:
        return True
    if schedule["dom_wildcard"]:
        return dow_match
    if schedule["dow_wildcard"]:
        return dom_match
    return dom_match or dow_match


def find_overlapping_schedules(
    workflows: Iterable[Mapping[str, Any]],
    *,
    start: datetime = datetime(2028, 1, 1, tzinfo=timezone.utc),
    duration_days: int = 366,
) -> list[dict[str, Any]]:
    if duration_days < 1:
        raise CronAuditError("DURATION_DAYS_INVALID")
    schedules: list[dict[str, Any]] = []
    for workflow in workflows:
        path = str(workflow.get("path", ""))
        crons = workflow.get("cron", [])
        if not isinstance(crons, list):
            raise CronAuditError(f"CRON_LIST_REQUIRED:{path}")
        for expression in crons:
            parsed = _parse(str(expression))
            parsed["path"] = path
            schedules.append(parsed)

    counts: Counter[tuple[int, int]] = Counter()
    first_seen: dict[tuple[int, int], str] = {}
    moment = start.replace(second=0, microsecond=0)
    end = moment + timedelta(days=duration_days)
    while moment < end:
        active = [index for index, schedule in enumerate(schedules) if _matches(schedule, moment)]
        for pair in itertools.combinations(active, 2):
            if schedules[pair[0]]["path"] == schedules[pair[1]]["path"]:
                continue
            counts[pair] += 1
            first_seen.setdefault(pair, moment.isoformat())
        moment += timedelta(minutes=1)

    result = []
    for pair, count in counts.items():
        left, right = schedules[pair[0]], schedules[pair[1]]
        result.append(
            {
                "workflows": sorted([left["path"], right["path"]]),
                "expressions": {
                    left["path"]: left["expression"],
                    right["path"]: right["expression"],
                },
                "collision_count_in_window": count,
                "first_collision_utc": first_seen[pair],
                "window_start_utc": start.isoformat(),
                "window_days": duration_days,
            }
        )
    return sorted(
        result,
        key=lambda row: (-row["collision_count_in_window"], row["workflows"]),
    )


if __name__ == "__main__":
    fixture = [
        {"path": "hourly.yml", "cron": ["17 * * * *"]},
        {"path": "four-hour.yml", "cron": ["17 */4 * * *"]},
        {"path": "separate.yml", "cron": ["27 */4 * * *"]},
    ]
    overlaps = find_overlapping_schedules(fixture, duration_days=7)
    assert len(overlaps) == 1, overlaps
    assert overlaps[0]["workflows"] == ["four-hour.yml", "hourly.yml"], overlaps
    print("PASS_CRON_OVERLAP_AUDIT")
