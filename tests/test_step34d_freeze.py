from pathlib import Path
import json

from scripts.verify_step34d_freeze import verify


def test_frozen_sources_and_parameters_still_match():
    root = Path(__file__).resolve().parents[1]
    result = verify(root)
    assert result["passed"], result["errors"]
    assert result["source_files_checked"] >= 20


def test_windows_crlf_checkout_keeps_same_freeze(tmp_path):
    root = Path(__file__).resolve().parents[1]
    relative = Path("evaluation/step34d/detector_v2_freeze.json")
    manifest = json.loads((root / relative).read_text(encoding="utf-8"))
    for filename in manifest["source_sha256"]:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / filename).read_bytes())
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((root / relative).read_bytes())
    source = tmp_path / "scripts/run_step34d_detector_v2.py"
    source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert verify(tmp_path)["passed"]
