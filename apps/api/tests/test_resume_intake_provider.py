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


def test_build_resume_segments_enforces_segment_and_character_caps() -> None:
    many_segments = build_resume_segments("\n".join(f"Skill {index}" for index in range(500)))
    assert len(many_segments) == MAX_RESUME_SEGMENTS

    large_segments = build_resume_segments("x" * 40_000 + "\n" + "y" * 40_000)
    assert sum(len(segment.text) for segment in large_segments) == MAX_RESUME_TEXT_CHARS
    assert large_segments[1].text == "y" * 20_000


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
                "Professional Experience : Data Analyst — Acme; responsibilities: Built and "
                "maintained weekly reports; tools: Python, Power BI"
            ),
        ),
    )


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
