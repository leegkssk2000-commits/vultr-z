from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

VERSION = "ZEL_BIND_AI_CONTROL_WORKFLOWS_V1"
TOKEN = "ZEL_AI_CONTROL_GATE_V1"


@dataclass(frozen=True)
class Binding:
    filename: str
    target_job: str
    stage_id: str
    predecessor_path: str
    upstream_needs: tuple[str, ...]


BINDINGS = (
    Binding(
        "zel-exact25-material-upgrade-loop-v1.yml",
        "direct",
        "EXACT25_LIVENESS_AND_REPAIR",
        "results/runtime_results/zel/data_b_risk_adapter_ablation_v1/latest.json",
        ("validate", "prerequisite"),
    ),
    Binding(
        "zel-trade-methods-pre-shadow-audit-v1.yml",
        "audit",
        "TRADE_METHOD_COVERAGE",
        "results/runtime_results/zel/exact25_material_upgrade_v1/latest.json",
        ("validate", "prerequisite"),
    ),
    Binding(
        "zel-alpha-auto-validation-chain-v1.yml",
        "orchestrate",
        "ALPHA_LAP_CHALLENGERS",
        "results/runtime_results/zel/strategy_top3_bundles_v1/latest.json",
        ("validate", "prerequisite"),
    ),
    Binding(
        "zel-exact25-material-child-probe-v2.yml",
        "probe",
        "EXACT25_LIVENESS_AND_REPAIR",
        "results/runtime_results/zel/exact25_material_upgrade_v1/latest.json",
        ("validate",),
    ),
    Binding(
        "zel-component-autonomy-v3.yml",
        "replay",
        "COMPONENT_MAIN_EFFECT",
        "results/runtime_results/zel/trade_methods_pre_shadow_v1/latest.json",
        ("verify",),
    ),
)


def gate_job(binding: Binding) -> str:
    needs = ", ".join(binding.upstream_needs)
    existing_ready = ""
    if "prerequisite" in binding.upstream_needs:
        existing_ready = " && needs.prerequisite.outputs.ready == 'true'"
    return f'''  ai_control_{binding.target_job}:
    if: github.event_name != 'pull_request'{existing_ready}
    needs: [{needs}]
    runs-on: ubuntu-latest
    timeout-minutes: 10
    outputs:
      ready: ${{{{ steps.gate.outputs.ready }}}}
    steps:
      - name: Checkout control plane
        uses: actions/checkout@v4
        with:
          ref: master
          path: control
          persist-credentials: false
      - name: Checkout result authority
        uses: actions/checkout@v4
        with:
          ref: zel-data-expansion-results-v1
          path: results
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - id: gate
        name: {TOKEN} — require current proposal lineage
        run: |
          set -euo pipefail
          mkdir -p out
          proposal=results/runtime_results/zel/ai_research_control_plane_v1/latest.json
          predecessor={binding.predecessor_path}
          if [ ! -s "$proposal" ] || [ ! -s "$predecessor" ]; then
            echo 'ready=false' >> "$GITHUB_OUTPUT"
            python - <<'PY'
          import json
          from datetime import datetime,timezone
          from pathlib import Path
          Path('out/ai_control_gate.json').write_text(json.dumps({{
            'schema_version':'zel.ai.control_gate.receipt.v1',
            'generated_at':datetime.now(timezone.utc).isoformat(),
            'state':'HOLD_AI_CONTROL_GATE_INPUT_MISSING',
            'stage_id':'{binding.stage_id}',
            'runtime_mutated':False,
            'selection_authority':False,
            'promotion_authority':False,
            'execution_authority':'NONE',
            'order_authority':'BLOCKED',
            'action':'hold'
          }},indent=2,sort_keys=True)+'\\n')
          PY
            exit 0
          fi
          predecessor_sha=$(sha256sum "$predecessor" | awk '{{print $1}}')
          STAGE_ID='{binding.stage_id}' PREDECESSOR_SHA="$predecessor_sha" PROPOSAL="$proposal" python - <<'PY'
          import json,os
          from pathlib import Path
          p=json.loads(Path(os.environ['PROPOSAL']).read_text())
          ctx=p.get('gate_context')
          assert isinstance(ctx,dict),p
          assert ctx.get('stage_id')==os.environ['STAGE_ID'],ctx
          assert ctx.get('predecessor_receipt_sha256')==os.environ['PREDECESSOR_SHA'],ctx
          epoch=str(ctx.get('epoch_id') or '')
          assert epoch,ctx
          Path('/tmp/zel_ai_epoch').write_text(epoch)
          PY
          epoch=$(cat /tmp/zel_ai_epoch)
          if python control/backend/tools/zel_ai_control_gate_v1.py verify \
            --policy control/backend/research/zel_ai_research_control_plane_v1.json \
            --proposal-receipt "$proposal" \
            --stage-id '{binding.stage_id}' \
            --epoch-id "$epoch" \
            --predecessor-receipt-sha256 "$predecessor_sha" \
            --out out/ai_control_gate.json; then
            echo 'ready=true' >> "$GITHUB_OUTPUT"
          else
            echo 'ready=false' >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: zel-ai-control-gate-{binding.target_job}-${{{{ github.run_id }}}}
          path: out/ai_control_gate.json
          if-no-files-found: error
          retention-days: 90

'''


def patch_target_header(text: str, binding: Binding) -> str:
    header = re.search(rf"(?m)^  {re.escape(binding.target_job)}:\n(?P<body>(?:    .*\n){{0,8}})", text)
    if not header:
        raise ValueError(f"TARGET_JOB_NOT_FOUND:{binding.filename}:{binding.target_job}")
    body = header.group("body")
    lines = body.splitlines()
    needs_name = f"ai_control_{binding.target_job}"
    changed = []
    if_seen = False
    needs_seen = False
    for line in lines:
        if line.startswith("    if:"):
            if_seen = True
            if f"needs.{needs_name}.outputs.ready" not in line:
                line = line + f" && needs.{needs_name}.outputs.ready == 'true'"
        elif line.startswith("    needs:"):
            needs_seen = True
            current = line.split(":", 1)[1].strip()
            if current.startswith("["):
                items = [x.strip() for x in current.strip("[]").split(",") if x.strip()]
            else:
                items = [current]
            if needs_name not in items:
                items.append(needs_name)
            line = "    needs: [" + ", ".join(items) + "]"
        changed.append(line)
    if not if_seen:
        changed.insert(0, f"    if: github.event_name != 'pull_request' && needs.{needs_name}.outputs.ready == 'true'")
    if not needs_seen:
        changed.insert(1 if changed and changed[0].startswith("    if:") else 0, f"    needs: [{needs_name}]")
    replacement = f"  {binding.target_job}:\n" + "\n".join(changed) + "\n"
    return text[: header.start()] + replacement + text[header.end() :]


def patch_file(path: Path, binding: Binding) -> bool:
    text = path.read_text(encoding="utf-8")
    if f"name: {TOKEN} — require current proposal lineage" in text:
        return False
    marker = f"  {binding.target_job}:\n"
    if marker not in text:
        raise ValueError(f"TARGET_MARKER_NOT_FOUND:{path}")
    text = text.replace(marker, gate_job(binding) + marker, 1)
    text = patch_target_header(text, binding)
    path.write_text(text, encoding="utf-8")
    return True


def apply(root: Path) -> dict[str, object]:
    changed: list[str] = []
    for binding in BINDINGS:
        path = root / binding.filename
        if not path.is_file():
            raise FileNotFoundError(path)
        if patch_file(path, binding):
            changed.append(binding.filename)
    return {"state": "PASS_AI_CONTROL_WORKFLOWS_BOUND", "changed": changed, "binding_count": len(BINDINGS)}


def self_test() -> None:
    sample = """name: sample\njobs:\n  validate:\n    runs-on: ubuntu-latest\n  prerequisite:\n    needs: validate\n  direct:\n    if: github.event_name != 'pull_request' && needs.prerequisite.outputs.ready == 'true'\n    needs: [validate, prerequisite]\n    runs-on: ubuntu-latest\n"""
    binding = BINDINGS[0]
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / binding.filename
        path.write_text(sample, encoding="utf-8")
        assert patch_file(path, binding) is True
        result = path.read_text()
        assert TOKEN in result
        assert "needs.ai_control_direct.outputs.ready == 'true'" in result
        assert "needs: [validate, prerequisite, ai_control_direct]" in result
        assert patch_file(path, binding) is False
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflows-root", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.workflows_root is None:
        parser.error("workflows-root required")
    result = apply(args.workflows_root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
