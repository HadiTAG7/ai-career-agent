from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from conftest import create_profile_and_source
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from career_agent_api.api.router import (
    _guard_analysis_snapshot,
    _guard_document_review_snapshot,
)
from career_agent_api.models.domain import CareerProfile, DocumentVersion, Job


async def _job_with_reviewed_python_requirement(client: httpx.AsyncClient, profile_id: str) -> dict:
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Engineer",
                "company": "Example",
                "description": "Python is required.",
            },
        )
    ).json()
    reviewed = await client.post(f"/v1/jobs/{job['id']}/requirements/review")
    assert reviewed.status_code == 200
    return (await client.get(f"/v1/jobs/{job['id']}")).json()


async def test_analysis_snapshot_guard_rejects_retracted_evidence_and_corrected_requirements(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    profile, source = await create_profile_and_source(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    job = await _job_with_reviewed_python_requirement(client, profile["id"])
    before = (await client.get("/v1/profiles")).json()
    stale_evidence_revision = before["evidence_revision"]
    stale_requirements_revision = job["requirements_revision"]
    analysis = await client.post(
        f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]}
    )
    assert analysis.status_code == 200
    assert analysis.json()["evidence_revision"] == stale_evidence_revision
    assert analysis.json()["requirements_revision"] == stale_requirements_revision

    async with session_factory() as session:
        await session.execute(
            update(CareerProfile)
            .where(CareerProfile.id == UUID(profile["id"]))
            .values(evidence_revision=CareerProfile.evidence_revision + 1)
        )
        await session.commit()
    # Defense in depth: a stale snapshot is hidden even if a future code path misses explicit
    # invalidation.
    assert (await client.get(f"/v1/jobs/{job['id']}/analyses/latest")).status_code == 404

    revoked = await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/unconfirm")
    assert revoked.status_code == 200
    after_revoke = (await client.get("/v1/profiles")).json()
    assert after_revoke["evidence_revision"] > stale_evidence_revision

    async with session_factory() as session:
        current_profile = await session.scalar(
            select(CareerProfile).where(CareerProfile.id == UUID(profile["id"]))
        )
        current_job = await session.scalar(select(Job).where(Job.id == UUID(job["id"])))
        with pytest.raises(HTTPException) as evidence_conflict:
            await _guard_analysis_snapshot(
                session,
                current_profile,
                current_job,
                stale_evidence_revision,
                stale_requirements_revision,
            )
        assert evidence_conflict.value.status_code == 409

    requirement = job["requirements"][0]
    corrected = await client.patch(
        f"/v1/jobs/{job['id']}/requirements/{requirement['id']}",
        json={"text": "SQL is required.", "correction_reason": "Correct parser output"},
    )
    assert corrected.status_code == 200
    current_profile_payload = (await client.get("/v1/profiles")).json()
    current_job_payload = (await client.get(f"/v1/jobs/{job['id']}")).json()
    assert current_job_payload["requirements_revision"] > stale_requirements_revision

    async with session_factory() as session:
        current_profile = await session.scalar(
            select(CareerProfile).where(CareerProfile.id == UUID(profile["id"]))
        )
        current_job = await session.scalar(select(Job).where(Job.id == UUID(job["id"])))
        with pytest.raises(HTTPException) as requirement_conflict:
            await _guard_analysis_snapshot(
                session,
                current_profile,
                current_job,
                current_profile_payload["evidence_revision"],
                stale_requirements_revision,
            )
        assert requirement_conflict.value.status_code == 409


async def test_document_review_snapshot_guard_rejects_retracted_fact(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    profile, source = await create_profile_and_source(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    stale_revision = (await client.get("/v1/profiles")).json()["evidence_revision"]
    document = (
        await client.post(
            "/v1/documents",
            json={
                "profile_id": profile["id"],
                "kind": "cv",
                "language": "en",
                "title": "CV",
                "claims": [
                    {
                        "claim_type": "skill",
                        "text": "Python",
                        "evidence_fact_ids": [fact["id"]],
                    }
                ],
            },
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/unconfirm")

    async with session_factory() as session:
        current_profile = await session.scalar(
            select(CareerProfile).where(CareerProfile.id == UUID(profile["id"]))
        )
        current_document = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.id == UUID(document["id"]))
        )
        with pytest.raises(HTTPException) as conflict:
            await _guard_document_review_snapshot(
                session,
                current_document,
                current_profile,
                stale_revision,
            )
        assert conflict.value.status_code == 409

    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    reviewed = await client.post(f"/v1/documents/{document['id']}/review")
    assert reviewed.status_code == 200
    current_revision = (await client.get("/v1/profiles")).json()["evidence_revision"]
    assert reviewed.json()["evidence_revision_at_review"] == current_revision


async def test_deletion_marker_rejects_late_profile_and_job_mutations(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    profile, source = await create_profile_and_source(client)
    async with session_factory() as session:
        await session.execute(
            update(CareerProfile)
            .where(CareerProfile.id == UUID(profile["id"]))
            .values(deletion_started_at=datetime.now(UTC))
        )
        await session.commit()

    late_fact = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={"source_id": source["id"], "category": "skill", "label": "Late fact"},
    )
    assert late_fact.status_code == 409
    late_job = await client.post(
        "/v1/jobs/manual",
        json={"title": "Late job", "company": "Example", "description": "SQL required."},
    )
    assert late_job.status_code == 409
    assert (await client.get("/v1/jobs")).json() == []
