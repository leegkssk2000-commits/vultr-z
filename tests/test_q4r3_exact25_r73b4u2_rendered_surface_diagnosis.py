from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_r73b4u2_rendered_surface_diagnosis.py"
SPEC = importlib.util.spec_from_file_location("r73b4u2", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_json_path_literals_are_deduplicated() -> None:
    text = "A='/a/one.json'\nB='/a/one.json'\nC=\"/b/two.jsonl\"\n"
    assert module.json_path_literals(text) == ["/a/one.json", "/b/two.jsonl"]


def test_numbered_hits_preserves_line_numbers_and_context() -> None:
    text = "one\ntwo\nlast_close = data.get('last_close')\nfour\n"
    hits = module.numbered_hits(text, ("last_close",), context=1)
    assert [item["line"] for item in hits] == [2, 3, 4]


def test_writer_map_accepts_writers_list() -> None:
    payload = {
        "writers": [
            {"writer_id": "VV", "strategy": "vwap_revert"},
            {"writer_id": "TR", "strategy": "trend_rider"},
        ]
    }
    assert module.writer_map(payload) == {"VV": "vwap_revert", "TR": "trend_rider"}


def test_metric_uses_first_present_alias() -> None:
    assert module.metric({"closed": 0}, "closed_count", "closed", default=-1) == 0
    assert module.metric({}, "closed_count", default=-1) == -1


def test_render_term_detection_covers_known_bottom_residue() -> None:
    text = "recent_rows={recent_rows} last12={last12} wr={wr} ev={ev} last_close={last_close}"
    count = sum(text.lower().count(term.lower()) for term in module.RENDER_TERMS)
    assert count >= 5
