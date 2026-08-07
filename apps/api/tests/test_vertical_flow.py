import httpx
from conftest import create_profile_and_source


async def test_profile_job_analysis_application_outcome_dashboard_flow(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact_response = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Python",
            "detail": "Built a FastAPI service",
        },
    )
    fact_id = fact_response.json()["id"]
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact_id}/confirm")

    job_response = await client.post(
        "/v1/jobs/manual",
        json={
            "title": "Junior Backend Developer",
            "company": "Example Tech",
            "description": "Python is required.",
            "requirements": [
                {
                    "category": "skill",
                    "importance": "mandatory",
                    "text": "Python is required",
                    "normalized_value": "python",
                    "weight": 1,
                }
            ],
        },
    )
    job = job_response.json()
    reviewed_requirements = await client.post(f"/v1/jobs/{job['id']}/requirements/review")
    assert reviewed_requirements.status_code == 200
    analysis_response = await client.post(
        f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]}
    )
    assert analysis_response.status_code == 200, analysis_response.text
    analysis = analysis_response.json()
    assert analysis["coverage_score"] == 100
    assert analysis["readiness_band"] == "high"
    assert analysis["decision"] == "apply_now"

    identity_facts = (
        await client.get(f"/v1/profiles/{profile['id']}/facts?verification_status=confirmed")
    ).json()
    identity = next(fact for fact in identity_facts if fact["category"] == "identity")
    document_response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "job_id": job["id"],
            "kind": "cv",
            "language": "ar",
            "title": "CV",
            "claims": [
                {
                    "claim_type": "identity",
                    "text": identity["label"],
                    "evidence_fact_ids": [identity["id"]],
                }
            ],
        },
    )
    assert document_response.status_code == 201, document_response.text
    document = document_response.json()
    reviewed = await client.post(f"/v1/documents/{document['id']}/review")
    assert reviewed.status_code == 200, reviewed.text

    application_response = await client.post(
        "/v1/applications",
        json={
            "profile_id": profile["id"],
            "job_id": job["id"],
            "analysis_id": analysis["id"],
            "cv_document_id": document["id"],
            "status": "submitted",
        },
    )
    assert application_response.status_code == 201, application_response.text
    application = application_response.json()
    assert application["submitted_at"] is not None

    outcome_response = await client.post(
        f"/v1/applications/{application['id']}/outcomes",
        json={
            "kind": "interview",
            "occurred_at": "2026-08-10T12:00:00Z",
            "confirmed_by_user": True,
            "qualified_human_interview": True,
            "detail": "Recruiter screen with a person",
        },
    )
    assert outcome_response.status_code == 201

    dashboard_response = await client.get("/v1/dashboard")
    assert dashboard_response.status_code == 200, dashboard_response.text
    dashboard = dashboard_response.json()
    assert dashboard["application_pipeline"]["interview"] == 1
    assert dashboard["submitted_applications"] == 1
    assert dashboard["qualified_interviews"] == 1
    assert dashboard["qualified_interviews_per_completed_application"] == 1.0
    assert dashboard["top_opportunities"][0]["id"] == analysis["id"]


async def test_pasted_job_extracts_reviews_analyzes_and_saves_to_dashboard(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    confirmed_python = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(
        f"/v1/profiles/{profile['id']}/facts/{confirmed_python['id']}/confirm"
    )
    await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={"source_id": source["id"], "category": "skill", "label": "SQL"},
    )
    await client.patch("/v1/profiles", json={"completed_fact_categories": ["skill"]})

    job_response = await client.post(
        "/v1/jobs/manual",
        json={
            "title": "Data Engineer",
            "company": "Example",
            "description": "Python is required. SQL is required.",
        },
    )
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()
    assert {item["normalized_value"] for item in job["requirements"]} == {"python", "sql"}

    reviewed = await client.post(f"/v1/jobs/{job['id']}/requirements/review")
    assert reviewed.status_code == 200
    analysis_response = await client.post(
        f"/v1/jobs/{job['id']}/analyze",
        json={"profile_id": profile["id"]},
    )
    assert analysis_response.status_code == 200, analysis_response.text
    analysis = analysis_response.json()
    statuses = {
        match["requirement"]["normalized_value"]: match["status"]
        for match in analysis["requirement_matches"]
    }
    assert statuses == {"python": "matched", "sql": "missing"}

    saved = await client.post(
        "/v1/applications",
        json={
            "profile_id": profile["id"],
            "job_id": job["id"],
            "analysis_id": analysis["id"],
            "status": "saved",
        },
    )
    assert saved.status_code == 201, saved.text
    dashboard = (await client.get("/v1/dashboard")).json()
    assert dashboard["application_pipeline"]["saved"] == 1
    assert dashboard["top_opportunities"][0]["id"] == analysis["id"]


async def test_user_cannot_read_another_users_profile(client: httpx.AsyncClient) -> None:
    await create_profile_and_source(client, user_id="owner-a")
    response = await client.get("/v1/profiles", headers={"X-User-Id": "owner-b"})
    assert response.status_code == 404


async def test_interview_outcome_requires_confirmed_submission(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    job_response = await client.post(
        "/v1/jobs/manual",
        json={
            "title": "Data Analyst",
            "company": "Example",
            "description": "SQL is required.",
        },
    )
    application_response = await client.post(
        "/v1/applications",
        json={
            "profile_id": profile["id"],
            "job_id": job_response.json()["id"],
            "status": "saved",
        },
    )
    application = application_response.json()
    outcome_payload = {
        "kind": "interview",
        "occurred_at": "2026-08-10T12:00:00Z",
        "confirmed_by_user": True,
        "qualified_human_interview": True,
    }

    rejected = await client.post(
        f"/v1/applications/{application['id']}/outcomes",
        json=outcome_payload,
    )
    assert rejected.status_code == 409

    identity = next(
        fact
        for fact in (
            await client.get(f"/v1/profiles/{profile['id']}/facts?verification_status=confirmed")
        ).json()
        if fact["category"] == "identity"
    )
    document = (
        await client.post(
            "/v1/documents",
            json={
                "profile_id": profile["id"],
                "job_id": job_response.json()["id"],
                "kind": "cv",
                "language": "ar",
                "title": "CV",
                "claims": [
                    {
                        "claim_type": "identity",
                        "text": identity["label"],
                        "evidence_fact_ids": [identity["id"]],
                    }
                ],
            },
        )
    ).json()
    reviewed = await client.post(f"/v1/documents/{document['id']}/review")
    assert reviewed.status_code == 200

    submitted = await client.patch(
        f"/v1/applications/{application['id']}",
        json={"status": "interview", "cv_document_id": document["id"]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["submitted_at"] is not None

    accepted = await client.post(
        f"/v1/applications/{application['id']}/outcomes",
        json=outcome_payload,
    )
    assert accepted.status_code == 201
    dashboard = (await client.get("/v1/dashboard")).json()
    assert dashboard["submitted_applications"] == 1
    assert dashboard["qualified_interviews"] == 1
    assert dashboard["qualified_interviews_per_completed_application"] == 1.0
