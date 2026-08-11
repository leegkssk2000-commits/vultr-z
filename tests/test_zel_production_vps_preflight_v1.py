from pathlib import Path

import ops.zel_production_vps_preflight_v1 as preflight


def write_release(root: Path, content: bytes) -> Path:
    marker = root / "backend" / "production" / "zel_production_spine_v1.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(content)
    return marker


def test_preferred_exact_root_wins_identical_release_tie(tmp_path, monkeypatch):
    releases = tmp_path / "releases"
    a = releases / "aaa"
    b = releases / "bbb"
    marker_a = write_release(a, b"same-master")
    marker_b = write_release(b, b"same-master")
    current = tmp_path / "current"
    current.symlink_to(b, target_is_directory=True)

    expected = {
        "backend/production/zel_production_spine_v1.py": preflight.sha256_file(marker_b),
    }
    monkeypatch.setattr(preflight, "_find_files", lambda pattern: [marker_a, marker_b])

    selected, ranked = preflight.discover_roots(current, expected)
    assert selected == b.resolve()
    assert len(ranked) == 2
    assert ranked[0]["score"] == ranked[1]["score"]
    assert all(row["exact_master_matches"] == 1 for row in ranked)


def test_ambiguous_tie_without_exact_preferred_still_holds(tmp_path, monkeypatch):
    releases = tmp_path / "releases"
    a = releases / "aaa"
    b = releases / "bbb"
    marker_a = write_release(a, b"same-master")
    marker_b = write_release(b, b"same-master")
    preferred = tmp_path / "missing-current"

    expected = {
        "backend/production/zel_production_spine_v1.py": preflight.sha256_file(marker_a),
    }
    monkeypatch.setattr(preflight, "_find_files", lambda pattern: [marker_a, marker_b])

    selected, ranked = preflight.discover_roots(preferred, expected)
    assert selected is None
    assert len(ranked) == 2
    assert ranked[0]["score"] == ranked[1]["score"]
