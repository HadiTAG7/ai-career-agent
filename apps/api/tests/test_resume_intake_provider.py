from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

import career_agent_api.services.resume_intake as resume_intake
from career_agent_api.core.config import Settings
from career_agent_api.models.enums import FactCategory
from career_agent_api.services.resume_intake import (
    MAX_RESUME_SEGMENT_CHARS,
    MAX_RESUME_SEGMENTS,
    MAX_RESUME_TEXT_CHARS,
    MISTRAL_API_BASE_URL,
    RESUME_MAX_OUTPUT_TOKENS,
    DisabledResumeIntakeProvider,
    MistralResumeIntakeProvider,
    OpenAIResumeIntakeProvider,
    ResumeIntakeProviderContext,
    ResumeIntakeProviderError,
    ResumeSegment,
    build_resume_segments,
    get_resume_intake_provider,
)

# Synthetic, shape-preserving ``PdfReader(...).pages[0].extract_text()`` output. The wrapped lines,
# bullets, NBSP, and spaced letters mirror the PDF artifacts under test without storing a person's
# identity, employers, institution, or career metrics in the repository.
_TWO_COLUMN_FINANCE_RESUME_PYPDF_TEXT = (
    "Candidate Name  Finance\n"
    "candidate@example.test\n"
    "Riyadh, Saudi Arabia\n"
    "+966551234567\n"
    "linkedin.com/in/candidate-profile\n"
    "Profile\n"
    "Finance & Investment Professional with 6+ years of hands-on experience in equity trading, "
    "strategy development, and risk management. Built and\n"
    "validated multiple systematic trading strategies through extensive backtesting using "
    "4,000+ data samples across various market conditions.\n"
    "Experienced trading educator with 1,200+ students trained and 20,000+ educational content "
    "views. Strong foundation in finance, treasury, and\n"
    "financial analysis.\n"
    "Education\n"
    "Bachelor degree in Finance\n"
    "Gulf Technical University, Dammam, Saudi Arabia\n"
    "GPA: 3.4/ 4\n"
    "Graduation Date: Dec 2023\n"
    "Relevant Courses: Auditing, Financial Accounting, Risk Management, Cost Control, Internal "
    "Control Systems, Financial Modelling\n"
    "Professional Experience\n"
    "2025 – Present\n"
    "Riyadh, Saudi Arabia\n"
    "Cost Control & Finance Analyst — Northstar Consumer Brands\n"
    "• Performed monthly variance analysis, cost control, and internal financial reviews.\n"
    "• Supported audit processes, compliance checks, and management reporting.\n"
    "2024/01 – 2024/08\n"
    "Jubail, Saudi Arabia\n"
    "Finance Trainee — Treasury, Reporting & Internal Controls\n"
    "Meridian Petrochemical\n"
    "•Supported month-end and year-end financial closing, reconciliations, and journal posting.\n"
    "•Assisted in tracking audit adjustments and documenting internal control findings.\n"
    "•Prepared reports on financial performance, liquidity, and variance analysis.\n"
    "•Participated in risk and compliance checks with the internal audit function.\n"
    "2022 – 2025 Financial Markets Instructor — MarketLearn\n"
    "• Trained 1,200+ students in trading strategy execution, market analysis, and risk "
    "management.\n"
    "• Designed structured educational programs covering strategy logic, psychology, and "
    "discipline.\n"
    "• Produced investment content exceeding 20,000 total views.\n"
    "• Guest lecturer on trading & risk management at GTU.\n"
    "Investment & Trading Experience\n"
    "2018 – Present Investment & Trading Professional\n"
    "• Active trader in U.S. and regional equity markets since 2018.\n"
    "• Built and optimized multiple trading strategies validated using 4,000+ backtesting "
    "samples across different market \n"
    "environments.\n"
    "• Performed robustness testing, scenario analysis, and volatility stress testing.\n"
    "• Designed professional risk management frameworks focused on R-multiples, position "
    "sizing, and drawdown control.\n"
    "• Applied portfolio diversification and systematic execution to improve risk-adjusted "
    "consistency.\n"
    "Certificates\n"
    "CME-4 Certification (Both CME-4A & CME-4B)\n"
    "Advanced Microsoft Excel\n"
    "CME-1 Certification (Both CME-1A & CME-1B)\n"
    "ERP Implementation Experience (Internship-based)\n"
    "Skills\n"
    "Financial Skills\n"
    "Trading Strategy Development, Backtesting & Optimization, Risk & Money Management, "
    "Portfolio Construction, Market Analysis, Options Strategies \n"
    "(Covered Calls).\n"
    "Data & Technical:\n"
    "Advanced Excel (Pivot Tables, VBA Basics, Lookups)- Power BI (Foundational dashboards)- "
    "Python — Financial Modelling & Scenario Analysis\n"
    "Soft Skills:\n"
    "Attention to Detail • Fast Market Response • Team Collaboration • Compliance Mindset • "
    "Clear Communication\n"
    "Languages\n"
    "English Arabic\n"
    " — \xa0 F l u e n t\n"
    " — \xa0 N a t i v e / B i l i n g u a l"
)


def _generated_json(*, source_handle: str = "segment_1") -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "category": "experience",
                    "label": "Payment APIs",
                    "detail": "Built payment APIs",
                    "source_handle": source_handle,
                }
            ]
        }
    )


def _generated_json_with_pii() -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "category": "experience",
                    "label": "Payment APIs +966 55 123 4567",
                    "detail": "Built payment APIs dev@example.test",
                    "source_handle": "segment_1",
                }
            ]
        }
    )


def _context(*, include_pii: bool = False) -> ResumeIntakeProviderContext:
    text = "Built payment APIs"
    if include_pii:
        text += " | dev@example.test | +966 55 123 4567"
    return ResumeIntakeProviderContext(
        locale="en",
        mode="upload",
        segments=(ResumeSegment(handle="segment_1", text=text),),
    )


@dataclass
class _OpenAICapture:
    output_parsed: object | None = field(
        default_factory=lambda: resume_intake._GeneratedResumeFacts.model_validate_json(
            _generated_json()
        )
    )
    provider_error: Exception | None = None
    client_kwargs: dict[str, Any] = field(default_factory=dict)
    parse_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _MistralCapture:
    content: str | None = field(default_factory=_generated_json)
    finish_reason: str | None = "stop"
    provider_error: Exception | None = None
    client_kwargs: dict[str, Any] = field(default_factory=dict)
    create_calls: list[dict[str, Any]] = field(default_factory=list)


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    capture: _OpenAICapture,
) -> None:
    class _FakeResponses:
        async def parse(self, **kwargs: Any) -> SimpleNamespace:
            capture.parse_calls.append(kwargs)
            if capture.provider_error is not None:
                raise capture.provider_error
            return SimpleNamespace(output_parsed=capture.output_parsed)

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            capture.client_kwargs = kwargs
            self.responses = _FakeResponses()

        async def __aenter__(self) -> _FakeAsyncOpenAI:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: object | None,
        ) -> bool:
            del exc_type, exc, traceback
            return False

    monkeypatch.setattr(resume_intake, "AsyncOpenAI", _FakeAsyncOpenAI)


def _install_fake_mistral(
    monkeypatch: pytest.MonkeyPatch,
    capture: _MistralCapture,
) -> None:
    class _FakeCompletions:
        async def create(self, **kwargs: Any) -> SimpleNamespace:
            capture.create_calls.append(kwargs)
            if capture.provider_error is not None:
                raise capture.provider_error
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=capture.finish_reason,
                        message=SimpleNamespace(content=capture.content),
                    )
                ]
            )

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            capture.client_kwargs = kwargs
            self.chat = SimpleNamespace(completions=_FakeCompletions())

        async def __aenter__(self) -> _FakeAsyncOpenAI:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: object | None,
        ) -> bool:
            del exc_type, exc, traceback
            return False

    monkeypatch.setattr(resume_intake, "AsyncOpenAI", _FakeAsyncOpenAI)


def test_build_resume_segments_redacts_pii_and_drops_empty_contact_lines() -> None:
    segments = build_resume_segments(
        """
        Email: candidate@example.test
        Phone: +966 55 123 4567
        Telephone: (555) 123-4567
        IBAN: SA0380000000608010167519
        National ID: 1234567890
        Built payment APIs; alternate email candidate@example.test
        Python
        """
    )

    assert [segment.handle for segment in segments] == ["segment_1", "segment_2"]
    assert segments[0].text == "Built payment APIs; alternate email [redacted]"
    assert segments[1].text == "Python"
    serialized = repr(segments)
    for sensitive in (
        "candidate@example.test",
        "+966 55 123 4567",
        "(555) 123-4567",
        "SA0380000000608010167519",
        "1234567890",
    ):
        assert sensitive not in serialized


def test_build_resume_segments_removes_names_addresses_and_reference_contacts() -> None:
    segments = build_resume_segments(
        """
        Hadi Alghanim
        Data Analyst
        hadi@example.test | linkedin.com/in/hadi-alghanim
        221B Baker Street, London NW1 6XE
        Professional Experience
        Data Analyst — Acme Corporation; office: 123 Main Street, Riyadh 12345
        Education
        BSc Computer Science — King Saud University
        References
        Sarah Ahmed
        Engineering Manager — Acme Corporation
        sarah.ahmed@example.test | +966 55 222 3344
        """
    )

    serialized = "\n".join(segment.text for segment in segments)
    for private_value in (
        "Hadi Alghanim",
        "hadi@example.test",
        "linkedin.com/in/hadi-alghanim",
        "221B Baker Street",
        "NW1 6XE",
        "123 Main Street",
        "Sarah Ahmed",
        "sarah.ahmed@example.test",
        "+966 55 222 3344",
    ):
        assert private_value not in serialized
    assert "Acme Corporation" in serialized
    assert "King Saud University" in serialized


def test_build_resume_segments_applies_arabic_identity_and_reference_privacy() -> None:
    segments = build_resume_segments(
        """
        الاسم الكامل: هادي الغانم
        الجوال: +966 55 123 4567
        العنوان البريدي: الرياض، حي النرجس، شارع عثمان بن عفان، مبنى 12
        الخبرة
        محلل بيانات — شركة سداد
        التعليم
        بكالوريوس علوم حاسب — جامعة الملك سعود
        المراجع
        سارة أحمد
        مديرة هندسية — شركة مرجعية
        sara@example.test
        """
    )

    serialized = "\n".join(segment.text for segment in segments)
    for private_value in (
        "هادي الغانم",
        "+966 55 123 4567",
        "حي النرجس",
        "شارع عثمان بن عفان",
        "سارة أحمد",
        "sara@example.test",
        "شركة مرجعية",
    ):
        assert private_value not in serialized
    assert "شركة سداد" in serialized
    assert "جامعة الملك سعود" in serialized


def test_provider_segment_sanitizer_cannot_bypass_contextual_privacy() -> None:
    context = ResumeIntakeProviderContext(
        locale="en",
        mode="upload",
        segments=(
            ResumeSegment(
                handle="profile",
                text=(
                    "Name: Hadi Alghanim\n"
                    "Address: 14 King Road, Riyadh 12345\n"
                    "Professional Experience\n"
                    "Engineer — Acme Corporation"
                ),
            ),
            ResumeSegment(
                handle="references",
                text=(
                    "References: Sarah Ahmed | Engineering Manager | "
                    "sarah@example.test | +966 55 222 3344"
                ),
            ),
            ResumeSegment(
                handle="education",
                text="Education\nBSc — King Saud University",
            ),
        ),
    )

    sanitized = resume_intake._sanitized_segments(context)

    serialized = repr(sanitized)
    for private_value in (
        "Hadi Alghanim",
        "14 King Road",
        "Sarah Ahmed",
        "sarah@example.test",
        "+966 55 222 3344",
    ):
        assert private_value not in serialized
    assert "Acme Corporation" in serialized
    assert "King Saud University" in serialized


def test_contextual_name_filter_preserves_standalone_professional_titles() -> None:
    assert build_resume_segments("Inventory Dashboard") == (
        ResumeSegment(handle="segment_1", text="Inventory Dashboard"),
    )


def test_inline_resume_header_name_is_removed_before_segment_building() -> None:
    segments = build_resume_segments(
        "hadi alghanim | Data Analyst | hadi@example.test\n"
        "Professional Experience\n"
        "Data Analyst — Acme Corporation"
    )

    serialized = repr(segments)
    assert "hadi alghanim" not in serialized.casefold()
    assert "hadi@example.test" not in serialized
    assert "Data Analyst" in serialized
    assert "Acme Corporation" in serialized


def test_spaced_header_name_after_profile_is_removed_before_segment_building() -> None:
    segments = build_resume_segments(
        "Profile\n"
        "J o h n D o e\n"
        "candidate@example.test\n"
        "Finance analyst with experience in cost control."
    )

    serialized = repr(segments)
    assert "J o h n" not in serialized
    assert "JohnDoe" not in serialized
    assert "candidate@example.test" not in serialized
    assert "Finance analyst with experience in cost control." in serialized


def test_profile_descriptor_cannot_hide_the_real_name_from_privacy_filter() -> None:
    segments = build_resume_segments(
        "Profile\n"
        "Finance Investment Professional\n"
        "John Doe\n"
        "john@example.test\n"
        "Experienced analyst"
    )

    serialized = repr(segments)
    assert "John Doe" not in serialized
    assert "john@example.test" not in serialized
    assert "Experienced analyst" in serialized


def test_location_detection_preserves_business_phrases_and_location_named_employers() -> None:
    assert not resume_intake._looks_like_location_line(
        "Saudi Arabia market analysis and reporting"
    )
    assert not resume_intake._looks_like_location_line(
        "Riyadh sales planning and forecasting"
    )
    assert not resume_intake._looks_like_location_line("Riyadh Air")
    assert resume_intake._looks_like_location_line("Riyadh, Saudi Arabia")

    record = resume_intake._record_from_candidate(
        category=FactCategory.EXPERIENCE,
        label="Financial Analyst",
        detail="Riyadh Air; Saudi Arabia market analysis and reporting",
        source_handle="segment_1",
        source_excerpt="Professional Experience",
    )
    assert record.organization == "Riyadh Air"
    assert record.location is None
    assert record.responsibilities == ["Saudi Arabia market analysis and reporting"]

    combined = resume_intake._record_from_candidate(
        category=FactCategory.EXPERIENCE,
        label="Financial Analyst",
        detail="Riyadh Air, Riyadh, Saudi Arabia; Prepared monthly reports",
        source_handle="segment_1",
        source_excerpt="Professional Experience",
    )
    assert combined.organization == "Riyadh Air"
    assert combined.location == "Riyadh, Saudi Arabia"
    assert combined.responsibilities == ["Prepared monthly reports"]


def test_build_resume_segments_enforces_segment_and_character_caps() -> None:
    many_segments = build_resume_segments("\n".join(f"Skill {index}" for index in range(500)))
    assert len(many_segments) == MAX_RESUME_SEGMENTS

    large_segments = build_resume_segments("x" * 40_000 + "\n" + "y" * 40_000)
    assert sum(len(segment.text) for segment in large_segments) == MAX_RESUME_TEXT_CHARS
    assert all(len(segment.text) <= MAX_RESUME_SEGMENT_CHARS for segment in large_segments)
    assert "".join(segment.text for segment in large_segments) == ("x" * 40_000 + "y" * 20_000)


def test_build_resume_segments_chunks_large_sections_without_losing_context() -> None:
    entries = [
        f"Portfolio analytics contribution {index}: Built scenario analysis using Python and SQL."
        for index in range(100)
    ]

    segments = build_resume_segments("Projects\n" + "\n".join(entries))

    assert len(segments) > 1
    assert all(len(segment.text) <= MAX_RESUME_SEGMENT_CHARS for segment in segments)
    assert all(segment.text.startswith("Projects:\n") for segment in segments)
    observed_entries = [line for segment in segments for line in segment.text.splitlines()[1:]]
    assert observed_entries == entries


def test_project_title_and_description_do_not_split_across_segment_boundary() -> None:
    filler = []
    for index in range(55):
        filler.extend(
            [
                f"Filler Project {index}",
                "Built a compact analysis with Python and documented the result.",
            ]
        )
    target_title = "Portfolio Risk Dashboard"
    target_detail = "Built an interactive dashboard in Power BI."

    segments = build_resume_segments(
        "Projects\n" + "\n".join([*filler, target_title, target_detail])
    )

    target_segment = next(segment for segment in segments if target_title in segment.text)
    assert target_detail in target_segment.text
    assert all(segment.text.splitlines()[1] != target_detail for segment in segments)


def test_build_resume_segments_joins_a_standalone_guided_label_to_its_answer() -> None:
    segments = build_resume_segments("Evidence — Education / التعليم:\nBSc in Computer Science")

    assert segments == (
        ResumeSegment(
            handle="segment_1",
            text="Evidence — Education / التعليم : BSc in Computer Science",
        ),
    )


def test_build_resume_segments_keeps_section_context_and_repairs_wrapped_sentences() -> None:
    segments = build_resume_segments(
        """
        Professional Experience
        Data Analyst — Acme; responsibilities: Built and
        maintained weekly reports; tools: Python, Power BI
        """
    )

    assert segments == (
        ResumeSegment(
            handle="segment_1",
            text=(
                "Professional Experience:\n"
                "Data Analyst — Acme; responsibilities: Built and maintained weekly reports; "
                "tools: Python, Power BI"
            ),
        ),
    )


def test_build_resume_segments_keeps_related_resume_fields_in_complete_sections() -> None:
    segments = build_resume_segments(
        """
        Professional Experience
        2025 – Present
        Investment Analyst
        Asset Management Company
        Managed global equity portfolios and analyzed markets.
        Skills
        Financial Skills
        Portfolio Management
        Equity Research
        Education
        Bachelor of Science in Finance
        King Fahd University of Petroleum and Minerals, Dhahran, Saudi Arabia
        2024
        """
    )

    assert segments == (
        ResumeSegment(
            handle="segment_1",
            text=(
                "Professional Experience:\n"
                "2025 – Present\n"
                "Investment Analyst\n"
                "Asset Management Company\n"
                "Managed global equity portfolios and analyzed markets."
            ),
        ),
        ResumeSegment(
            handle="segment_2",
            text="Financial Skills:\nPortfolio Management\nEquity Research",
        ),
        ResumeSegment(
            handle="segment_3",
            text=(
                "Education:\n"
                "Bachelor of Science in Finance\n"
                "King Fahd University of Petroleum and Minerals, Dhahran, Saudi Arabia\n"
                "2024"
            ),
        ),
    )


def test_inline_section_values_keep_the_following_record_fields_together() -> None:
    segments = build_resume_segments(
        """
        Professional Experience : 2025 – Present
        Investment Analyst
        Asset Management Company
        Managed global equity portfolios.
        Skills : Financial Skills
        Portfolio Management
        Education : Bachelor of Science in Finance
        King Fahd University of Petroleum and Minerals
        2024
        """
    )

    assert [segment.text for segment in segments] == [
        (
            "Professional Experience:\n"
            "2025 – Present\n"
            "Investment Analyst\n"
            "Asset Management Company\n"
            "Managed global equity portfolios."
        ),
        "Skills:\nFinancial Skills\nPortfolio Management",
        (
            "Education:\n"
            "Bachelor of Science in Finance\n"
            "King Fahd University of Petroleum and Minerals\n"
            "2024"
        ),
    ]


@pytest.mark.parametrize(
    "value",
    [
        "Jan 2023 – Present",
        "September 2021 – Dec 2023",
        "09/2021 – 06/2024",
        "يناير 2023 – الآن",
        "٢٠٢٥",
    ],
)
def test_common_resume_date_formats_are_recognized(value: str) -> None:
    assert resume_intake._looks_like_date_only(value)


def test_generated_headings_and_dangling_fragments_are_not_facts() -> None:
    generated = resume_intake._GeneratedResumeFacts.model_validate(
        {
            "facts": [
                {
                    "category": "experience",
                    "label": "Professional Experience",
                    "detail": None,
                    "source_handle": "segment_1",
                },
                {
                    "category": "experience",
                    "label": "Built and",
                    "detail": None,
                    "source_handle": "segment_2",
                },
            ]
        }
    )

    resolved = resume_intake._resolve_generated_facts(
        generated,
        (
            ResumeSegment("segment_1", "Professional Experience"),
            ResumeSegment("segment_2", "Built and"),
        ),
    )

    assert resolved == []


def test_unlabelled_responsibility_is_not_misclassified_as_an_organization() -> None:
    responsibility = "Analyzed sales data using Power BI"

    record = resume_intake._record_from_candidate(
        category=FactCategory.EXPERIENCE,
        label="Data Analyst",
        detail=responsibility,
        source_handle="segment_1",
        source_excerpt=f"Data Analyst — {responsibility}",
    )

    assert record.organization is None
    assert record.responsibilities == [responsibility]

    arabic_responsibility = "تحليل بيانات المبيعات"
    arabic_record = resume_intake._record_from_candidate(
        category=FactCategory.EXPERIENCE,
        label="محلل بيانات",
        detail=arabic_responsibility,
        source_handle="segment_2",
        source_excerpt=f"محلل بيانات — {arabic_responsibility}",
    )
    assert arabic_record.organization is None
    assert arabic_record.responsibilities == [arabic_responsibility]


def test_short_name_like_context_can_still_be_an_organization() -> None:
    record = resume_intake._record_from_candidate(
        category=FactCategory.PROJECT,
        label="Inventory dashboard",
        detail="University Project; responsibilities: Built weekly reports",
        source_handle="segment_1",
        source_excerpt=(
            "Inventory dashboard — University Project; responsibilities: Built weekly reports"
        ),
    )

    assert record.organization == "University Project"
    assert record.responsibilities == ["Built weekly reports"]


def test_a_single_responsibility_is_not_split_at_a_natural_conjunction() -> None:
    responsibility = "Built portfolio dashboards and automated monthly reporting"

    record = resume_intake._record_from_candidate(
        category=FactCategory.EXPERIENCE,
        label="Data Analyst",
        detail=f"Acme Company; responsibilities: {responsibility}",
        source_handle="segment_1",
        source_excerpt=f"Data Analyst — Acme Company; responsibilities: {responsibility}",
    )

    assert record.responsibilities == [responsibility]


def test_institution_only_education_is_never_stored_as_a_degree() -> None:
    institution = "King Fahd University of Petroleum and Minerals, Dhahran, Saudi Arabia"

    record = resume_intake._record_from_candidate(
        category=FactCategory.EDUCATION,
        label=institution,
        detail=None,
        source_handle="segment_1",
        source_excerpt=f"Education:\n{institution}",
    )

    assert record.institution == institution
    assert record.degree is None


@pytest.mark.asyncio
async def test_section_scoped_local_fallback_creates_a_complete_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    context = ResumeIntakeProviderContext(
        locale="en",
        mode="upload",
        segments=build_resume_segments(
            """
            Professional Experience
            Data Analyst — Acme; responsibilities: Built weekly reports; tools: Python
            """
        ),
    )

    result = await provider.generate(context)

    experience = next(item for item in result if item.category == FactCategory.EXPERIENCE)
    assert experience.label == "Data Analyst"
    assert experience.detail == "Acme; responsibilities: Built weekly reports; tools: Python"
    assert experience.structured_value["organization"] == "Acme"
    assert experience.structured_value["responsibilities"] == ["Built weekly reports"]


@pytest.mark.asyncio
async def test_multi_entry_experience_keeps_date_before_and_after_with_the_right_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Professional Experience
        Jan 2021 – Dec 2022
        Data Analyst
        Acme Company
        Built monthly sales dashboards.
        Senior Investment Analyst
        Beta Bank
        Jan 2023 – Present
        Led equity research and prepared investment reports.
        """
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [segment.text for segment in segments] == [
        (
            "Professional Experience:\n"
            "Jan 2021 – Dec 2022\n"
            "Data Analyst\n"
            "Acme Company\n"
            "Built monthly sales dashboards."
        ),
        (
            "Professional Experience:\n"
            "Senior Investment Analyst\n"
            "Beta Bank\n"
            "Jan 2023 – Present\n"
            "Led equity research and prepared investment reports."
        ),
    ]
    assert [fact.label for fact in result] == ["Data Analyst", "Senior Investment Analyst"]
    assert result[0].structured_value["organization"] == "Acme Company"
    assert result[0].structured_value["date_range"] == "Jan 2021 – Dec 2022"
    assert result[0].structured_value["responsibilities"] == ["Built monthly sales dashboards"]
    assert result[1].structured_value["organization"] == "Beta Bank"
    assert result[1].structured_value["date_range"] == "Jan 2023 – Present"
    assert result[1].structured_value["responsibilities"] == [
        "Led equity research and prepared investment reports"
    ]


@pytest.mark.asyncio
async def test_professional_development_bullet_stays_inside_its_experience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        "Professional Experience\n"
        "Financial Analyst\n"
        "Acme Corporation\n"
        "2023 - Present\n"
        "Professional development and team training.\n"
        "Prepared monthly reports."
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert len(segments) == 1
    assert [fact.label for fact in result] == ["Financial Analyst"]
    assert result[0].structured_value["responsibilities"] == [
        "Professional development and team training",
        "Prepared monthly reports",
    ]


@pytest.mark.asyncio
async def test_role_specialization_after_dash_is_not_invented_as_an_employer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        "Professional Experience\n"
        "Investment Analyst - Equity Research\n"
        "2023 - Present\n"
        "Analyzed listed companies and prepared valuation models."
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [fact.label for fact in result] == ["Investment Analyst - Equity Research"]
    assert result[0].structured_value.get("organization") is None
    assert result[0].structured_value["date_range"] == "2023 - Present"


@pytest.mark.asyncio
async def test_explicit_language_proficiency_fills_partial_provider_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = build_resume_segments("Languages\nEnglish - Fluent")
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "language",
                        "label": "English",
                        "detail": None,
                        "source_handle": segments[0].handle,
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [(fact.label, fact.detail) for fact in result] == [("English", "Fluent")]
    assert result[0].structured_value["proficiency"] == "Fluent"


@pytest.mark.asyncio
async def test_mixed_date_layout_keeps_the_second_leading_date_with_the_second_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Professional Experience
        Data Analyst
        Acme Company
        2021 – 2022
        Built dashboards.
        2023 – Present
        Senior Investment Analyst
        Beta Bank
        Led equity research.
        """
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert "2023 – Present" not in segments[0].text
    assert segments[1].text.startswith(
        "Professional Experience:\n2023 – Present\nSenior Investment Analyst"
    )
    assert [fact.structured_value.get("date_range") for fact in result] == [
        "2021 – 2022",
        "2023 – Present",
    ]


@pytest.mark.asyncio
async def test_split_year_and_present_lines_form_one_experience_date_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Professional Experience
        2025
        Present
        Investment Analyst
        Asset Management Company
        Analyzed global equity portfolios.
        """
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [(fact.category, fact.label) for fact in result] == [
        (FactCategory.EXPERIENCE, "Investment Analyst")
    ]
    record = result[0].structured_value
    assert record["date_range"] == "2025 – Present"
    assert record["organization"] == "Asset Management Company"
    assert record["responsibilities"] == ["Analyzed global equity portfolios"]


@pytest.mark.asyncio
async def test_grounded_baseline_does_not_duplicate_generated_projects_languages_or_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "project",
                        "label": "Portfolio Risk Dashboard",
                        "detail": "Built an interactive dashboard in Power BI",
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "skill",
                        "label": "Python",
                        "detail": None,
                        "source_handle": "segment_2",
                    },
                    {
                        "category": "skill",
                        "label": "SQL",
                        "detail": None,
                        "source_handle": "segment_2",
                    },
                    {
                        "category": "skill",
                        "label": "Power BI",
                        "detail": None,
                        "source_handle": "segment_2",
                    },
                    {
                        "category": "language",
                        "label": "Arabic",
                        "detail": None,
                        "source_handle": "segment_3",
                    },
                    {
                        "category": "language",
                        "label": "English",
                        "detail": None,
                        "source_handle": "segment_3",
                    },
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Projects
        Portfolio Risk Dashboard
        Built an interactive dashboard in Power BI.
        Skills
        Python / SQL / Power BI
        Languages
        Arabic / English
        """
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [(fact.category, fact.label) for fact in result] == [
        (FactCategory.PROJECT, "Portfolio Risk Dashboard"),
        (FactCategory.SKILL, "Python"),
        (FactCategory.SKILL, "SQL"),
        (FactCategory.SKILL, "Power BI"),
        (FactCategory.LANGUAGE, "Arabic"),
        (FactCategory.LANGUAGE, "English"),
    ]


@pytest.mark.asyncio
async def test_grounded_baseline_fills_specific_skills_the_provider_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "skill",
                        "label": "Python",
                        "detail": None,
                        "source_handle": "segment_1",
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments("Skills\nPython / SQL / Power BI")

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [fact.label for fact in result] == ["Python", "SQL", "Power BI"]


@pytest.mark.asyncio
async def test_project_action_sentence_cannot_replace_the_explicit_project_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = "Built an interactive dashboard in Power BI"
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "project",
                        "label": action,
                        "detail": None,
                        "source_handle": "segment_1",
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(f"Projects\nPortfolio Risk Dashboard\n{action}.")

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [(fact.label, fact.detail) for fact in result] == [
        ("Portfolio Risk Dashboard", f"{action}.")
    ]


@pytest.mark.asyncio
async def test_same_role_at_two_employers_stays_as_two_separate_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = build_resume_segments(
        """
        Professional Experience
        Data Analyst
        Acme Company
        2021 – 2023
        Built sales reports.
        Data Analyst
        Beta Bank
        2023 – Present
        Built portfolio reports.
        """
    )
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "experience",
                        "label": "Data Analyst",
                        "detail": "Acme Company",
                        "source_handle": "segment_1",
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [fact.label for fact in result] == ["Data Analyst", "Data Analyst"]
    assert [fact.structured_value["organization"] for fact in result] == [
        "Acme Company",
        "Beta Bank",
    ]
    assert [fact.structured_value["date_range"] for fact in result] == [
        "2021 – 2023",
        "2023 – Present",
    ]


@pytest.mark.asyncio
async def test_cross_paired_employers_are_removed_and_repaired_from_each_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = build_resume_segments(
        """
        Professional Experience
        Data Analyst
        Acme Company
        2021 – 2023
        Built sales reports.
        Portfolio Manager
        Beta Bank
        2023 – Present
        Managed equity portfolios.
        """
    )
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "experience",
                        "label": "Data Analyst",
                        "detail": "Beta Bank",
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "experience",
                        "label": "Portfolio Manager",
                        "detail": "Acme Company",
                        "source_handle": "segment_2",
                    },
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [fact.structured_value["organization"] for fact in result] == [
        "Acme Company",
        "Beta Bank",
    ]


@pytest.mark.asyncio
async def test_heading_date_skill_group_and_institution_fragments_are_all_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution = "King Fahd University of Petroleum and Minerals"
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "experience",
                        "label": "2025",
                        "detail": "Present",
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "skill",
                        "label": "Financial Skills",
                        "detail": None,
                        "source_handle": "segment_2",
                    },
                    {
                        "category": "education",
                        "label": institution,
                        "detail": None,
                        "source_handle": "segment_3",
                    },
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        f"Professional Experience : 2025 – Present\n"
        "Skills : Financial Skills\n"
        f"Education : {institution}"
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert result == []


@pytest.mark.asyncio
async def test_upload_replaces_heading_and_date_fragments_with_complete_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "experience",
                        "label": "2025",
                        "detail": "Present",
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "experience",
                        "label": "Investment Analyst",
                        "detail": None,
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "skill",
                        "label": "Financial Skills",
                        "detail": None,
                        "source_handle": "segment_2",
                    },
                    {
                        "category": "education",
                        "label": (
                            "King Fahd University of Petroleum and Minerals, Dhahran, Saudi Arabia"
                        ),
                        "detail": None,
                        "source_handle": "segment_3",
                    },
                    {
                        "category": "education",
                        "label": "Bachelor of Science in Finance",
                        "detail": None,
                        "source_handle": "segment_3",
                    },
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Professional Experience
        2025 – Present
        Investment Analyst
        Asset Management Company
        Managed global equity portfolios and analyzed markets.
        Skills
        Financial Skills
        Portfolio Management
        Equity Research
        Education
        Bachelor of Science in Finance
        King Fahd University of Petroleum and Minerals, Dhahran, Saudi Arabia
        2024
        """
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert [(fact.category, fact.label) for fact in result] == [
        (FactCategory.EXPERIENCE, "Investment Analyst"),
        (FactCategory.SKILL, "Portfolio Management"),
        (FactCategory.SKILL, "Equity Research"),
        (FactCategory.EDUCATION, "Bachelor of Science in Finance"),
    ]
    experience = result[0].structured_value
    assert experience["organization"] == "Asset Management Company"
    assert experience["date_range"] == "2025 – Present"
    assert experience["responsibilities"] == [
        "Managed global equity portfolios and analyzed markets"
    ]
    education = result[-1].structured_value
    assert education["degree"] == "Bachelor of Science in Finance"
    assert education["institution"] == "King Fahd University of Petroleum and Minerals"
    assert education["location"] == "Dhahran, Saudi Arabia"
    assert education["date_range"] == "2024"
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_two_column_pdf_keeps_complete_resume_records_without_layout_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = build_resume_segments(_TWO_COLUMN_FINANCE_RESUME_PYPDF_TEXT)

    def source_handle(marker: str) -> str:
        matches = [segment.handle for segment in segments if marker in segment.text]
        assert len(matches) == 1, (marker, matches)
        return matches[0]

    def fact(
        category: str,
        label: str,
        marker: str,
        detail: str | None = None,
    ) -> dict[str, str | None]:
        return {
            "category": category,
            "label": label,
            "detail": detail,
            "source_handle": source_handle(marker),
        }

    raw_facts = [
        fact(
            "education",
            "Bachelor degree in Finance",
            "Bachelor degree in Finance",
            (
                "Gulf Technical University, Dammam, Saudi Arabia; "
                "GPA: 3.4/ 4; Dec 2023"
            ),
        ),
        fact(
            "experience",
            "Cost Control & Finance Analyst",
            "Cost Control & Finance Analyst",
            (
                "Northstar Consumer Brands; 2025 – Present; Performed monthly variance analysis, "
                "cost control, and internal financial reviews; Supported audit processes, "
                "compliance checks, and management reporting"
            ),
        ),
        fact(
            "experience",
            "Finance Trainee — Treasury, Reporting & Internal Controls",
            "Finance Trainee — Treasury, Reporting & Internal Controls",
            (
                "Meridian Petrochemical; 2024/01 – 2024/08; Supported month-end and year-end "
                "financial closing, reconciliations, and journal posting; Assisted in tracking "
                "audit adjustments and documenting internal control findings; Prepared reports "
                "on financial performance, liquidity, and variance analysis; Participated in "
                "risk and compliance checks with the internal audit function"
            ),
        ),
        fact(
            "experience",
            "Financial Markets Instructor",
            "Financial Markets Instructor",
            (
                "MarketLearn; 2022 – 2025; Trained 1,200+ students in trading strategy execution, "
                "market analysis, and risk management; Designed structured educational programs "
                "covering strategy logic, psychology, and discipline; Produced investment "
                "content exceeding 20,000 total views; Guest lecturer on trading & risk "
                "management at GTU"
            ),
        ),
        fact(
            "experience",
            "Investment & Trading Professional",
            "Investment & Trading Professional",
            (
                "2018 – Present; Active trader in U.S. and regional equity markets since 2018; "
                "Built and optimized multiple trading strategies validated using 4,000+ "
                "backtesting samples across different market environments; Performed robustness "
                "testing, scenario analysis, and volatility stress testing; Designed professional "
                "risk management frameworks focused on R-multiples, position sizing, and "
                "drawdown control; Applied portfolio diversification and systematic execution to "
                "improve risk-adjusted consistency"
            ),
        ),
        fact(
            "certification",
            "CME-4 Certification (Both CME-4A & CME-4B)",
            "CME-4 Certification",
        ),
        fact(
            "certification",
            "Advanced Microsoft Excel",
            "Advanced Microsoft Excel",
        ),
        fact(
            "certification",
            "CME-1 Certification (Both CME-1A & CME-1B)",
            "CME-1 Certification",
        ),
        fact(
            "certification",
            "ERP Implementation Experience (Internship-based)",
            "ERP Implementation Experience",
        ),
        fact("skill", "Trading Strategy Development", "Financial Skills"),
        fact("skill", "Backtesting & Optimization", "Financial Skills"),
        fact("skill", "Risk & Money Management", "Financial Skills"),
        fact("skill", "Portfolio Construction", "Financial Skills"),
        fact("skill", "Market Analysis", "Financial Skills"),
        fact("skill", "Options Strategies (Covered Calls)", "Financial Skills"),
        fact(
            "skill",
            "Advanced Excel (Pivot Tables, VBA Basics, Lookups)",
            "Data & Technical",
        ),
        fact("skill", "Power BI (Foundational dashboards)", "Data & Technical"),
        fact(
            "skill",
            "Python — Financial Modelling & Scenario Analysis",
            "Data & Technical",
        ),
        fact("skill", "Attention to Detail", "Soft Skills"),
        fact("skill", "Fast Market Response", "Soft Skills"),
        fact("skill", "Team Collaboration", "Soft Skills"),
        fact("skill", "Compliance Mindset", "Soft Skills"),
        fact("skill", "Clear Communication", "Soft Skills"),
        fact("language", "English", "Languages", "Fluent"),
        fact("language", "Arabic", "Languages", "Native/Bilingual"),
    ]
    assert len(raw_facts) == 25

    capture = _MistralCapture(
        content=json.dumps({"facts": raw_facts}, ensure_ascii=False)
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="en", mode="upload", segments=segments)
    )

    assert len(capture.create_calls) == 1
    assert len(result) == 25

    education = [fact for fact in result if fact.category == FactCategory.EDUCATION]
    assert [fact.label for fact in education] == ["Bachelor degree in Finance"]
    assert education[0].structured_value["degree"] == "Bachelor degree in Finance"
    assert education[0].structured_value["institution"] == (
        "Gulf Technical University"
    )
    assert education[0].structured_value["location"] == "Dammam, Saudi Arabia"
    assert education[0].structured_value["date_range"] == "Dec 2023"
    assert education[0].structured_value["gpa_score"] == "3.4"
    assert education[0].structured_value["gpa_scale"] == "4"
    assert education[0].structured_value["gpa_display_recommended"] is True

    experiences = [fact for fact in result if fact.category == FactCategory.EXPERIENCE]
    assert [fact.label for fact in experiences] == [
        "Cost Control & Finance Analyst",
        "Finance Trainee — Treasury, Reporting & Internal Controls",
        "Financial Markets Instructor",
        "Investment & Trading Professional",
    ]
    assert all(fact.label.casefold() != "profile" for fact in experiences)
    assert [fact.structured_value.get("organization") for fact in experiences] == [
        "Northstar Consumer Brands",
        "Meridian Petrochemical",
        "MarketLearn",
        None,
    ]
    assert [fact.structured_value["date_range"] for fact in experiences] == [
        "2025 – Present",
        "2024/01 – 2024/08",
        "2022 – 2025",
        "2018 – Present",
    ]
    assert [fact.structured_value["responsibilities"] for fact in experiences] == [
        [
            "Performed monthly variance analysis, cost control, and internal financial reviews",
            "Supported audit processes, compliance checks, and management reporting",
        ],
        [
            "Supported month-end and year-end financial closing, reconciliations, and journal "
            "posting",
            "Assisted in tracking audit adjustments and documenting internal control findings",
            "Prepared reports on financial performance, liquidity, and variance analysis",
            "Participated in risk and compliance checks with the internal audit function",
        ],
        [
            "Trained 1,200+ students in trading strategy execution, market analysis, and risk "
            "management",
            "Designed structured educational programs covering strategy logic, psychology, and "
            "discipline",
            "Produced investment content exceeding 20,000 total views",
            "Guest lecturer on trading & risk management at GTU",
        ],
        [
            "Active trader in U.S. and regional equity markets since 2018",
            "Built and optimized multiple trading strategies validated using 4,000+ backtesting "
            "samples across different market environments",
            "Performed robustness testing, scenario analysis, and volatility stress testing",
            "Designed professional risk management frameworks focused on R-multiples, position "
            "sizing, and drawdown control",
            "Applied portfolio diversification and systematic execution to improve risk-adjusted "
            "consistency",
        ],
    ]

    certifications = [fact for fact in result if fact.category == FactCategory.CERTIFICATION]
    assert [fact.label for fact in certifications] == [
        "CME-4 Certification (Both CME-4A & CME-4B)",
        "Advanced Microsoft Excel",
        "CME-1 Certification (Both CME-1A & CME-1B)",
        "ERP Implementation Experience (Internship-based)",
    ]

    skills = [fact for fact in result if fact.category == FactCategory.SKILL]
    assert [fact.label for fact in skills] == [
        "Trading Strategy Development",
        "Backtesting & Optimization",
        "Risk & Money Management",
        "Portfolio Construction",
        "Market Analysis",
        "Options Strategies (Covered Calls)",
        "Advanced Excel (Pivot Tables, VBA Basics, Lookups)",
        "Power BI (Foundational dashboards)",
        "Python — Financial Modelling & Scenario Analysis",
        "Attention to Detail",
        "Fast Market Response",
        "Team Collaboration",
        "Compliance Mindset",
        "Clear Communication",
    ]
    fragment_labels = {
        "Financial Skills",
        "Data & Technical",
        "Soft Skills",
        "Options Strategies",
        "(Covered Calls).",
        "English Arabic",
        "— F l u e n t",
        "— N a t i v e",
        "B i l i n g u a l",
    }
    assert fragment_labels.isdisjoint(fact.label for fact in result)

    languages = [fact for fact in result if fact.category == FactCategory.LANGUAGE]
    assert [(fact.label, fact.detail) for fact in languages] == [
        ("English", "Fluent"),
        ("Arabic", "Native/Bilingual"),
    ]
    assert [fact.structured_value["proficiency"] for fact in languages] == [
        "Fluent",
        "Native/Bilingual",
    ]


@pytest.mark.asyncio
async def test_mistral_request_is_strict_bounded_and_privacy_preserving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture()
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(
        api_key="mistral-secret",
        model="mistral-small-2603",
        timeout_seconds=11,
    )

    result = await provider.generate(_context(include_pii=True))

    assert result[0].category == FactCategory.EXPERIENCE
    assert result[0].label == "Payment APIs"
    assert result[0].source_excerpt == "Built payment APIs | [redacted] | [redacted]"
    assert capture.client_kwargs == {
        "api_key": "mistral-secret",
        "base_url": MISTRAL_API_BASE_URL,
        "timeout": 11,
        "max_retries": 1,
    }
    request = capture.create_calls[0]
    assert set(request) == {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "stream",
        "response_format",
    }
    assert request["model"] == "mistral-small-2603"
    assert request["max_tokens"] == RESUME_MAX_OUTPUT_TOKENS
    assert request["temperature"] == 0
    assert request["stream"] is False
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "resume_fact_candidates",
            "strict": True,
            "schema": resume_intake._GeneratedResumeFacts.model_json_schema(),
        },
    }
    serialized = repr(request)
    assert "candidate@example.test" not in serialized
    assert "+966 55 123 4567" not in serialized
    assert "mistral-secret" not in serialized
    for forbidden_field in ("filename", "owner", "metadata", "safety_identifier", "tools"):
        assert forbidden_field not in request


@pytest.mark.asyncio
async def test_intake_writes_an_evidence_addressable_structured_resume_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = (
        "Acme; period: 2023–2025; responsibilities: Built weekly reports; "
        "outcome: Reduced review time; tools: Python, Power BI"
    )
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "experience",
                        "label": "Data Analyst",
                        "detail": detail,
                        "source_handle": "segment_1",
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    context = ResumeIntakeProviderContext(
        locale="en",
        mode="builder",
        segments=(
            ResumeSegment(
                "segment_1",
                f"Evidence — Experience / الخبرة: Data Analyst — {detail}",
            ),
        ),
    )

    result = await provider.generate(context)

    assert len(result) == 1
    record = result[0].structured_value
    assert record == {
        "schema_version": "resume_record.v1",
        "record_type": "experience",
        "source_handles": ["segment_1"],
        "title": "Data Analyst",
        "organization": "Acme",
        "date_range": "2023–2025",
        "responsibilities": ["Built weekly reports"],
        "outcomes": ["Reduced review time"],
        "tools": ["Python", "Power BI"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detail", "recommended"),
    [
        ("University; GPA: 3.2/4", True),
        ("University; GPA: 3.1/4", False),
        ("University; GPA: 2.8/4; honors: honors", True),
    ],
)
async def test_structured_education_record_applies_eighty_percent_or_honors_gpa_policy(
    monkeypatch: pytest.MonkeyPatch,
    detail: str,
    recommended: bool,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "education",
                        "label": "BSc Computer Science",
                        "detail": detail,
                        "source_handle": "segment_1",
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    result = await provider.generate(
        ResumeIntakeProviderContext(
            locale="en",
            mode="upload",
            segments=(ResumeSegment("segment_1", f"BSc Computer Science — {detail}"),),
        )
    )

    assert result[0].structured_value["gpa_display_recommended"] is recommended


@pytest.mark.asyncio
async def test_openai_uses_parse_without_retention_or_identifying_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _OpenAICapture()
    _install_fake_openai(monkeypatch, capture)
    provider = OpenAIResumeIntakeProvider(
        api_key="openai-secret",
        model="test-model",
        timeout_seconds=9,
    )

    result = await provider.generate(_context())

    assert result[0].source_excerpt == "Built payment APIs"
    assert capture.client_kwargs == {
        "api_key": "openai-secret",
        "timeout": 9,
        "max_retries": 1,
    }
    request = capture.parse_calls[0]
    assert request["store"] is False
    assert request["max_output_tokens"] == RESUME_MAX_OUTPUT_TOKENS
    assert request["text_format"] is resume_intake._GeneratedResumeFacts
    for forbidden_field in (
        "filename",
        "owner",
        "metadata",
        "safety_identifier",
        "tools",
        "previous_response_id",
        "conversation",
    ):
        assert forbidden_field not in request


@pytest.mark.asyncio
async def test_unknown_source_handle_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=_generated_json(source_handle="segment_unknown"))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    with pytest.raises(ResumeIntakeProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Resume intake provider returned no usable response"


@pytest.mark.asyncio
async def test_provider_output_identifiers_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=_generated_json_with_pii())
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    result = await provider.generate(_context())

    assert result[0].label == "Payment APIs [redacted]"
    assert result[0].detail == "Built payment APIs [redacted]"


@pytest.mark.asyncio
async def test_ungrounded_title_is_dropped_and_ungrounded_detail_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "experience",
                        "label": "Senior backend lead",
                        "detail": "Led 12 engineers",
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "experience",
                        "label": "Payment APIs",
                        "detail": "Led a 12-person payment team",
                        "source_handle": "segment_1",
                    },
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    result = await provider.generate(_context())

    assert [(fact.label, fact.detail) for fact in result] == [("Payment APIs", None)]
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_third_party_team_evidence_is_not_attributed_to_the_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "skill",
                        "label": "Python",
                        "detail": None,
                        "source_handle": "segment_1",
                    }
                ]
            }
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    context = ResumeIntakeProviderContext(
        locale="en",
        mode="builder",
        segments=(ResumeSegment(handle="segment_1", text="My team uses Python"),),
    )

    result = await provider.generate(context)

    assert result == []
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_english_guided_builder_covers_evidence_without_inventing_experience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Context — Career stage / المرحلة المهنية: New graduate
        Context — Target role / الهدف المهني: Python backend developer
        Evidence — Education / التعليم: BSc Computer Science, King Saud University
        Evidence — Experience / الخبرة: No experience yet
        Evidence — Projects & volunteering / المشاريع والتطوع: Volunteer charity app
        Evidence — Skills with evidence / المهارات مع أمثلة: Python — built the scheduling app
        Evidence — Certifications / الشهادات: AWS Cloud Practitioner
        Evidence — Achievements / الإنجازات: First place in a university hackathon
        Evidence — Languages / اللغات: Arabic native, English advanced
        """
    )
    context = ResumeIntakeProviderContext(locale="en", mode="builder", segments=segments)

    result = await provider.generate(context)

    assert {fact.category for fact in result} == {
        FactCategory.EDUCATION,
        FactCategory.PROJECT,
        FactCategory.SKILL,
        FactCategory.CERTIFICATION,
        FactCategory.ACHIEVEMENT,
        FactCategory.LANGUAGE,
    }
    assert FactCategory.EXPERIENCE not in {fact.category for fact in result}
    assert all("Context —" not in fact.label for fact in result)
    assert all("Evidence —" not in fact.label for fact in result)
    assert any("Evidence —" in fact.source_excerpt for fact in result)
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_arabic_guided_builder_covers_all_explicit_evidence_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        """
        Context — Career stage / المرحلة المهنية: خريج حديث
        Context — Target role / الهدف المهني: محلل بيانات
        Evidence — Education / التعليم: بكالوريوس نظم معلومات من جامعة الملك سعود
        Evidence — Experience / الخبرة: تدربت في شركة تقنية لمدة ثلاثة أشهر
        Evidence — Projects & volunteering / المشاريع والتطوع: بنيت لوحة بيانات لجمعية تطوعية
        Evidence — Skills with evidence / المهارات مع أمثلة: تحليل البيانات — بنيت تقارير أسبوعية
        Evidence — Certifications / الشهادات: شهادة أساسيات تحليل البيانات
        Evidence — Achievements / الإنجازات: المركز الأول في مسابقة جامعية
        Evidence — Languages / اللغات: العربية لغة أم، والإنجليزية متقدمة
        """
    )
    context = ResumeIntakeProviderContext(locale="ar", mode="builder", segments=segments)

    result = await provider.generate(context)

    assert {fact.category for fact in result} == {
        FactCategory.EDUCATION,
        FactCategory.EXPERIENCE,
        FactCategory.PROJECT,
        FactCategory.SKILL,
        FactCategory.CERTIFICATION,
        FactCategory.ACHIEVEMENT,
        FactCategory.LANGUAGE,
    }
    assert next(fact for fact in result if fact.category == FactCategory.SKILL).label == (
        "تحليل البيانات"
    )
    assert all("Evidence —" not in fact.label for fact in result)
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_multi_field_entries_become_useful_facts_without_technical_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": []}))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    content = "\n".join(
        (
            "Context — Career stage / المرحلة المهنية: Experienced professional | محترف ذو خبرة",
            "Context — Target role / الهدف المهني: مدير تحليل بيانات",
            "Evidence — Education / التعليم: بكالوريوس نظم المعلومات — "
            "جامعة الملك سعود؛ الحالة: متخرج؛ سنة التخرج: 2025؛ المعدل: 4.5 من 5؛ "
            "تكريم أو مواد بارزة: مرتبة الشرف",
            "Evidence — Education / التعليم: دبلوم تحليل البيانات — "
            "الأكاديمية الوطنية؛ سنة الإكمال: 2023",
            "Evidence — Experience / الخبرة: محلل بيانات — شركة س؛ الفترة: يناير "
            "2024–الآن؛ المسؤوليات: تقارير أسبوعية؛ الإنجازات: خفض الوقت للنصف؛ "
            "الأدوات: Excel، Power BI",
            "Evidence — Projects and volunteering / المشاريع والتطوع: لوحة المبيعات — "
            "مشروع جامعي؛ الهدف: متابعة الأداء؛ دوري: تحليل البيانات؛ الأدوات: Power BI؛ "
            "النتيجة: لوحة تفاعلية",
            "Evidence — Skills / المهارات: Excel — النوع: أداة؛ مصدر الدليل: مشروع لوحة "
            "المبيعات؛ مثال الاستخدام: تنظيف 500 سجل وبناء تقرير أسبوعي",
            "Evidence — Certifications / الشهادات:",
            "Evidence — Languages / اللغات: الإنجليزية — المستوى: متوسط؛ الاستخدام: "
            "اجتماعات وقراءة تقارير",
        )
    )
    segments = build_resume_segments(content)
    context = ResumeIntakeProviderContext(locale="ar", mode="builder", segments=segments)

    result = await provider.generate(context)

    education = [fact for fact in result if fact.category == FactCategory.EDUCATION]
    assert [(fact.label, fact.detail) for fact in education] == [
        (
            "بكالوريوس نظم المعلومات",
            "جامعة الملك سعود؛ الحالة: متخرج؛ سنة التخرج: 2025؛ المعدل: 4.5 من 5؛ "
            "تكريم أو مواد بارزة: مرتبة الشرف",
        ),
        (
            "دبلوم تحليل البيانات",
            "الأكاديمية الوطنية؛ سنة الإكمال: 2023",
        ),
    ]
    assert next(fact for fact in result if fact.category == FactCategory.EXPERIENCE).label == (
        "محلل بيانات"
    )
    assert next(fact for fact in result if fact.category == FactCategory.PROJECT).label == (
        "لوحة المبيعات"
    )
    assert next(fact for fact in result if fact.category == FactCategory.SKILL).label == "Excel"
    language = next(fact for fact in result if fact.category == FactCategory.LANGUAGE)
    assert (language.label, language.detail) == (
        "الإنجليزية",
        "المستوى: متوسط؛ الاستخدام: اجتماعات وقراءة تقارير",
    )
    assert FactCategory.CERTIFICATION not in {fact.category for fact in result}
    assert all("Context —" not in fact.label for fact in result)
    assert all("Evidence —" not in f"{fact.label} {fact.detail or ''}" for fact in result)
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_grounded_multi_field_numbers_survive_without_allowing_new_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = "جامعة الملك سعود؛ سنة التخرج: 2025؛ المعدل: 4.5 من 5"
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "education",
                        "label": "بكالوريوس نظم المعلومات",
                        "detail": detail,
                        "source_handle": "segment_1",
                    },
                    {
                        "category": "education",
                        "label": "بكالوريوس نظم المعلومات بمرتبة الشرف",
                        "detail": "المعدل: 4.9 من 5",
                        "source_handle": "segment_1",
                    },
                ]
            },
            ensure_ascii=False,
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    segments = build_resume_segments(
        f"Evidence — Education / التعليم: بكالوريوس نظم المعلومات — {detail}"
    )

    result = await provider.generate(
        ResumeIntakeProviderContext(locale="ar", mode="builder", segments=segments)
    )

    assert [(fact.label, fact.detail) for fact in result] == [("بكالوريوس نظم المعلومات", detail)]
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "content", "returned_facts"),
    [
        (
            "en",
            """
            Context — Career stage / المرحلة المهنية: Student
            Context — Target role / الهدف المهني: Python developer
            Evidence — Education / التعليم: none
            Evidence — Experience / الخبرة: no experience yet
            Evidence — Projects & volunteering / المشاريع والتطوع: skip
            Evidence — Skills with evidence / المهارات مع أمثلة: not yet
            Evidence — Certifications / الشهادات: N/A
            Evidence — Achievements / الإنجازات: none
            Evidence — Languages / اللغات: prefer not to answer
            """,
            [
                {
                    "category": "skill",
                    "label": "Python",
                    "detail": None,
                    "source_handle": "segment_2",
                },
                {
                    "category": "experience",
                    "label": "no experience yet",
                    "detail": None,
                    "source_handle": "segment_4",
                },
            ],
        ),
        (
            "ar",
            """
            Context — Career stage / المرحلة المهنية: طالب
            Context — Target role / الهدف المهني: مطور بايثون
            Evidence — Education / التعليم: تخطي
            Evidence — Experience / الخبرة: لا توجد خبرة
            Evidence — Projects & volunteering / المشاريع والتطوع: لا يوجد
            Evidence — Skills with evidence / المهارات مع أمثلة: ما عندي
            Evidence — Certifications / الشهادات: لا توجد شهادات
            Evidence — Achievements / الإنجازات: لا توجد إنجازات
            Evidence — Languages / اللغات: لا شيء
            """,
            [
                {
                    "category": "experience",
                    "label": "مطور بايثون",
                    "detail": None,
                    "source_handle": "segment_2",
                },
                {
                    "category": "experience",
                    "label": "لا توجد خبرة",
                    "detail": None,
                    "source_handle": "segment_4",
                },
            ],
        ),
    ],
)
async def test_context_and_skipped_answers_never_become_professional_facts(
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
    content: str,
    returned_facts: list[dict[str, object]],
) -> None:
    capture = _MistralCapture(content=json.dumps({"facts": returned_facts}, ensure_ascii=False))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    context = ResumeIntakeProviderContext(
        locale=locale,
        mode="builder",
        segments=build_resume_segments(content),
    )

    result = await provider.generate(context)

    assert result == []
    assert len(capture.create_calls) == 1


@pytest.mark.asyncio
async def test_explicit_arabic_sections_fill_model_omissions_without_a_second_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _MistralCapture(
        content=json.dumps(
            {
                "facts": [
                    {
                        "category": "skill",
                        "label": "Python وSQL",
                        "detail": None,
                        "source_handle": "segment_1",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")
    context = ResumeIntakeProviderContext(
        locale="ar",
        mode="upload",
        segments=(
            ResumeSegment(
                handle="segment_1",
                text="المشاريع: لوحة بيانات أسبوعية باستخدام Python وSQL",
            ),
            ResumeSegment(handle="segment_2", text="اللغات: العربية والإنجليزية"),
        ),
    )

    result = await provider.generate(context)

    assert len(capture.create_calls) == 1
    assert {(fact.category, fact.source_excerpt) for fact in result} >= {
        (
            FactCategory.PROJECT,
            "المشاريع: لوحة بيانات أسبوعية باستخدام Python وSQL",
        ),
        (FactCategory.LANGUAGE, "اللغات: العربية والإنجليزية"),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        None,
        "not-json",
        json.dumps(
            {
                "facts": [
                    {
                        "category": "identity",
                        "label": "Name",
                        "detail": None,
                        "source_handle": "segment_1",
                    }
                ]
            }
        ),
        json.dumps({"facts": [], "unexpected": True}),
    ],
)
async def test_invalid_mistral_output_becomes_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
) -> None:
    capture = _MistralCapture(content=content)
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret", model="test-model")

    with pytest.raises(ResumeIntakeProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Resume intake provider returned no usable response"
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_provider_exception_details_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_detail = "upstream included candidate@example.test and secret-key"
    capture = _MistralCapture(provider_error=RuntimeError(sensitive_detail))
    _install_fake_mistral(monkeypatch, capture)
    provider = MistralResumeIntakeProvider(api_key="secret-key", model="test-model")

    with pytest.raises(ResumeIntakeProviderError) as raised:
        await provider.generate(_context())

    assert str(raised.value) == "Resume intake provider request failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert sensitive_detail not in str(raised.value)


def test_provider_factory_uses_only_selected_provider_key() -> None:
    mistral = get_resume_intake_provider(
        Settings(
            _env_file=None,
            environment="test",
            ai_provider="mistral",
            mistral_api_key=SecretStr("mistral-key"),
            ai_model="mistral-small-2603",
        )
    )
    assert isinstance(mistral, MistralResumeIntakeProvider)
    assert mistral.model == "mistral-small-2603"

    openai = get_resume_intake_provider(
        Settings(
            _env_file=None,
            environment="test",
            ai_provider="openai",
            openai_api_key=SecretStr("openai-key"),
            ai_model="gpt-test",
        )
    )
    assert isinstance(openai, OpenAIResumeIntakeProvider)

    wrong_key = get_resume_intake_provider(
        Settings(
            _env_file=None,
            environment="test",
            ai_provider="mistral",
            openai_api_key=SecretStr("openai-key"),
            ai_model="mistral-small-2603",
        )
    )
    assert isinstance(wrong_key, DisabledResumeIntakeProvider)
