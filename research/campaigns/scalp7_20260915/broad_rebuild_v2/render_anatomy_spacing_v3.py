"""Create readable presentation copies of frozen SVG evidence; no data replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent / "anatomy_binding_repair"
NS = "{http://www.w3.org/2000/svg}"


def main():
    ET.register_namespace("", NS[1:-1])
    out = BASE / "readable"
    out.mkdir(exist_ok=True)
    manifest = []
    for source in sorted(BASE.glob("*.svg")):
        original = source.read_bytes()
        svg = ET.fromstring(original)
        group = svg.find(NS + "g")
        assert group is not None
        elements = list(group)
        starts = [
            i
            for i, element in enumerate(elements)
            if element.tag == NS + "text"
            and element.get("font-size") == "12"
            and " side=" in (element.text or "")
        ]
        assert len(starts) == 10, source.name
        for element in elements:
            group.remove(element)
        for element in elements[: starts[0]]:
            group.append(element)
        for panel, begin in enumerate(starts):
            end = starts[panel + 1] if panel + 1 < len(starts) else len(elements)
            wrapper = ET.SubElement(
                group, NS + "g", {"transform": f"translate(0,{50 * panel})"}
            )
            for element in elements[begin:end]:
                wrapper.append(element)
        height = int(svg.get("height")) + 50 * (len(starts) - 1)
        svg.set("height", str(height))
        svg.set("viewBox", f"0 0 1140 {height}")
        svg.find(NS + "rect").set("height", str(height))
        result = ET.tostring(svg, encoding="utf-8")
        target = out / source.name
        target.write_bytes(result)
        assert source.read_bytes() == original
        manifest.append(
            {
                "source": source.name,
                "source_sha256": hashlib.sha256(original).hexdigest(),
                "presentation": "readable/" + source.name,
                "presentation_sha256": hashlib.sha256(result).hexdigest(),
                "panels": len(starts),
                "extra_spacing_px_per_panel": 50,
            }
        )
    assert len(manifest) == 12
    (out / "PRESENTATION_MANIFEST_V3.json").write_text(
        json.dumps(
            {
                "schema": "scalp7.anatomy.presentation_spacing.v3",
                "purpose": "Separate overlapping source-range footers from the next panel title",
                "data_or_geometry_changed": False,
                "only_panel_translation_and_canvas_height_changed": True,
                "original_frozen_evidence_preserved": True,
                "economic_replays": 0,
                "files": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "readable_svgs": len(manifest),
                "panels": sum(x["panels"] for x in manifest),
                "source_files_unchanged": True,
            }
        )
    )


if __name__ == "__main__":
    main()
