from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
NAVY = colors.HexColor("#172033")
BLUE = colors.HexColor("#1D4ED8")
GREEN = colors.HexColor("#166534")
AMBER = colors.HexColor("#92400E")
PALE_BLUE = colors.HexColor("#EFF6FF")
PALE_GREEN = colors.HexColor("#F0FDF4")
PALE_AMBER = colors.HexColor("#FFFBEB")
SLATE = colors.HexColor("#64748B")
LINE = colors.HexColor("#DCE3EE")


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("&", "&amp;"), style)


def build_front_matter(output: Path, benchmark: dict, result: dict, runtime: dict) -> None:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Eyebrow",
            parent=styles["BodyText"],
            textColor=BLUE,
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Hero",
            parent=styles["Title"],
            textColor=NAVY,
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=29,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CenteredMetric",
            parent=styles["BodyText"],
            alignment=TA_CENTER,
            textColor=NAVY,
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CenteredLabel",
            parent=styles["BodyText"],
            alignment=TA_CENTER,
            textColor=SLATE,
            fontSize=8,
            leading=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            textColor=NAVY,
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=8,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["BodyText"],
            textColor=NAVY,
            fontSize=8.3,
            leading=11.2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Tiny",
            parent=styles["BodyText"],
            textColor=NAVY,
            fontSize=7.2,
            leading=9.2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Mono",
            parent=styles["BodyText"],
            textColor=NAVY,
            fontName="Courier",
            fontSize=6.7,
            leading=8.8,
            wordWrap="CJK",
        )
    )

    doc = BaseDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.62 * inch,
        rightMargin=0.62 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.5 * inch,
        title="RentReady Vision - Step-8 Stock OpenCV 5 Baseline Evidence",
        author="RentReady Vision",
        subject="Frozen stock OpenCV 5 baseline and reproduction gate",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="content")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(doc.leftMargin, 0.38 * inch, letter[0] - doc.rightMargin, 0.38 * inch)
        canvas.setFillColor(SLATE)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(doc.leftMargin, 0.22 * inch, "RentReady Vision - Step-8 baseline front matter")
        canvas.drawRightString(letter[0] - doc.rightMargin, 0.22 * inch, f"Runtime page {document.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="front", frames=[frame], onPage=footer)])
    story = []
    story.append(paragraph("RENTREADY VISION / REPRODUCIBILITY", styles["Eyebrow"]))
    story.append(paragraph("Step-8 Stock OpenCV 5 Baseline Evidence", styles["Hero"]))
    story.append(
        Table(
            [[paragraph("GATE BLOCKED - CLEAN WORKLOAD REPRODUCTION PENDING", styles["Small"])]],
            colWidths=[doc.width],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
                    ("TEXTCOLOR", (0, 0), (-1, -1), AMBER),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#F59E0B")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        )
    )
    story.append(Spacer(1, 14))

    metrics = [
        ("31,576", "Source frames"),
        ("1,053", "1-second samples"),
        ("73", "Representatives"),
        ("56", "Scenes"),
    ]
    metric_cells = [
        [
            paragraph(value, styles["CenteredMetric"]),
            paragraph(label, styles["CenteredLabel"]),
        ]
        for value, label in metrics
    ]
    story.append(
        Table(
            [metric_cells],
            colWidths=[doc.width / 4] * 4,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                    ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#BFDBFE")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        )
    )
    story.append(Spacer(1, 14))
    story.append(paragraph("What is frozen and proven", styles["Section"]))
    proven = [
        ["Exact tracked Step-8 source", benchmark["source_snapshot"]["git_commit"]],
        ["Original archive SHA-256", benchmark["source_snapshot"]["original_archive_sha256"]],
        ["Historical evidence report SHA-256", benchmark["historical_evidence_report"]["original_report_sha256"]],
        ["Pinned clean runtime", f'CPython {runtime["python_version"]}; {runtime["cv2_distribution"]["name"]}=={runtime["cv2_distribution"]["version"]}'],
        ["Clean test suite", "25 passed"],
    ]
    story.append(key_value_table(proven, doc.width, styles, PALE_GREEN))
    story.append(Spacer(1, 12))
    story.append(paragraph("What still blocks the continuation gate", styles["Section"]))
    blockers = benchmark["gate"]["blockers"]
    blocker_text = "<br/>".join(f"- {item}" for item in blockers)
    story.append(
        Table(
            [[paragraph(blocker_text, styles["Small"])]],
            colWidths=[doc.width],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
                    ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#FCD34D")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        )
    )
    story.append(Spacer(1, 12))
    story.append(
        paragraph(
            "Judging integrity: the historical metrics are preserved exactly, but they are not represented as a clean reproduction. COOL work must not begin until the input S3 key and checksum are filled and the pinned stock runtime reproduces every invariant.",
            styles["Small"],
        )
    )

    story.append(PageBreak())
    story.append(paragraph("Runtime", styles["Hero"]))
    story.append(
        paragraph(
            "Pinned clean stock environment captured before any COOL integration. Full cv2.getBuildInformation() is saved in evaluation/runtime/cv2_build_information.txt.",
            styles["Small"],
        )
    )
    story.append(Spacer(1, 10))
    runtime_rows = [
        ["cv2.__version__", runtime["cv2_version"]],
        ["Python distribution", f'{runtime["cv2_distribution"]["name"]}=={runtime["cv2_distribution"]["version"]}'],
        ["cv2.__file__", runtime["cv2_file"]],
        ["cv2 file SHA-256", runtime["cv2_file_sha256"]],
        ["Loaded cv2 binary", runtime["cv2_binary_file"]],
        ["Loaded binary SHA-256", runtime["cv2_binary_sha256"]],
        ["Build information SHA-256", runtime["cv2_build_information_sha256"]],
        ["Python", f'{runtime["python_implementation"]} {runtime["python_version"]}'],
        ["Operating system", runtime["operating_system"]],
        ["Architecture", f'{runtime["architecture"]} / {runtime["machine"]}'],
        ["Runtime code commit", runtime["git_commit"]],
        ["Runtime repository dirty", str(runtime["git_dirty"])],
        ["Exact Step-8 source commit", benchmark["source_snapshot"]["git_commit"]],
        ["Test-video S3 key", runtime.get("input_s3_key") or "NOT RECOVERED - REQUIRED"],
    ]
    story.append(key_value_table(runtime_rows, doc.width, styles, PALE_BLUE, mono_values=True))
    story.append(Spacer(1, 12))
    story.append(paragraph("Historical environment evidence", styles["Section"]))
    historical = result["historical_runtime_evidence"]
    historical_rows = [
        ["PDF creator", result["provenance"]["evidence_report_creator"]],
        ["Python cache tag in archive", historical["python_cache_tag_found_in_archive"]],
        ["Historical OpenCV build", "NOT RECORDED IN ORIGINAL REPORT"],
        ["Interpretation", "The pinned runtime above is the reproduction target, not a retroactive claim about the unrecorded historical wheel."],
    ]
    story.append(key_value_table(historical_rows, doc.width, styles, PALE_AMBER))

    story.append(PageBreak())
    story.append(paragraph("Canonical processing parameters", styles["Hero"]))
    story.append(
        paragraph(
            "These values are loaded by scripts/run_baseline.py and are included in every run result. Model/network work is excluded.",
            styles["Small"],
        )
    )
    story.append(Spacer(1, 9))
    parameter_rows = []
    for key, value in benchmark["processing_parameters"].items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                parameter_rows.append([f"{key}.{nested_key}", str(nested_value)])
        else:
            parameter_rows.append([key, str(value)])
    midpoint = (len(parameter_rows) + 1) // 2
    left = parameter_rows[:midpoint]
    right = parameter_rows[midpoint:]
    while len(right) < len(left):
        right.append(["", ""])
    combined = [left[index] + right[index] for index in range(len(left))]
    story.append(
        Table(
            [
                [
                    "Parameter",
                    "Value",
                    "Parameter",
                    "Value",
                ]
            ]
            + [
                [
                    paragraph(row[0], styles["Tiny"]),
                    paragraph(row[1], styles["Mono"]),
                    paragraph(row[2], styles["Tiny"]),
                    paragraph(row[3], styles["Mono"]),
                ]
                for row in combined
            ],
            colWidths=[2.35 * inch, 0.65 * inch, 2.35 * inch, 0.65 * inch],
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 7.2),
                    ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ]
            ),
        )
    )
    story.append(Spacer(1, 10))
    story.append(paragraph("Expected output invariants", styles["Section"]))
    invariant_rows = [
        [key, str(value)]
        for key, value in benchmark["expected_output_invariants"].items()
    ]
    story.append(key_value_table(invariant_rows, doc.width, styles, PALE_GREEN))
    doc.build(story)


def key_value_table(
    rows: list[list[str]],
    width: float,
    styles,
    background,
    *,
    mono_values: bool = False,
) -> Table:
    body = []
    for label, value in rows:
        body.append(
            [
                paragraph(str(label), styles["Small"]),
                paragraph(str(value), styles["Mono"] if mono_values else styles["Small"]),
            ]
        )
    return Table(
        body,
        colWidths=[1.85 * inch, width - 1.85 * inch],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepend runtime evidence to the historical report.")
    parser.add_argument("--original-report", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation" / "evidence" / "RentReady_Vision_OpenCV_Step8_Baseline_Evidence.pdf",
    )
    args = parser.parse_args()
    original = args.original_report.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    benchmark = json.loads((ROOT / "evaluation" / "benchmark_manifest.json").read_text(encoding="utf-8"))
    result = json.loads((ROOT / "evaluation" / "baseline_result.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "evaluation" / "runtime" / "clean_stock_runtime.json").read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="rentready-pdf-") as temporary:
        front = Path(temporary) / "front-matter.pdf"
        build_front_matter(front, benchmark, result, runtime)
        writer = PdfWriter()
        for source in (PdfReader(front), PdfReader(original)):
            for page in source.pages:
                writer.add_page(page)
        writer.add_metadata(
            {
                "/Title": "RentReady Vision - Step-8 Stock OpenCV 5 Baseline Evidence",
                "/Author": "RentReady Vision",
                "/Subject": "Frozen baseline, runtime identity, and reproduction gate",
            }
        )
        with output.open("wb") as stream:
            writer.write(stream)

    final_reader = PdfReader(output)
    expected_pages = len(PdfReader(original).pages) + 3
    if len(final_reader.pages) != expected_pages:
        raise RuntimeError(
            f"Unexpected page count: {len(final_reader.pages)} != {expected_pages}"
        )
    print(json.dumps({"output": str(output), "pages": len(final_reader.pages)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
