from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from career_agent_api.models.enums import PreferredLanguage
from career_agent_api.schemas.api import ResumeDraftContent, ResumeExportContact
from career_agent_api.services.resume_export import (
    render_resume_pdf,
    render_resume_pdf_with_layout,
)


def _hadi_like_draft() -> ResumeDraftContent:
    return ResumeDraftContent.model_validate(
        {
            "headline": "Finance Graduate | Cost Control | Investment & Trading Research",
            "professional_summary": (
                "Finance graduate with practical experience in cost control, financial reporting, "
                "and investment research. Prepared recurring management reports, analyzed more "
                "than 3,000 market observations, and taught financial-market concepts to over "
                "5,000 learners. Combines disciplined risk management with clear communication "
                "and evidence-based analysis."
            ),
            "summary_evidence_handles": ["professional", "trading", "teaching"],
            "sections": [
                {
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "id": "education_kfupm",
                            "title": "Bachelor of Science in Finance",
                            "organization": (
                                "King Fahd University of Petroleum and Minerals"
                            ),
                            "date_range": "2018 - 2025",
                            "location": "Dhahran, Saudi Arabia",
                            "bullets": [
                                "GPA: 3.2/4.0.",
                                "Relevant coursework included investments, corporate finance, "
                                "financial modeling, and risk management.",
                            ],
                            "evidence_handles": ["education"],
                        }
                    ],
                },
                {
                    "key": "experience",
                    "title": "Professional Experience",
                    "items": [
                        {
                            "id": "cost_control",
                            "title": "Cost Control Analyst",
                            "organization": "Industrial Services Company",
                            "date_range": "2025 - Present",
                            "location": "Eastern Province, Saudi Arabia",
                            "bullets": [
                                "Prepared monthly cost reports and investigated budget variances "
                                "for management review.",
                                "Reconciled 48 ledger accounts and improved the reliability of "
                                "supporting schedules.",
                            ],
                            "evidence_handles": ["professional"],
                        },
                        {
                            "id": "finance_trainee",
                            "title": "Finance Cooperative Trainee",
                            "organization": "Regional Operations Group",
                            "date_range": "2024",
                            "location": "Dammam, Saudi Arabia",
                            "bullets": [
                                "Supported eight monthly forecasts and summarized operational "
                                "drivers for the finance team.",
                                "Built Excel tracking files that reduced manual follow-up across "
                                "six reporting workstreams.",
                            ],
                            "evidence_handles": ["trainee"],
                        },
                        {
                            "id": "markets_instructor",
                            "title": "Financial Markets Instructor",
                            "organization": "Independent Education Programs",
                            "date_range": "2021 - 2024",
                            "location": "Remote",
                            "bullets": [
                                "Delivered practical market lessons to more than 5,000 learners.",
                                "Translated portfolio, valuation, and risk concepts into concise "
                                "Arabic learning materials.",
                            ],
                            "evidence_handles": ["teaching"],
                        },
                    ],
                },
                {
                    "key": "trading_experience",
                    "title": "Investment & Trading Experience",
                    "items": [
                        {
                            "id": "independent_trader",
                            "title": "Independent Investment & Trading Researcher",
                            "organization": "Personal Portfolio Research",
                            "date_range": "2018 - Present",
                            "location": "Saudi Arabia",
                            "bullets": [
                                "Reviewed more than 3,000 market observations across equities, "
                                "index products, and macroeconomic releases.",
                                "Maintained a rules-based journal covering entries, exits, "
                                "position sizing, and post-trade review.",
                                "Managed a simulated portfolio of SAR 50,000 while documenting "
                                "risk limits and thesis changes.",
                            ],
                            "evidence_handles": ["trading"],
                        }
                    ],
                },
                {
                    "key": "certification",
                    "title": "Certifications",
                    "items": [
                        {
                            "id": "cme_4a",
                            "title": "CME-4A",
                            "organization": "Capital Market Authority",
                            "date_range": "2025",
                            "bullets": [],
                            "evidence_handles": ["cme_4a"],
                        },
                        {
                            "id": "cme_1a",
                            "title": "CME-1A",
                            "organization": "Capital Market Authority",
                            "date_range": "2024/01",
                            "bullets": [],
                            "evidence_handles": ["cme_1a"],
                        },
                        {
                            "id": "financial_modeling",
                            "title": "Financial Modeling & Valuation",
                            "organization": "Professional Training Provider",
                            "date_range": "2024",
                            "bullets": [],
                            "evidence_handles": ["modeling_certificate"],
                        },
                        {
                            "id": "risk_management",
                            "title": "Investment Risk Management",
                            "organization": "Professional Training Provider",
                            "date_range": "2023",
                            "bullets": [],
                            "evidence_handles": ["risk_certificate"],
                        },
                    ],
                },
                {
                    "key": "skill",
                    "title": "Skills",
                    "items": [
                        {
                            "id": "finance_skills",
                            "title": "Financial Skills",
                            "bullets": [
                                "Cost control",
                                "Budget variance analysis",
                                "Financial reporting",
                                "Equity research",
                                "Portfolio risk management",
                            ],
                            "evidence_handles": ["finance_skills"],
                        },
                        {
                            "id": "technical_skills",
                            "title": "Technical Skills",
                            "bullets": [
                                "Microsoft Excel",
                                "Power BI",
                                "Financial modeling",
                                "Data visualization",
                            ],
                            "evidence_handles": ["technical_skills"],
                        },
                        {
                            "id": "professional_skills",
                            "title": "Professional Skills",
                            "bullets": [
                                "Analytical writing",
                                "Presentation",
                                "Stakeholder communication",
                                "Training delivery",
                            ],
                            "evidence_handles": ["professional_skills"],
                        },
                    ],
                },
                {
                    "key": "language",
                    "title": "Languages",
                    "items": [
                        {
                            "id": "arabic",
                            "title": "Arabic",
                            "bullets": ["Native"],
                            "evidence_handles": ["arabic"],
                        },
                        {
                            "id": "english",
                            "title": "English",
                            "bullets": ["Professional working proficiency"],
                            "evidence_handles": ["english"],
                        },
                    ],
                },
            ],
        }
    )


def _extracted_text(content: bytes) -> tuple[PdfReader, str]:
    reader = PdfReader(BytesIO(content))
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    return reader, " ".join(text.split())


def test_hadi_like_resume_fits_one_ats_safe_page_without_losing_facts() -> None:
    result = render_resume_pdf_with_layout(
        profile_name="Hadi Alghanim",
        city="Dammam, Saudi Arabia",
        language=PreferredLanguage.EN,
        draft=_hadi_like_draft(),
        contact=ResumeExportContact(
            email="hadi@example.com",
            phone="+966 50 000 0000",
            linkedin="linkedin.com/in/hadi-alghanim",
        ),
    )

    reader, text = _extracted_text(result.content)
    assert result.page_count == len(reader.pages) == 1
    assert result.layout_profile in {"comfortable", "compact"}

    section_positions = [
        text.index(section_title)
        for section_title in (
            "Education",
            "Professional Experience",
            "Investment & Trading Experience",
            "Certifications",
            "Skills",
            "Languages",
        )
    ]
    assert section_positions == sorted(section_positions)

    protected_facts = (
        "King Fahd University of Petroleum and Minerals",
        "3.2/4.0",
        "48 ledger accounts",
        "5,000 learners",
        "3,000 market observations",
        "SAR 50,000",
        "CME-4A",
        "CME-1A",
        "2024/01",
        "Power BI",
        "Professional working proficiency",
    )
    for fact in protected_facts:
        assert fact in text

    # The legacy byte-only API remains intact.
    legacy = render_resume_pdf(
        profile_name="Hadi Alghanim",
        city="Dammam, Saudi Arabia",
        language=PreferredLanguage.EN,
        draft=_hadi_like_draft(),
        contact=ResumeExportContact(),
    )
    assert legacy.startswith(b"%PDF")


def test_true_overflow_uses_multiple_pages_and_keeps_every_bullet() -> None:
    detail = (
        "Documented assumptions, sources, calculations, controls, review notes, exceptions, "
        "and decision criteria for a detailed financial scenario. Reconciled the scenario to "
        "source records and recorded the reasons for every variance so another analyst could "
        "reproduce the work. Compared base, downside, and upside cases across revenue, cost, "
        "cash-flow, timing, and sensitivity drivers before writing a traceable conclusion. "
    )
    bullets = [
        f"OVERFLOW-{index:02d}-START {detail}{detail}OVERFLOW-{index:02d}-END"
        for index in range(20)
    ]
    draft = ResumeDraftContent.model_validate(
        {
            "headline": "Financial Analysis Graduate",
            "professional_summary": (
                "Finance graduate with documented analytical work and reproducible review "
                "practices across detailed financial scenarios."
            ),
            "summary_evidence_handles": ["overflow"],
            "sections": [
                {
                    "key": "project",
                    "title": "Projects",
                    "items": [
                        {
                            "id": "overflow_project",
                            "title": "Evidence Preservation Project",
                            "organization": "Independent Research",
                            "date_range": "2025",
                            "location": "Saudi Arabia",
                            "bullets": bullets,
                            "evidence_handles": ["overflow"],
                        }
                    ],
                }
            ],
        }
    )

    result = render_resume_pdf_with_layout(
        profile_name="Overflow Candidate",
        city=None,
        language=PreferredLanguage.EN,
        draft=draft,
        contact=ResumeExportContact(),
    )

    reader, text = _extracted_text(result.content)
    assert result.page_count == len(reader.pages)
    assert result.page_count > 1
    for index in range(20):
        assert f"OVERFLOW-{index:02d}-START" in text
        assert f"OVERFLOW-{index:02d}-END" in text
