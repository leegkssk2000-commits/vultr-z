from __future__ import annotations

from pathlib import Path

TARGET = Path('.github/workflows/zel-composite-post-terminal-controller-v1.yml')

AI_JOB = r'''  ai_control:
    if: github.event_name != 'pull_request'
    needs: validate
    runs-on: ubuntu-latest
    timeout-minutes: 10
    outputs:
      ready: ${{ steps.ai_gate.outputs.ready }}
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
      - id: ai_gate
        name: ZEL_AI_CONTROL_GATE_V1 — verify terminal-bound Composite authorization
        run: |
          set -euo pipefail
          mkdir -p out
          stage_id=COMPOSITE_POST_TERMINAL
          proposal=results/runtime_results/zel/ai_research_control_plane_v1/composite_post_terminal/latest.json
          predecessor=results/runtime_results/zel/data_b_1m_v2_watch_v1/latest.json
          if [ ! -s "$proposal" ] || [ ! -s "$predecessor" ]; then
            echo 'ready=false' >> "$GITHUB_OUTPUT"
            STAGE_ID="$stage_id" python - <<'PY'
          import json,os
          from datetime import datetime,timezone
          from pathlib import Path
          Path('out/ai_gate.json').write_text(json.dumps({
            'schema_version':'zel.ai.control_gate.receipt.v1',
            'generated_at':datetime.now(timezone.utc).isoformat(),
            'state':'HOLD_AI_CONTROL_GATE_INPUT_MISSING',
            'stage_id':os.environ['STAGE_ID'],
            'runtime_mutated':False,
            'selection_authority':False,
            'promotion_authority':False,
            'execution_authority':'NONE',
            'order_authority':'BLOCKED',
            'action':'hold'
          },indent=2,sort_keys=True)+'\n')
          PY
            exit 0
          fi
          STAGE_ID="$stage_id" PROPOSAL="$proposal" PREDECESSOR="$predecessor" python - <<'PY'
          import hashlib,json,os
          from pathlib import Path
          proposal_path=Path(os.environ['PROPOSAL'])
          predecessor_path=Path(os.environ['PREDECESSOR'])
          proposal=json.loads(proposal_path.read_text())
          predecessor=json.loads(predecessor_path.read_text())
          context=proposal.get('gate_context')
          assert isinstance(context,dict),proposal
          assert proposal.get('state')=='PASS_AI_RESEARCH_CONTROL_PLANE',proposal
          assert proposal.get('economic_claim_allowed') is False,proposal
          assert proposal.get('candidate_execution_allowed') is False,proposal
          assert proposal.get('selection_authority') is False,proposal
          assert proposal.get('promotion_authority') is False,proposal
          assert proposal.get('execution_authority')=='NONE',proposal
          assert proposal.get('order_authority')=='BLOCKED',proposal
          assert context.get('stage_id')==os.environ['STAGE_ID'],context
          assert context.get('broker_stage_id')==os.environ['STAGE_ID'],context
          assert context.get('target_workflow')=='zel-composite-post-terminal-controller-v1.yml',context
          assert predecessor.get('state')=='PASS_DATA_B_1M_V2_TERMINAL',predecessor
          assert predecessor.get('terminal_complete') is True,predecessor
          assert predecessor.get('runtime_mutated') is False,predecessor
          assert predecessor.get('execution_authority')=='NONE',predecessor
          assert predecessor.get('order_authority')=='BLOCKED',predecessor
          predecessor_sha=hashlib.sha256(predecessor_path.read_bytes()).hexdigest()
          assert context.get('predecessor_receipt_sha256')==predecessor_sha,(context,predecessor_sha)
          epoch=str(context.get('epoch_id') or '')
          assert epoch,context
          Path('/tmp/zel_composite_ai_epoch').write_text(epoch)
          Path('/tmp/zel_composite_predecessor_sha').write_text(predecessor_sha)
          PY
          epoch=$(cat /tmp/zel_composite_ai_epoch)
          predecessor_sha=$(cat /tmp/zel_composite_predecessor_sha)
          if python control/backend/tools/zel_ai_control_gate_v1.py verify \
            --policy control/backend/research/zel_ai_research_control_plane_v1.json \
            --proposal-receipt "$proposal" \
            --stage-id "$stage_id" \
            --epoch-id "$epoch" \
            --predecessor-receipt-sha256 "$predecessor_sha" \
            --out out/ai_gate.json; then
            echo 'ready=true' >> "$GITHUB_OUTPUT"
          else
            echo 'ready=false' >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: composite-post-terminal-ai-gate-${{ github.run_id }}
          path: out/ai_gate.json
          if-no-files-found: error
          retention-days: 90

'''


def main() -> int:
    text = TARGET.read_text(encoding='utf-8')
    if 'id: ai_gate' in text and 'COMPOSITE_POST_TERMINAL' in text:
        print('PASS_ALREADY_BOUND')
        return 0

    marker = '\n  execute:\n'
    if marker not in text:
        raise SystemExit('EXECUTE_JOB_MARKER_MISSING')
    text = text.replace(marker, '\n' + AI_JOB + '  execute:\n', 1)

    old_header = '''  execute:
    if: >-
      github.event_name != 'pull_request' &&
      (github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success')
    needs: validate
'''
    new_header = '''  execute:
    if: >-
      github.event_name != 'pull_request' &&
      needs.ai_control.outputs.ready == 'true' &&
      (github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success')
    needs: [validate, ai_control]
'''
    if old_header not in text:
        raise SystemExit('EXECUTE_HEADER_MARKER_MISSING')
    text = text.replace(old_header, new_header, 1)

    static_marker = '''          for marker in required:
              assert marker in text,marker
          print('PASS_COMPOSITE_POST_TERMINAL_CONTROLLER_STATIC')
'''
    static_replacement = '''          for marker in required:
              assert marker in text,marker
          assert 'ZEL_AI_CONTROL_GATE_V1' in text
          assert 'zel_ai_control_gate_v1.py verify' in text
          assert '--proposal-receipt' in text
          assert '--stage-id' in text
          assert 'COMPOSITE_POST_TERMINAL' in text
          assert "needs.ai_control.outputs.ready == 'true'" in text
          assert 'needs: [validate, ai_control]' in text
          print('PASS_COMPOSITE_POST_TERMINAL_CONTROLLER_STATIC')
'''
    if static_marker not in text:
        raise SystemExit('STATIC_VALIDATION_MARKER_MISSING')
    text = text.replace(static_marker, static_replacement, 1)

    required_fragments = (
        'ZEL_AI_CONTROL_GATE_V1',
        'zel_ai_control_gate_v1.py verify',
        '--proposal-receipt',
        '--stage-id',
        'COMPOSITE_POST_TERMINAL',
        "needs.ai_control.outputs.ready == 'true'",
        'needs: [validate, ai_control]',
        'PASS_DATA_B_1M_V2_TERMINAL',
    )
    for fragment in required_fragments:
        if fragment not in text:
            raise SystemExit(f'PATCH_FRAGMENT_MISSING:{fragment}')
    TARGET.write_text(text, encoding='utf-8')
    print('PASS_COMPOSITE_CONTROLLER_AI_GATE_BOUND')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
