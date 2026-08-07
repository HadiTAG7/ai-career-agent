from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from career_agent_api.models.enums import PreferredLanguage
from career_agent_api.schemas.api import ResumeDraftContent, ResumeExportContact

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
REGULAR_FONT = ASSET_DIR / "noto-sans-arabic-400-normal.woff2"
BOLD_FONT = ASSET_DIR / "noto-sans-arabic-700-normal.woff2"

INK = (17, 45, 69)
MUTED = (91, 111, 128)
EMERALD = (5, 140, 99)
BORDER = (214, 223, 231)


def _clean(value: str | None, *, limit: int = 4_000) -> str:
    if not value:
        return ""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return " ".join(value.split())[:limit]


def _set_font(pdf: FPDF, *, bold: bool = False, size: float = 10) -> None:
    pdf.set_font("NotoResume", style="B" if bold else "", size=size)


def _ensure_space(pdf: FPDF, height: float) -> None:
    if pdf.get_y() + height > pdf.h - pdf.b_margin:
        pdf.add_page()


def _text(
    pdf: FPDF,
    value: str,
    *,
    align: str,
    size: float = 10,
    bold: bool = False,
    color: tuple[int, int, int] = INK,
    line_height: float = 5.4,
) -> None:
    value = _clean(value)
    if not value:
        return
    _set_font(pdf, bold=bold, size=size)
    pdf.set_text_color(*color)
    pdf.multi_cell(
        0,
        line_height,
        text=value,
        align=align,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )


def render_resume_pdf(
    *,
    profile_name: str,
    city: str | None,
    language: PreferredLanguage,
    draft: ResumeDraftContent,
    contact: ResumeExportContact,
) -> bytes:
    if not REGULAR_FONT.is_file() or not BOLD_FONT.is_file():
        raise RuntimeError("Bundled resume font is unavailable")

    rtl = language is PreferredLanguage.AR
    align = "R" if rtl else "L"
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(17, 15, 17)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(f"Resume - {_clean(profile_name, limit=200)}")
    pdf.set_author(_clean(profile_name, limit=200))
    pdf.set_creator("AI Career Agent")
    pdf.add_font("NotoResume", fname=str(REGULAR_FONT))
    pdf.add_font("NotoResume", style="B", fname=str(BOLD_FONT))
    pdf.add_page()
    pdf.set_text_shaping(
        True,
        direction="rtl" if rtl else "ltr",
    )

    _text(pdf, profile_name, align=align, size=20, bold=True, line_height=8)
    _text(pdf, draft.headline, align=align, size=11.5, bold=True, color=EMERALD, line_height=6)
    contact_parts = [
        _clean(city, limit=120),
        _clean(contact.email, limit=320),
        _clean(contact.phone, limit=80),
        _clean(contact.linkedin, limit=500),
    ]
    contact_line = " | ".join(part for part in contact_parts if part)
    if contact_line:
        _text(pdf, contact_line, align=align, size=8.5, color=MUTED, line_height=4.8)

    pdf.ln(2)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.4)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    summary_title = "الملخص المهني" if rtl else "Professional summary"
    _text(pdf, summary_title, align=align, size=12, bold=True, color=EMERALD, line_height=6)
    _text(
        pdf,
        draft.professional_summary,
        align=align,
        size=9.5,
        color=INK,
        line_height=5.4,
    )

    for section in draft.sections:
        _ensure_space(pdf, 20)
        pdf.ln(3)
        pdf.set_draw_color(*BORDER)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        _text(pdf, section.title, align=align, size=12, bold=True, color=EMERALD, line_height=6)
        for item in section.items:
            _ensure_space(pdf, 15)
            heading = item.title
            if item.organization:
                heading = f"{heading} | {item.organization}"
            _text(pdf, heading, align=align, size=10, bold=True, line_height=5.5)
            metadata = " | ".join(
                part for part in (_clean(item.date_range), _clean(item.location)) if part
            )
            if metadata:
                _text(pdf, metadata, align=align, size=8.3, color=MUTED, line_height=4.5)
            for bullet in item.bullets:
                _text(
                    pdf,
                    f"- {_clean(bullet, limit=1_000)}",
                    align=align,
                    size=9.2,
                    color=INK,
                    line_height=5.2,
                )
            pdf.ln(1.5)

    return bytes(pdf.output())
