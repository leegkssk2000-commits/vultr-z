from __future__ import annotations

from pathlib import Path

from zel_bind_composite_controller_ai_gate_v1 import AI_JOB

TARGET = Path('.github/workflows/zel-composite-post-terminal-controller-v1.yml')


def main() -> int:
    text = TARGET.read_text(encoding='utf-8')
    if 'id: ai_gate' in text and 'COMPOSITE_POST_TERMINAL' in text:
        print('PASS_ALREADY_BOUND')
        return 0

    marker = '\n  execute:\n'
    if marker not in text:
        raise SystemExit('EXECUTE_JOB_MARKER_MISSING')
    text = text.replace(marker, '\n' + AI_JOB + '  execute:\n', 1)

    header_fragments = (
        "      github.event_name != 'pull_request' &&\n      (github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success')\n    needs: validate\n",
        "      github.event_name != 'pull_request' &&\r\n      (github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success')\r\n    needs: validate\r\n",
    )
    replacement = (
        "      github.event_name != 'pull_request' &&\n"
        "      needs.ai_control.outputs.ready == 'true' &&\n"
        "      (github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success')\n"
        "    needs: [validate, ai_control]\n"
    )
    for fragment in header_fragments:
        if fragment in text:
            text = text.replace(fragment, replacement, 1)
            break
    else:
        raise SystemExit('EXECUTE_HEADER_FRAGMENT_MISSING')

    print_marker = "          print('PASS_COMPOSITE_POST_TERMINAL_CONTROLLER_STATIC')"
    if print_marker not in text:
        raise SystemExit('STATIC_PRINT_MARKER_MISSING')
    assertions = '''          assert 'ZEL_AI_CONTROL_GATE_V1' in text
          assert 'zel_ai_control_gate_v1.py verify' in text
          assert '--proposal-receipt' in text
          assert '--stage-id' in text
          assert 'COMPOSITE_POST_TERMINAL' in text
          assert "needs.ai_control.outputs.ready == 'true'" in text
          assert 'needs: [validate, ai_control]' in text
'''
    text = text.replace(print_marker, assertions + print_marker, 1)

    required = (
        'ZEL_AI_CONTROL_GATE_V1',
        'zel_ai_control_gate_v1.py verify',
        '--proposal-receipt',
        '--stage-id',
        'COMPOSITE_POST_TERMINAL',
        "needs.ai_control.outputs.ready == 'true'",
        'needs: [validate, ai_control]',
        'PASS_DATA_B_1M_V2_TERMINAL',
    )
    for fragment in required:
        if fragment not in text:
            raise SystemExit(f'PATCH_FRAGMENT_MISSING:{fragment}')
    TARGET.write_text(text, encoding='utf-8')
    print('PASS_COMPOSITE_CONTROLLER_AI_GATE_BOUND_V2')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
