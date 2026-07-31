from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path

from backend.tools import strategy11_post_gemini_intake_v1 as subject


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe(**extra):
    return {**subject.SAFETY, **extra}


def reviews():
    rows=[]
    for i in range(24):
        sid=f"strategy_{i:02d}"
        verdict="NO_ACTION"; candidate=None; reason="NO_BOUNDED_IMPROVEMENT"
        if i in (0,1,2): verdict="SELECT_REPLAY"; candidate=f"CAND_{i}"; reason="BOUNDED_HYPOTHESIS"
        if i in (22,23): verdict="NEW_CHILD_REQUIRED"; reason="BASIS_REJECT"
        rows.append({"strategy_id":sid,"verdict":verdict,"selected_candidate_id":candidate,"causal_reason":reason,"overfit_risk":"MEDIUM","video_source_indexes":[1,2] if candidate else []})
    return rows


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        summary=safe(GEMINI_USED=True,reviewed_strategy_count=24,state="PASS_GEMINI_V3_2_COHORT_REVIEW")
        artifact=safe(run_id="TEST_RUN",input_sha="i",prompt_sha="p",response_sha="r",public_urls=["a","b","c","d"],alpha_fresh_only={"strategy_id":"alpha_combo","authority":"TIME54_TIME60_W1_FRESH_ONLY","hypotheses":[{"label":"HYPOTHESIS_EXTERNAL_FRESH_ONLY","axis":"exit_trailing_distance","parameter":"trailing_stop_distance_pips","values":[20,30],"single_cause_change":"trailing_stop","falsification_test":"fresh W1"}]},response={"strategy_reviews":reviews(),"terminal_hold_reason":"FAILED_RESCUE_FAMILY_DIVERSITY_LOW:2"})
        ai=safe(state="PASS_CANDIDATE_AI_FILTER",accepted_strategy_ids=[],rejected_rows=[])
        replay=safe(state="COMPLETE_NO_AI_APPROVED_GEMINI_REPLAY_AXIS",discovery_pass_rows=[],blockers=[])
        for name,value in (("summary",summary),("artifact",artifact),("ai",ai),("replay",replay)): dump(root/f"{name}.json",value)
        classification=root/"classification.json"
        subject.classify(Namespace(summary=str(root/'summary.json'),gemini_artifact=str(root/'artifact.json'),ai_filter=str(root/'ai.json'),replay_final=str(root/'replay.json'),out=str(classification)))
        c=subject.read_json(classification)
        assert c["category_counts"]=={"NEW_CHILD_REQUIRED":2,"NO_CHANGE":19,"RESEARCH_HYPOTHESIS_HOLD":3}
        alpha_path=root/"alpha.json"
        subject.alpha_receipt(Namespace(gemini_artifact=str(root/'artifact.json'),out=str(alpha_path)))
        assert subject.read_json(alpha_path)["state"]=="WAIT_ALPHA_W1_FRESH"
        symbols=[{"symbol":sid,"rows":384,"market_sha256":"m"+sid,"funding_sha256":"f"+sid} for sid in sorted(subject.EXPECTED_SYMBOLS)]
        manifest=safe(state="PASS",blockers=[],available_non_overlap_bars=384,missing_to_w1_480=96,w1_ready=False,latest_closed_end="2026-07-31T08:30:00+00:00",symbols=symbols)
        contract={"upstream":{"w1_exact_end_utc":"2026-08-01T08:30:00Z","native_completion_artifact":"s11-w1-native-completion-20260801t083000z-v1"},"candidate":{"strategy_id":"trend_ma_macd","variant_id":"INT3_MAX_CHASE_DIST_ATR_RELAX"},"safety":subject.SAFETY}
        dump(root/'manifest.json',manifest); dump(root/'contract.json',contract)
        w1_path=root/'w1.json'
        subject.w1_preflight(Namespace(manifest=str(root/'manifest.json'),overlay_contract=str(root/'contract.json'),out=str(w1_path)))
        assert subject.read_json(w1_path)["state"]=="WAIT_W1_DATA"
        intake_path=root/'intake.json'
        subject.shadow_intake(Namespace(classification=str(classification),alpha_receipt=str(alpha_path),w1_preflight=str(w1_path),trend_w1=None,alpha_w1=None,out=str(intake_path)))
        intake=subject.read_json(intake_path)
        assert intake["state"]=="WAIT_SHADOW_INTAKE_UPSTREAM" and intake["shadow_start_allowed"] is False
        manifest.update(available_non_overlap_bars=480,missing_to_w1_480=0,w1_ready=True,latest_closed_end="2026-08-01T08:30:00+00:00")
        for row in manifest["symbols"]: row["rows"]=480
        dump(root/'manifest-ready.json',manifest)
        w1_ready=root/'w1-ready.json'
        subject.w1_preflight(Namespace(manifest=str(root/'manifest-ready.json'),overlay_contract=str(root/'contract.json'),out=str(w1_ready)))
        dump(root/'trend-pass.json',safe(state="PASS_W1_V3_SURVIVOR_CONFIRMATION")); dump(root/'alpha-pass.json',safe(state="PASS_ALPHA_W1_FRESH_CONFIRMATION"))
        ready_intake=root/'ready-intake.json'
        subject.shadow_intake(Namespace(classification=str(classification),alpha_receipt=str(alpha_path),w1_preflight=str(w1_ready),trend_w1=str(root/'trend-pass.json'),alpha_w1=str(root/'alpha-pass.json'),out=str(ready_intake)))
        result=subject.read_json(ready_intake)
        assert result["state"]=="READY_SHADOW_INTAKE_REVIEW" and result["admitted_family_count"]==2
        assert result["shadow_start_allowed"] is False
    print("PASS_STRATEGY11_POST_GEMINI_INTAKE_FIXTURE_V1")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
