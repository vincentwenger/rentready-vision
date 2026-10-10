"""Step 52: report frontend uses batch frame URLs."""

from pathlib import Path


def report_rendering_source():
    html = Path("web/index.html").read_text(encoding="utf-8")

    return html.split(
        "async function renderResults(id, response) {", 1
    )[1].split(
        "// Step 53: retain the active upload controller", 1
    )[0]


def test_report_uses_one_batch_frame_url_request():
    source = report_rendering_source()

    assert source.count(
        "await api(`/inspections/${id}/frames/urls`)"
    ) == 1

    assert "/frames/${frame.index}/url" not in source
    assert "Promise.all(response.keyframes" not in source


def test_report_renders_each_frame_from_batch_mapping():
    source = report_rendering_source()

    assert "new Map(" in source
    assert "Number(frame.index)" in source
    assert "const cards = response.keyframes.map(" in source
    assert "img.src = frameUrl;" in source
    assert "Missing frame URL for retained frame" in source


def test_existing_frame_url_endpoint_is_preserved():
    backend = Path(
        "app/routers/inspections.py"
    ).read_text(encoding="utf-8")

    assert '@router.get("/{inspection_id}/frames/urls")' in backend
    assert '@router.get("/{inspection_id}/frames/{frame_index}/url")' in backend
