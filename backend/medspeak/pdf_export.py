from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from medspeak.schema import AnalysisResult
from medspeak.speaker_display import normalize_result_speakers, normalize_transcript_speakers


class PDFGenerationError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


def _safe_text(value: str) -> str:
    return escape(value).replace("\n", "<br/>")


def _list_text(values: list[str]) -> str:
    return "<br/>".join(_safe_text(f"- {value}") for value in values) if values else _safe_text("- Not stated")


def build_report_sections(*, result: AnalysisResult, transcript: str) -> list[tuple[str, list[str]]]:
    normalized_transcript, speaker_map = normalize_transcript_speakers(transcript)
    normalized_result = normalize_result_speakers(result, speaker_map)
    timeline_rows = [
        f"{item.start} to {item.end} | {item.speaker} | {', '.join(item.intents)} | {item.text}"
        for item in normalized_result.intent_timeline
    ]
    next_steps_rows = [
        f"{item.step} | Who: {item.who} | When: {item.when}"
        for item in normalized_result.next_steps_checklist
    ]
    medications_rows = [
        f"{item.name} | Dose: {item.dose} | Frequency: {item.frequency} | Purpose: {item.purpose} | Notes: {item.notes}"
        for item in normalized_result.medications
    ]
    tests_rows = [
        f"{item.item} | Purpose: {item.purpose} | When: {item.when}"
        for item in normalized_result.tests_and_referrals
    ]
    scripts_rows = [f"{item.situation}: {item.script}" for item in normalized_result.social_scripts]
    accommodation_rows = [
        normalized_result.accommodation_card.summary,
        f"Communication: {', '.join(normalized_result.accommodation_card.communication)}",
        f"Sensory: {', '.join(normalized_result.accommodation_card.sensory)}",
        f"Processing: {', '.join(normalized_result.accommodation_card.processing)}",
        f"Support: {', '.join(normalized_result.accommodation_card.support)}",
    ]
    return [
        ("Visit Summary", [normalized_result.standard_summary, normalized_result.autism_friendly_summary]),
        ("Intent Summary", normalized_result.intent_summary),
        ("Intent Timeline", timeline_rows),
        ("Next Steps", next_steps_rows),
        ("Medications", medications_rows),
        ("Tests and Referrals", tests_rows),
        ("Questions to Ask", normalized_result.questions_to_ask),
        ("Accommodation Card", accommodation_rows),
        ("Social Scripts", scripts_rows),
        ("Uncertainties", normalized_result.uncertainties),
        ("Safety Note", [normalized_result.safety_note]),
        ("Full Redacted Transcript", [normalized_transcript or "Transcript not available."]),
    ]


def _logo_path() -> Path | None:
    candidate = Path(__file__).resolve().parents[2] / "frontend" / "public" / "Images" / "logo.png"
    return candidate if candidate.exists() else None


def _header_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d1b25a"))
    canvas.setFillColor(colors.HexColor("#213147"))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(doc.leftMargin, doc.height + doc.topMargin + 12, "MedSpeak Visit Report")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 20, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _table_from_rows(rows: list[str], body_style: ParagraphStyle, accent_color: str) -> Table:
    data = [[Paragraph(_safe_text(item), body_style)] for item in (rows or ["Not stated"])]
    table = Table(data, colWidths=[6.75 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9e5e2")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e7eceb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(accent_color)),
            ]
        )
    )
    return table


def generate_pdf_report(
    *,
    job_id: str,
    result: AnalysisResult,
    transcript: str,
    output_dir: Path,
    logger: Any,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"{job_id}.pdf"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#183247"),
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#46616e"),
        spaceAfter=8,
    )
    eyebrow_style = ParagraphStyle(
        "ReportEyebrow",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#2e9ea3"),
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "ReportSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1f6f72"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyCompact",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#213147"),
        spaceAfter=4,
    )
    transcript_style = ParagraphStyle(
        "TranscriptBody",
        parent=body_style,
        fontName="Courier",
        fontSize=8.2,
        leading=10.5,
    )

    story = []
    logo_path = _logo_path()
    if logo_path:
        story.append(Image(str(logo_path), width=0.82 * inch, height=0.82 * inch))
        story.append(Spacer(1, 6))
    story.extend(
        [
            Paragraph("MedSpeak Visit Report", title_style),
            Paragraph(f"Job ID {job_id}", eyebrow_style),
            Paragraph(
                "A structured handoff of the recorded visit. This is for note-taking and clarity, not medical advice.",
                subtitle_style,
            ),
            HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#d1b25a"), spaceBefore=6, spaceAfter=12),
        ]
    )

    sections = build_report_sections(result=result, transcript=transcript)
    for index, (title, rows) in enumerate(sections):
        if title == "Full Redacted Transcript":
            story.append(PageBreak())
        story.append(Paragraph(title, section_style))
        if title == "Visit Summary":
            story.append(
                Table(
                    [
                        [Paragraph("What happened", body_style), Paragraph(_safe_text(rows[0]), body_style)],
                        [Paragraph("Autism-friendly summary", body_style), Paragraph(_safe_text(rows[1]), body_style)],
                    ],
                    colWidths=[1.65 * inch, 5.1 * inch],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9e5e2")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e7eceb")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef8f7")),
                        ]
                    ),
                )
            )
        elif title == "Full Redacted Transcript":
            story.append(
                Table(
                    [[Paragraph(_safe_text(rows[0]), transcript_style)]],
                    colWidths=[6.75 * inch],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6fbfa")),
                            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9e5e2")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 10),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ]
                    ),
                )
            )
        else:
            story.append(_table_from_rows(rows, body_style, "#2e9ea3" if index % 2 == 0 else "#d1b25a"))
        story.append(Spacer(1, 10))

    try:
        SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=24,
            title="MedSpeak Visit Report",
            author="MedSpeak",
            subject="Grounded visit summary",
        ).build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        logger.info("PDF generated")
    except Exception as exc:
        raise PDFGenerationError(f"Could not generate PDF: {exc}") from exc

    return pdf_path
