import asyncio
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select

import career_agent_api.models  # noqa: F401
from career_agent_api.core.config import get_settings
from career_agent_api.db.base import Base
from career_agent_api.db.session import get_engine, get_session_factory
from career_agent_api.models.domain import (
    CareerFact,
    CareerProfile,
    EvidenceSource,
    Job,
    JobRequirement,
)
from career_agent_api.models.enums import (
    FactCategory,
    IntakeMethod,
    PreferredLanguage,
    RequirementCategory,
    RequirementImportance,
    SourceKind,
    VerificationStatus,
)
from career_agent_api.services.policies import (
    get_or_create_deny_by_default_policy,
    seed_source_policies,
)


async def seed_demo() -> None:
    settings = get_settings()
    if settings.environment == "production":
        raise RuntimeError("Demo seed is disabled in production")
    if settings.auto_create_schema:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        await seed_source_policies(session)
        existing = await session.scalar(
            select(CareerProfile).where(CareerProfile.owner_id == "demo-user")
        )
        if existing:
            await session.commit()
            print(f"Demo profile already exists: {existing.id}")
            return
        profile = CareerProfile(
            owner_id="demo-user",
            full_name="نورة المطيري",
            headline="مطورة برمجيات مبتدئة",
            preferred_language=PreferredLanguage.AR,
            city="الرياض",
            years_experience=1,
        )
        session.add(profile)
        await session.flush()
        source = EvidenceSource(
            profile_id=profile.id,
            kind=SourceKind.MANUAL,
            label="Demo facts confirmed by user",
            source_metadata={"demo": True},
        )
        session.add(source)
        await session.flush()
        for category, label, detail in (
            (FactCategory.SKILL, "Python", "Built APIs with Python and FastAPI"),
            (FactCategory.SKILL, "SQL", "Designed relational queries and schemas"),
            (FactCategory.EDUCATION, "بكالوريوس علوم الحاسب", "جامعة سعودية، 2025"),
            (FactCategory.LANGUAGE, "العربية والإنجليزية", "العربية أم، الإنجليزية مهنية"),
            (FactCategory.PROJECT, "منصة تحليل بيانات", "مشروع تخرج موثق"),
        ):
            session.add(
                CareerFact(
                    profile_id=profile.id,
                    source_id=source.id,
                    category=category,
                    label=label,
                    detail=detail,
                    structured_value={},
                    verification_status=VerificationStatus.CONFIRMED,
                    confirmed_at=datetime.now(UTC),
                )
            )
        policy = await get_or_create_deny_by_default_policy(session, "manual")
        description = "مطلوب إتقان Python وSQL. يفضل معرفة FastAPI. يشترط بكالوريوس تقني."
        job = Job(
            owner_id="demo-user",
            source_policy_id=policy.id,
            intake_method=IntakeMethod.MANUAL,
            title="Junior Backend Developer",
            company="شركة تقنية تجريبية",
            description=description,
            location="الرياض",
            content_hash=sha256(description.encode()).hexdigest(),
        )
        session.add(job)
        await session.flush()
        for category, importance, text_value, normalized in (
            (
                RequirementCategory.SKILL,
                RequirementImportance.MANDATORY,
                "مطلوب إتقان Python",
                "python",
            ),
            (
                RequirementCategory.SKILL,
                RequirementImportance.MANDATORY,
                "مطلوب إتقان SQL",
                "sql",
            ),
            (
                RequirementCategory.EDUCATION,
                RequirementImportance.MANDATORY,
                "يشترط بكالوريوس تقني",
                "بكالوريوس",
            ),
        ):
            session.add(
                JobRequirement(
                    job_id=job.id,
                    category=category,
                    importance=importance,
                    text=text_value,
                    normalized_value=normalized,
                    weight=1,
                )
            )
        await session.commit()
        print(f"Seeded demo profile {profile.id} and job {job.id}")


if __name__ == "__main__":
    asyncio.run(seed_demo())
