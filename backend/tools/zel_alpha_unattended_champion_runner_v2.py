from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_alpha_unattended_champion_v2 as engine


def read_previous(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    value = engine.read_json(path)
    return value if value.get("schema_version") == engine.STATE_SCHEMA else None


def terminal_receipt(
    *,
    policy: Mapping[str, Any],
    previous: Mapping[str, Any],
    out: Path,
) -> int:
    champion_found = previous.get("champion_found") is True
    converged = previous.get("converged") is True
    if not champion_found and not converged:
        return -1
    safety = dict(policy["safety"])
    receipt = {
        "schema_version": engine.SCHEMA,
        "version": engine.VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": (
            "PASS_ALPHA_CHAMPION_ALREADY_SEALED_FOR_RESEARCH_HOLDBACK"
            if champion_found
            else "WAIT_NEW_DATA_FINGERPRINT_ALPHA_CHAMPION_NOT_FOUND"
        ),
        "strategy_id": "alpha_combo",
        "data_fingerprint": previous.get("data_fingerprint"),
        "epoch": previous.get("epoch"),
        "champion": previous.get("best_metrics") if champion_found else None,
        "champion_config": previous.get("best_config") if champion_found else None,
        "champion_found": champion_found,
        "converged": converged,
        "raw_canonical_exact25_used_as_control": False,
        "time54_time60_authority_restored": True,
        "raw_trade_rows_published": False,
        "raw_prices_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "shadow_start_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "WAIT_SEALED_HOLDBACK_AND_NEW_FORWARD_CONFIRMATION"
            if champion_found
            else "WAIT_NEW_IMMUTABLE_DATA_THEN_RESET_SEARCH"
        ),
        **safety,
    }
    receipt["receipt_sha256"] = engine.stable_sha(receipt)
    out.mkdir(parents=True, exist_ok=True)
    engine.write_json(out / "latest.json", receipt)
    engine.write_json(out / "state.json", previous)
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "champion_found": champion_found,
                "converged": converged,
                "replay_skipped": True,
            },
            sort_keys=True,
        )
    )
    return 0


def choose_epoch_policy(
    policy: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> tuple[dict[str, Any], str, Any]:
    epoch = int((previous or {}).get("epoch") or 0)
    axis = engine.choose_axis(policy, previous, epoch)
    axis_id = str(axis["axis_id"])
    values = list(axis.get("values") or [])
    if not values:
        raise RuntimeError(f"AXIS_VALUES_EMPTY:{axis_id}")
    tested = set(str(v) for v in (previous or {}).get("tested_config_sha256", []))
    control = engine.normalized_config(
        (previous or {}).get("best_config") or policy["initial_control"]
    )
    selected = None
    for offset in range(len(values)):
        value = values[(epoch + offset) % len(values)]
        candidate = engine.config_for_axis(control, axis, value)
        digest = engine.config_sha(candidate)
        if digest != engine.config_sha(control) and digest not in tested:
            selected = value
            break
    if selected is None:
        selected = values[epoch % len(values)]
    bounded = copy.deepcopy(dict(policy))
    for row in bounded["axes"]:
        if str(row.get("axis_id")) == axis_id:
            row["values"] = [selected]
    bounded["runtime_epoch_bound"] = {
        "one_candidate_only": True,
        "axis_id": axis_id,
        "value": selected,
        "epoch": epoch + 1,
    }
    return bounded, axis_id, selected


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    known, _ = parser.parse_known_args()
    original_policy = known.policy.resolve()
    policy = engine.read_json(original_policy)
    previous = read_previous(known.previous_state)
    if previous:
        terminal = terminal_receipt(policy=policy, previous=previous, out=known.out.resolve())
        if terminal == 0:
            return 0
    bounded, axis_id, selected = choose_epoch_policy(policy, previous)

    with tempfile.TemporaryDirectory(prefix="zel-alpha-epoch-") as tmp:
        epoch_policy = Path(tmp) / "policy.json"
        engine.write_json(epoch_policy, bounded)
        original_fingerprint = engine.fingerprint

        def stable_fingerprint(
            *,
            data_root: Path,
            baseline_path: Path,
            authority_root: Path,
            policy_path: Path,
        ) -> str:
            return original_fingerprint(
                data_root=data_root,
                baseline_path=baseline_path,
                authority_root=authority_root,
                policy_path=original_policy,
            )

        engine.fingerprint = stable_fingerprint
        argv = list(sys.argv)
        index = argv.index("--policy") + 1
        argv[index] = str(epoch_policy)
        sys.argv = argv
        print(
            f"ALPHA_EPOCH_BOUND axis={axis_id} value={selected} one_candidate_only=true",
            flush=True,
        )
        return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
