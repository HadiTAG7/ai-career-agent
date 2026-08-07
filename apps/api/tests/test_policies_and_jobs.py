import httpx
import pytest
from conftest import create_profile_and_source
from fastapi import HTTPException

from career_agent_api.models.domain import SourcePolicy
from career_agent_api.models.enums import IntakeMethod
from career_agent_api.services.policies import require_automatic_permission


async def test_linkedin_url_is_stored_but_never_fetched(client: httpx.AsyncClient) -> None:
    await create_profile_and_source(client)
    response = await client.post(
        "/v1/jobs/manual",
        json={
            "source_key": "manual",
            "source_url": "https://www.linkedin.com/jobs/view/12345",
            "title": "Junior Software Engineer",
            "company": "Example",
            "description": "Must know Python.",
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["source_policy"]["source_key"] == "linkedin"
    assert job["source_policy"]["can_search_automatically"] is False
    assert job["source_policy"]["can_fetch_details"] is False
    assert job["source_policy"]["can_apply_automatically"] is False
    assert job["intake_method"] == "manual"
    assert job["fetched_at"] is None


async def test_unknown_source_is_deny_by_default(client: httpx.AsyncClient) -> None:
    await create_profile_and_source(client)
    response = await client.post(
        "/v1/jobs/manual",
        json={
            "source_key": "new-board",
            "title": "Data Analyst",
            "company": "Example",
            "description": "SQL is preferred.",
        },
    )
    assert response.status_code == 201
    policy = response.json()["source_policy"]
    assert policy["permission_basis"].startswith("Unreviewed source")
    assert not any(
        (
            policy["can_search_automatically"],
            policy["can_fetch_details"],
            policy["can_apply_automatically"],
        )
    )


def test_policy_gate_denies_automatic_fetch() -> None:
    policy = SourcePolicy(
        source_key="indeed",
        display_name="Indeed",
        intake_method=IntakeMethod.MANUAL,
        permission_basis="User text only",
        can_search_automatically=False,
        can_fetch_details=False,
        can_apply_automatically=False,
    )
    with pytest.raises(HTTPException) as exc_info:
        require_automatic_permission(policy, "fetch")
    assert exc_info.value.status_code == 403

    inactive_policy = SourcePolicy(
        source_key="licensed-but-disabled",
        display_name="Disabled feed",
        intake_method=IntakeMethod.LICENSED_FEED,
        permission_basis="Contract paused",
        can_search_automatically=True,
        can_fetch_details=True,
        can_apply_automatically=True,
        active=False,
    )
    with pytest.raises(HTTPException) as inactive_exc:
        require_automatic_permission(inactive_policy, "fetch")
    assert inactive_exc.value.status_code == 403


async def test_job_cannot_be_persisted_before_profile_onboarding(
    client: httpx.AsyncClient,
) -> None:
    headers = {"X-User-Id": "not-onboarded"}
    response = await client.post(
        "/v1/jobs/manual",
        headers=headers,
        json={
            "title": "Data Analyst",
            "company": "Example",
            "description": "SQL is required.",
        },
    )
    assert response.status_code == 404
    jobs = await client.get("/v1/jobs", headers=headers)
    assert jobs.json() == []
