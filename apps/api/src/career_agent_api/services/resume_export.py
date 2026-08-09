from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from career_agent_api.models.enums import PreferredLanguage
from career_agent_api.schemas.api import (
    ResumeDraftContent,
    ResumeDraftItem,
    ResumeDraftSection,
    ResumeExportContact,
)

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
REGULAR_FONT = ASSET_DIR / "noto-sans-arabic-400-normal.woff2"
BOLD_FONT = ASSET_DIR / "noto-sans-arabic-700-normal.woff2"

INK = (17, 45, 69)
MUTED = (91, 111, 128)
EMERALD = (5, 140, 99)
BORDER = (214, 223, 231)

_COMPACT_SECTION_KEYS = frozenset({"certification", "skill", "language"})
_ATS_SECTION_ORDER = {
    key: index
    for index, key in enumerate(
        (
            "education",
            "experience",
            "trading_experience",
            "certification",
            "skill",
            "language",
            "project",
            "achievement",
        )
    )
}


@dataclass(frozen=True, slots=True)
class _ResumeLayoutProfile:
    name: str
    margin: float
    top_margin: float
    bottom_margin: float
    name_size: float
    name_line_height: float
    headline_size: float
    headline_line_height: float
    contact_size: float
    contact_line_height: float
    section_title_size: float
    section_title_line_height: float
    item_title_size: float
    item_title_line_height: float
    body_size: float
    body_line_height: float
    metadata_size: float
    metadata_line_height: float
    header_gap: float
    divider_gap: float
    section_gap: float
    item_gap: float


_COMFORTABLE = _ResumeLayoutProfile(
    name="comfortable",
    margin=14,
    top_margin=14,
    bottom_margin=14,
    name_size=18,
    name_line_height=7,
    headline_size=10.5,
    headline_line_height=5,
    contact_size=9,
    contact_line_height=4.2,
    section_title_size=11,
    section_title_line_height=5,
    item_title_size=9.8,
    item_title_line_height=4.4,
    body_size=9.5,
    body_line_height=4.3,
    metadata_size=9,
    metadata_line_height=4,
    header_gap=2,
    divider_gap=2,
    section_gap=2.2,
    item_gap=1,
)

_COMPACT = _ResumeLayoutProfile(
    name="compact",
    margin=12,
    top_margin=12,
    bottom_margin=12,
    name_size=17,
    name_line_height=6.4,
    headline_size=10,
    headline_line_height=4.6,
    contact_size=9,
    contact_line_height=3.8,
    section_title_size=10.5,
    section_title_line_height=4.5,
    item_title_size=9.5,
    item_title_line_height=4,
    body_size=9,
    body_line_height=3.8,
    metadata_size=9,
    metadata_line_height=3.8,
    header_gap=1.3,
    divider_gap=1.4,
    section_gap=1.4,
    item_gap=0.5,
)


@dataclass(frozen=True, slots=True)
class ResumePdfRenderResult:
    """Rendered PDF plus the layout decision used to produce it."""

    content: bytes
    page_count: int
    layout_profile: str


def _clean(value: str | None, *, limit: int | None = 4_000) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    cleaned = " ".join(cleaned.split())
    return cleaned if limit is None else cleaned[:limit]


def _set_font(pdf: FPDF, *, bold: bool = False, size: float = 10) -> None:
    pdf.set_font("NotoResume", style="B" if bold else "", size=size)


def _ensure_space(pdf: FPDF, height: float) -> None:
    """Keep a measured block together when it can fit on an otherwise empty page."""

    usable_page_height = pdf.h - pdf.t_margin - pdf.b_margin
    if height <= usable_page_height and pdf.will_page_break(height):
        pdf.add_page()


def _measure_text_height(
    pdf: FPDF,
    value: str,
    *,
    align: str,
    size: float,
    bold: bool = False,
    line_height: float,
    limit: int | None = 4_000,
) -> float:
    value = _clean(value, limit=limit)
    if not value:
        return 0
    _set_font(pdf, bold=bold, size=size)
    height = pdf.multi_cell(
        0,
        line_height,
        text=value,
        align=align,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        dry_run=True,
        output=MethodReturnValue.HEIGHT,
    )
    return float(height)


def _text(
    pdf: FPDF,
    value: str,
    *,
    align: str,
    size: float = 10,
    bold: bool = False,
    color: tuple[int, int, int] = INK,
    line_height: float = 5.4,
    limit: int | None = 4_000,
) -> None:
    value = _clean(value, limit=limit)
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


def _item_heading(item: ResumeDraftItem) -> str:
    parts = [_clean(item.title, limit=None), _clean(item.organization, limit=None)]
    return " | ".join(part for part in parts if part)


def _item_metadata(item: ResumeDraftItem) -> str:
    parts = [_clean(item.date_range, limit=None), _clean(item.location, limit=None)]
    return " | ".join(part for part in parts if part)


def _compact_item_text(
    item: ResumeDraftItem,
    *,
    first_bullet_only: bool = False,
) -> str:
    parts = [_item_heading(item), _item_metadata(item)]
    text = " | ".join(part for part in parts if part)
    bullets = item.bullets[:1] if first_bullet_only else item.bullets
    cleaned_bullets = [_clean(bullet, limit=1_000) for bullet in bullets]
    cleaned_bullets = [bullet for bullet in cleaned_bullets if bullet]
    if cleaned_bullets:
        text = f"{text}: {'; '.join(cleaned_bullets)}" if text else "; ".join(cleaned_bullets)
    return text


def _narrative_item_lead_height(
    pdf: FPDF,
    item: ResumeDraftItem,
    *,
    align: str,
    profile: _ResumeLayoutProfile,
) -> float:
    height = _measure_text_height(
        pdf,
        _item_heading(item),
        align=align,
        size=profile.item_title_size,
        bold=True,
        line_height=profile.item_title_line_height,
        limit=None,
    )
    height += _measure_text_height(
        pdf,
        _item_metadata(item),
        align=align,
        size=profile.metadata_size,
        line_height=profile.metadata_line_height,
        limit=None,
    )
    if item.bullets:
        height += _measure_text_height(
            pdf,
            f"- {_clean(item.bullets[0], limit=1_000)}",
            align=align,
            size=profile.body_size,
            line_height=profile.body_line_height,
            limit=None,
        )
    return height


def _section_lead_height(
    pdf: FPDF,
    section: ResumeDraftSection,
    *,
    align: str,
    profile: _ResumeLayoutProfile,
) -> float:
    height = profile.section_gap + profile.divider_gap
    height += _measure_text_height(
        pdf,
        section.title,
        align=align,
        size=profile.section_title_size,
        bold=True,
        line_height=profile.section_title_line_height,
        limit=None,
    )
    first_item = section.items[0]
    if section.key in _COMPACT_SECTION_KEYS:
        height += _measure_text_height(
            pdf,
            _compact_item_text(first_item, first_bullet_only=True),
            align=align,
            size=profile.body_size,
            line_height=profile.body_line_height,
            limit=None,
        )
    else:
        height += _narrative_item_lead_height(
            pdf,
            first_item,
            align=align,
            profile=profile,
        )
    return height


def _render_section_header(
    pdf: FPDF,
    section: ResumeDraftSection,
    *,
    align: str,
    profile: _ResumeLayoutProfile,
) -> None:
    _ensure_space(
        pdf,
        _section_lead_height(pdf, section, align=align, profile=profile),
    )
    pdf.ln(profile.section_gap)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.35)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(profile.divider_gap)
    _text(
        pdf,
        section.title,
        align=align,
        size=profile.section_title_size,
        bold=True,
        color=EMERALD,
        line_height=profile.section_title_line_height,
        limit=None,
    )


def _render_compact_section(
    pdf: FPDF,
    section: ResumeDraftSection,
    *,
    align: str,
    profile: _ResumeLayoutProfile,
) -> None:
    # Low-density facts remain in normal reading order, but share wrapped lines instead of
    # paying the vertical cost of a separate heading, metadata row, and bullet block each.
    compact_text = "  •  ".join(_compact_item_text(item) for item in section.items)
    _text(
        pdf,
        compact_text,
        align=align,
        size=profile.body_size,
        line_height=profile.body_line_height,
        limit=None,
    )


def _render_narrative_section(
    pdf: FPDF,
    section: ResumeDraftSection,
    *,
    align: str,
    profile: _ResumeLayoutProfile,
) -> None:
    for item in section.items:
        _ensure_space(
            pdf,
            _narrative_item_lead_height(pdf, item, align=align, profile=profile),
        )
        _text(
            pdf,
            _item_heading(item),
            align=align,
            size=profile.item_title_size,
            bold=True,
            line_height=profile.item_title_line_height,
            limit=None,
        )
        metadata = _item_metadata(item)
        if metadata:
            _text(
                pdf,
                metadata,
                align=align,
                size=profile.metadata_size,
                color=MUTED,
                line_height=profile.metadata_line_height,
                limit=None,
            )
        for bullet in item.bullets:
            _text(
                pdf,
                f"- {_clean(bullet, limit=1_000)}",
                align=align,
                size=profile.body_size,
                color=INK,
                line_height=profile.body_line_height,
                limit=None,
            )
        pdf.ln(profile.item_gap)


def _ordered_sections(draft: ResumeDraftContent) -> list[ResumeDraftSection]:
    indexed_sections = list(enumerate(draft.sections))
    indexed_sections.sort(
        key=lambda pair: (_ATS_SECTION_ORDER.get(pair[1].key, len(_ATS_SECTION_ORDER)), pair[0])
    )
    return [section for _, section in indexed_sections]


def _render_with_profile(
    *,
    profile_name: str,
    city: str | None,
    language: PreferredLanguage,
    draft: ResumeDraftContent,
    contact: ResumeExportContact,
    layout: _ResumeLayoutProfile,
) -> ResumePdfRenderResult:
    rtl = language is PreferredLanguage.AR
    align = "R" if rtl else "L"
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(layout.margin, layout.top_margin, layout.margin)
    pdf.set_auto_page_break(auto=True, margin=layout.bottom_margin)
    pdf.set_title(f"Resume - {_clean(profile_name, limit=200)}")
    pdf.set_author(_clean(profile_name, limit=200))
    pdf.set_creator("AI Career Agent")
    pdf.add_font("NotoResume", fname=str(REGULAR_FONT))
    pdf.add_font("NotoResume", style="B", fname=str(BOLD_FONT))
    pdf.add_page()
    pdf.set_text_shaping(True, direction="rtl" if rtl else "ltr")

    _text(
        pdf,
        profile_name,
        align=align,
        size=layout.name_size,
        bold=True,
        line_height=layout.name_line_height,
        limit=None,
    )
    _text(
        pdf,
        draft.headline,
        align=align,
        size=layout.headline_size,
        bold=True,
        color=EMERALD,
        line_height=layout.headline_line_height,
        limit=None,
    )
    contact_parts = [
        _clean(city, limit=120),
        _clean(contact.email, limit=320),
        _clean(contact.phone, limit=80),
        _clean(contact.linkedin, limit=500),
    ]
    contact_line = " | ".join(part for part in contact_parts if part)
    if contact_line:
        _text(
            pdf,
            contact_line,
            align=align,
            size=layout.contact_size,
            color=MUTED,
            line_height=layout.contact_line_height,
            limit=None,
        )

    pdf.ln(layout.header_gap)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.35)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(layout.divider_gap)

    summary_title = "الملخص المهني" if rtl else "Professional summary"
    summary_lead_height = _measure_text_height(
        pdf,
        summary_title,
        align=align,
        size=layout.section_title_size,
        bold=True,
        line_height=layout.section_title_line_height,
        limit=None,
    ) + layout.body_line_height
    _ensure_space(pdf, summary_lead_height)
    _text(
        pdf,
        summary_title,
        align=align,
        size=layout.section_title_size,
        bold=True,
        color=EMERALD,
        line_height=layout.section_title_line_height,
        limit=None,
    )
    _text(
        pdf,
        draft.professional_summary,
        align=align,
        size=layout.body_size,
        color=INK,
        line_height=layout.body_line_height,
        limit=None,
    )

    for section in _ordered_sections(draft):
        _render_section_header(pdf, section, align=align, profile=layout)
        if section.key in _COMPACT_SECTION_KEYS:
            _render_compact_section(pdf, section, align=align, profile=layout)
        else:
            _render_narrative_section(pdf, section, align=align, profile=layout)

    return ResumePdfRenderResult(
        content=bytes(pdf.output()),
        page_count=pdf.pages_count,
        layout_profile=layout.name,
    )


def render_resume_pdf_with_layout(
    *,
    profile_name: str,
    city: str | None,
    language: PreferredLanguage,
    draft: ResumeDraftContent,
    contact: ResumeExportContact,
) -> ResumePdfRenderResult:
    """Render for one page when readable profiles allow it, without dropping content."""

    if not REGULAR_FONT.is_file() or not BOLD_FONT.is_file():
        raise RuntimeError("Bundled resume font is unavailable")

    comfortable = _render_with_profile(
        profile_name=profile_name,
        city=city,
        language=language,
        draft=draft,
        contact=contact,
        layout=_COMFORTABLE,
    )
    if comfortable.page_count == 1:
        return comfortable

    compact = _render_with_profile(
        profile_name=profile_name,
        city=city,
        language=language,
        draft=draft,
        contact=contact,
        layout=_COMPACT,
    )
    if compact.page_count < comfortable.page_count:
        return compact
    return comfortable


def render_resume_pdf(
    *,
    profile_name: str,
    city: str | None,
    language: PreferredLanguage,
    draft: ResumeDraftContent,
    contact: ResumeExportContact,
) -> bytes:
    """Backward-compatible byte-only PDF renderer."""

    return render_resume_pdf_with_layout(
        profile_name=profile_name,
        city=city,
        language=language,
        draft=draft,
        contact=contact,
    ).content
