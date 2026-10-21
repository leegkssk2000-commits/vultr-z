def _fresh_touch_successor(
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    windows: list[dict[str, Any]],
    *, benchmark_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    first_start = min(int(window["start_ms"]) for window in windows)
    ordered_windows = sorted(windows, key=lambda item: int(item["start_ms"]))
    prepared: dict[
        tuple[str, str], tuple[pd.DataFrame, list[dict[str, Any]], dict[int, int]]
    ] = {}
    for window in windows:
        start, end = int(window["start_ms"]), int(window["end_ms"])
        prefix_start = start - 200 * positive.TIMEFRAME_MS
        for symbol, frame in frames.items():
            sliced = frame[
                (frame["open_ts_ms"] >= prefix_start)
                & (frame["close_ts_ms"] <= end)
            ].reset_index(drop=True)
            records, index = execution._frame_records(
                sliced, positive.TIMEFRAME_MIN
            )
            prepared[(str(window["label"]), symbol)] = (sliced, records, index)

    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    boundary_excluded: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    by_partition: dict[str, Counter[str]] = {
        "validation": Counter(),
        "rolling": Counter(),
    }
    unverified_admissions: Counter[str] = Counter()
    unverified_by_partition: dict[str, Counter[str]] = {
        "validation": Counter(),
        "rolling": Counter(),
    }
    candidates: Counter[str] = Counter()
    admitted: Counter[str] = Counter()
    ownership: dict[tuple[str, str], int] = {}
    held_positions: dict = {}
    seen: set[tuple[str, str, int]] = set()

    for symbol, frame in sorted(frames.items()):
        cost = float(costs.get(symbol, float("nan")))
        if not math.isfinite(cost) or cost <= 0:
            raise ValueError("KELTNER_SUCCESSOR_COST_UNBOUND:" + symbol)
        for segment in positive.enriched_segments(frame):
            source_rows = segment.to_dict("records")
            state = positive.HolyGrailState()
            if benchmark_observations is not None:
                from ops.scalp7_benchmark_observer_v1 import HGObserver
                watcher = HGObserver(symbol)
            pending: dict[str, Any] | None = None
            for i in range(1, len(source_rows)):
                row, previous = source_rows[i], source_rows[i - 1]
                before = _state(state)
                observation = None
                if i >= 121 and benchmark_observations is not None:
                    from dataclasses import asdict
                    from ops.scalp7_benchmark_observer_v1 import _state_view
                    raw_before = asdict(state)
                    # Exactly one native call. Observe raw dataclass state, not
                    # the JSON null-sanitized projection used by existing traces.
                    event = positive._hg_event(state, row, previous)
                    try:
                        observation = watcher.observe(raw_before, asdict(state), row, previous, event)
                    except (ValueError, KeyError, TypeError, IndexError) as exc:
                        observation = {"kind": "KELTNER_TRANSITION_UNKNOWN", "symbol": symbol,
                            "signal_open_ts_ms": int(row["open_ts_ms"]),
                            "error_type": type(exc).__name__, "error": str(exc),
                            "coverage": "UNKNOWN_NOT_ZERO"}
                    observation["admission"] = {"state": "NO_GENERATED_EVENT", "reason": None}
                    benchmark_observations.append(observation)
                else:
                    event = positive._hg_event(state, row, previous) if i >= 121 else None
                after = _state(state)
                row_available = int(row["feature_available_ts_ms"])
                if (
                    pending is not None
                    and int(after["side"]) != int(pending["rejected_side"])
                ):
                    pending["next_decision"] = (
                        "NATIVE_SIDE_OR_WEAK_RESET_BEFORE_NEW_TOUCH"
                    )
                    traces.append(pending)
                    pending = None
                if (
                    pending is not None
                    and before["stage"] == 0
                    and after["stage"] == 1
                    and event is None
                ):
                    if row_available <= int(pending["rejected_decision_ts_ms"]):
                        raise ValueError("NONCAUSAL_NEW_TOUCH:" + symbol)
                    pending["new_touch_ts_ms"] = row_available
                    pending["new_touch_open_ts_ms"] = int(row["open_ts_ms"])
                if event is None:
                    continue
                if observation is not None:
                    observation["admission"] = {"state": "OUTSIDE_EVALUATION_WINDOW", "reason": None}
                regime, regime_available = positive._regime(row, None)
                stamp = max(row_available, int(regime_available))
                if stamp < first_start:
                    continue
                # Match the accepted-entry child control: evaluation alone
                # must not consume the episode.  Geometry is unchanged here.
                state.episode_traded = False
                window = next(
                    (
                        item
                        for item in ordered_windows
                        if int(item["start_ms"]) <= stamp < int(item["end_ms"])
                    ),
                    None,
                )
                if window is None:
                    continue
                partition = str(window["partition"])
                if regime not in {"PANIC_DISPERSION", "TREND_DISPERSED"}:
                    if observation is not None:
                        observation["admission"] = {"state": "REGIME_INELIGIBLE_NO_RESET", "reason": regime}
                    continue

                candidates[partition] += 1
                signal = native._keltner_parent_signal(
                    symbol,
                    row,
                    int(event[0]),
                    float(event[1]),
                    regime,
                    int(regime_available),
                    cost,
                )
                policy = RejectedHGEventReset()
                policy.generated(int(stamp))
                duplicate = (str(window["label"]), symbol, int(stamp))
                reason: str | None = None
                decision_ts: int | None = int(stamp)
                trade = open_position = None
                until = int(stamp)

                if duplicate in seen:
                    reason = "DUPLICATE_SIGNAL"
                else:
                    seen.add(duplicate)
                    owner = (str(window["label"]), symbol)
                    if stamp < ownership.get(owner, -1):
                        hand_frame,hand_records,hand_index = prepared[(str(window["label"]),symbol)]
                        released = _handoff.switch(held_positions.get(owner),signal,hand_frame,hand_records,hand_index,cost,window,rows,unresolved,boundary_excluded)
                        if released is None:
                            reason = "POSITION_ALREADY_OWNED"
                        else:
                            ownership[owner] = released
                    if reason is None:
                        sliced, records, index = prepared[
                            (str(window["label"]), symbol)
                        ]
                        gate_allowed, gate_ts, gate_reason = native._entry_gate(
                            signal, {symbol: sliced}
                        )
                        trade, open_position, until, reason = execution._single(
                            signal,
                            sliced,
                            records,
                            index,
                            cost,
                            positive.exit_update,
                            positive.entry_update,
                        )
                        decision_ts = (
                            int(gate_ts) if gate_ts is not None else None
                        )
                        if reason is None and (
                            not gate_allowed or decision_ts is None
                        ):
                            raise ValueError(
                                "ENTRY_GATE_SINGLE_DISAGREEMENT:"
                                + symbol
                                + ":"
                                + str(gate_reason)
                            )
                        if reason is not None and not gate_allowed:
                            reason = str(reason)
                if reason is not None and decision_ts is None:
                    reason = str(reason)
                    unverified_admissions[reason] += 1
                    unverified_by_partition[partition][reason] += 1
                    if observation is not None:
                        observation["admission"] = {"state": "UNKNOWN_NO_RESET", "reason": reason}
                    continue
                if reason is not None:
                    reason = str(reason)
                    rejections[reason] += 1
                    by_partition[partition][reason] += 1
                    pending = _reject_generated(
                        policy,
                        state,
                        signal_ts_ms=int(stamp),
                        decision_ts_ms=int(decision_ts),
                        reason=reason,
                        symbol=symbol,
                        segment_id=str(row["segment_id"]),
                        pending=pending,
                        traces=traces,
                    )
                    if observation is not None:
                        observation["admission"] = {"state": "REJECTED_RESET", "reason": reason,
                            "decision_ts_ms": int(decision_ts),
                            "state_after_policy": _state_view(asdict(state))}
                    continue

                if pending is not None:
                    if pending.get("new_touch_ts_ms") is None:
                        raise ValueError(
                            "ACCEPTED_SUCCESSOR_TURN_WITHOUT_NEW_TOUCH:" + symbol
                        )
                    if int(pending["new_touch_ts_ms"]) <= int(
                        pending["rejected_decision_ts_ms"]
                    ):
                        raise ValueError(
                            "NEW_TOUCH_NOT_STRICTLY_AFTER_REJECTION:" + symbol
                        )
                    pending["new_turn_ts_ms"] = int(stamp)
                    pending["accepted_entry_ts_ms"] = int(decision_ts)
                    pending["next_decision"] = "ACCEPTED"
                    traces.append(pending)
                    pending = None
                policy.decided(
                    state, accepted=True, decision_ts_ms=int(decision_ts)
                )
                if observation is not None:
                    observation["admission"] = {"state": "ACCEPTED", "reason": None,
                        "decision_ts_ms": int(decision_ts),
                        "state_after_policy": _state_view(asdict(state))}
                admitted[partition] += 1
                owner = (str(window["label"]), symbol)
                ownership[owner] = int(until)
                filled = trade if trade is not None else open_position
                held_positions[owner] = {"signal":deepcopy(signal),"entry_ts_ms":int(filled["entry_ts_ms"])}
                if trade is not None:
                    child = _relabel(trade)
                    child["window_label"] = str(window["label"])
                    child["partition"] = partition
                    if int(child["outcome_available_ts_ms"]) >= int(
                        window["end_ms"]
                    ):
                        child["boundary_exclusion_reason"] = (
                            "OUTCOME_AT_OR_AFTER_WINDOW_END_UNAVAILABLE"
                        )
                        child["window_end_ms"] = int(window["end_ms"])
                        boundary_excluded.append(child)
                    else:
                        rows.append(child)
                if open_position is not None:
                    child_open = _relabel(open_position)
                    child_open["window_label"] = str(window["label"])
                    child_open["partition"] = partition
                    child_open["window_end_ms"] = int(window["end_ms"])
                    unresolved.append(child_open)
            if pending is not None:
                pending["next_decision"] = "NO_LATER_ACCEPTED_EVENT_IN_SEGMENT"
                traces.append(pending)

    rows.sort(
        key=lambda item: (
            int(item["outcome_available_ts_ms"]),
            int(item["exit_ts_ms"]),
            str(item["symbol"]),
            str(item["identity"]),
            int(item["signal_ts_ms"]),
        )
    )
    return {
        "trades": rows,
        "unresolved": unresolved,
        "boundary_excluded": boundary_excluded,
        "traces": traces,
        "candidate_count_by_partition": dict(candidates),
        "admitted_count_by_partition": dict(admitted),
        "rejections": dict(sorted(rejections.items())),
        "rejections_by_partition": {
            key: dict(sorted(value.items())) for key, value in by_partition.items()
        },
        "unverified_admissions": dict(sorted(unverified_admissions.items())),
        "unverified_admissions_by_partition": {
            key: dict(sorted(value.items()))
            for key, value in unverified_by_partition.items()
        },
    }
