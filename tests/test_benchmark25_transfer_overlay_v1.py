import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REBUILD = ROOT / "backend/research/rebuild"
if str(REBUILD) not in sys.path:
    sys.path.insert(0, str(REBUILD))
from benchmark25_transfer_overlay_v1 import self_test  # noqa: E402

CONTRACT = ROOT / "backend/research/rebuild/benchmark25_transfer_contract_v1.json"
MATRIX = (
    ROOT / "backend/research/rebuild/benchmark25_transfer_implementation_matrix_v1.json"
)


def test_benchmark25_contract_and_implementation_are_exact_25():
    contract = json.loads(CONTRACT.read_text())
    matrix = json.loads(MATRIX.read_text())
    assert len(contract["strategies"]) == 25
    assert matrix["state"] == "PASS_25_OF_25_1_TO_1"
    assert matrix["unimplemented_count"] == 0
    assert self_test(contract) == 0
    for sid, spec in contract["strategies"].items():
        implemented = [
            x["transfer"] for x in matrix["strategies"][sid]["transfer_implementation"]
        ]
        assert implemented == spec["transfer"]
