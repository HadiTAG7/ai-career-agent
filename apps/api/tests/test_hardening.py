import httpx
from conftest import create_profile_and_source


async def _confirmed_identity(client: httpx.AsyncClient, profile_id: str) -> dict:
    facts = (
        await client.get(f"/v1/profiles/{profile_id}/facts?verification_status=confirmed")
    ).json()
    return next(fact for fact in facts if fact["category"] == "identity")


async def test_certification_requirement_is_missing_end_to_end(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    updated = await client.patch(
        "/v1/profiles",
        json={"completed_fact_categories": ["certification"]},
    )
    assert updated.status_code == 200
    job_response = await client.post(
        "/v1/jobs/manual",
        json={
            "title": "Cloud Engineer",
            "company": "Example",
            "description": "AWS certification is required.",
        },
    )
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()
    assert [(item["category"], item["normalized_value"]) for item in job["requirements"]] == [
        ("certification", "aws")
    ]

    analysis = await client.post(
        f"/v1/jobs/{job['id']}/analyze",
        json={"profile_id": profile["id"]},
    )
    assert analysis.status_code == 200, analysis.text
    result = analysis.json()
    assert result["requirement_matches"][0]["status"] == "missing"
    assert result["explanation"]["mandatory_missing_count"] == 1


async def test_user_cannot_forge_server_owned_evidence_source_kind(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    for kind in ("cv_upload", "linkedin_export", "licensed_feed"):
        response = await client.post(
            f"/v1/profiles/{profile['id']}/sources",
            json={"kind": kind, "label": "Forged source", "original_filename": "fake.pdf"},
        )
        assert response.status_code == 422


async def test_profile_city_and_years_are_confirmed_matchable_evidence(
    client: httpx.AsyncClient,
) -> None:
    profile_response = await client.post(
        "/v1/profiles",
        json={
            "full_name": "Noura Almutairi",
            "city": "Riyadh",
            "years_experience": 5,
            "preferred_language": "en",
        },
    )
    assert profile_response.status_code == 201
    profile = profile_response.json()
    facts = (
        await client.get(f"/v1/profiles/{profile['id']}/facts?verification_status=confirmed")
    ).json()
    assert {fact["structured_value"].get("profile_field") for fact in facts} >= {
        "full_name",
        "city",
        "years_experience",
    }
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Engineer",
                "company": "Example",
                "description": "Riyadh is required. 3 years experience required.",
            },
        )
    ).json()
    assert (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).status_code == 200
    analysis = await client.post(
        f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]}
    )
    assert analysis.status_code == 200, analysis.text
    assert {match["status"] for match in analysis.json()["requirement_matches"]} == {"matched"}

    changed = await client.patch("/v1/profiles", json={"city": "Jeddah"})
    assert changed.status_code == 200
    updated_facts = (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    city = next(
        fact for fact in updated_facts if fact["structured_value"].get("profile_field") == "city"
    )
    assert city["label"] == "Jeddah"
    assert city["verification_status"] == "unconfirmed"
    assert city["original_extraction"]["label"] == "Riyadh"
    assert (await client.get("/v1/dashboard")).json()["top_opportunities"] == []


async def test_unqualified_requirement_prevents_apply_now_until_reviewed(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    python = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{python['id']}/confirm")
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Engineer",
                "company": "Example",
                "description": "Python required. 5 years of experience.",
            },
        )
    ).json()
    assert any(item["needs_user_review"] for item in job["requirements"])
    analysis = await client.post(
        f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]}
    )
    assert analysis.status_code == 200
    assert analysis.json()["decision"] == "need_information"
    assert analysis.json()["explanation"]["review_required_count"] == 1


async def test_fact_retraction_invalidates_document_and_stale_analysis(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={
                "source_id": source["id"],
                "category": "skill",
                "label": "Python",
                "detail": "Built APIs with Python",
                "source_excerpt": "Skills: Python",
            },
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    await client.patch("/v1/profiles", json={"completed_fact_categories": ["skill"]})
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Backend Engineer",
                "company": "Example",
                "description": "Python is required.",
            },
        )
    ).json()
    assert (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).status_code == 200
    analysis = await client.post(
        f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]}
    )
    assert analysis.json()["decision"] == "apply_now"
    document = (
        await client.post(
            "/v1/documents",
            json={
                "profile_id": profile["id"],
                "job_id": job["id"],
                "kind": "cv",
                "language": "en",
                "title": "CV",
                "status": "export_ready",
                "claims": [
                    {
                        "claim_type": "skill",
                        "text": "Built APIs with Python",
                        "evidence_fact_ids": [fact["id"]],
                    }
                ],
            },
        )
    ).json()
    assert document["status"] == "draft"
    assert (await client.post(f"/v1/documents/{document['id']}/review")).status_code == 200

    revoked = await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/unconfirm")
    assert revoked.status_code == 200
    assert revoked.json()["verification_status"] == "unconfirmed"
    assert (await client.get(f"/v1/documents/{document['id']}")).json()["status"] == "draft"
    validation = (await client.post(f"/v1/documents/{document['id']}/validate")).json()
    assert validation["valid"] is False
    assert validation["export_allowed"] is False
    assert (await client.get("/v1/dashboard")).json()["top_opportunities"] == []

    denied = await client.patch(
        f"/v1/profiles/{profile['id']}/facts/{fact['id']}",
        headers={"X-User-Id": "other-owner"},
        json={"label": "Python 3", "correction_reason": "Correct version"},
    )
    assert denied.status_code == 404
    immutable_source = await client.patch(
        f"/v1/profiles/{profile['id']}/facts/{fact['id']}",
        json={"source_id": source["id"], "correction_reason": "Move source"},
    )
    assert immutable_source.status_code == 422
    corrected = await client.patch(
        f"/v1/profiles/{profile['id']}/facts/{fact['id']}",
        json={"label": "Python 3", "correction_reason": "Correct version"},
    )
    assert corrected.status_code == 200, corrected.text
    corrected_fact = corrected.json()
    assert corrected_fact["verification_status"] == "unconfirmed"
    assert corrected_fact["source_excerpt"] == "Skills: Python"
    assert corrected_fact["original_extraction"]["label"] == "Python"
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    stale_excerpt_claim = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cv",
            "language": "en",
            "title": "Stale evidence CV",
            "claims": [
                {
                    "claim_type": "skill",
                    "text": "Skills: Python",
                    "evidence_fact_ids": [fact["id"]],
                }
            ],
        },
    )
    assert stale_excerpt_claim.status_code == 422


async def test_profile_name_change_preserves_identity_provenance_and_requires_reconfirmation(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    original = await _confirmed_identity(client, profile["id"])
    direct_edit = await client.patch(
        f"/v1/profiles/{profile['id']}/facts/{original['id']}",
        json={"label": "Wrong path", "correction_reason": "Try direct edit"},
    )
    assert direct_edit.status_code == 409
    assert (await client.get("/v1/profiles")).json()["full_name"] == profile["full_name"]
    response = await client.patch("/v1/profiles", json={"full_name": "Noura Almutairi"})
    assert response.status_code == 200
    facts = (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
    identity = next(fact for fact in facts if fact["id"] == original["id"])
    assert identity["label"] == "Noura Almutairi"
    assert identity["verification_status"] == "unconfirmed"
    assert identity["confirmed_at"] is None
    assert identity["original_extraction"]["label"] == original["label"]
    assert identity["user_correction_reason"] == "Profile full_name changed by user"


async def test_requirement_correction_is_owned_audited_and_requires_reanalysis(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    await client.patch("/v1/profiles", json={"completed_fact_categories": ["skill"]})
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
    preliminary = (
        await client.post(f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]})
    ).json()
    assert preliminary["decision"] == "need_information"
    assert preliminary["explanation"]["decision_preliminary"] is True
    assert (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).status_code == 200
    first = (
        await client.post(f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]})
    ).json()
    assert first["decision"] == "apply_now"
    latest = await client.get(f"/v1/jobs/{job['id']}/analyses/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == first["id"]
    hidden = await client.get(
        f"/v1/jobs/{job['id']}/analyses/latest",
        headers={"X-User-Id": "other-owner"},
    )
    assert hidden.status_code == 404
    requirement = job["requirements"][0]

    denied = await client.patch(
        f"/v1/jobs/{job['id']}/requirements/{requirement['id']}",
        headers={"X-User-Id": "other-owner"},
        json={"normalized_value": "sql", "correction_reason": "Parser correction"},
    )
    assert denied.status_code == 404
    corrected = await client.patch(
        f"/v1/jobs/{job['id']}/requirements/{requirement['id']}",
        json={
            "text": "SQL is required.",
            "correction_reason": "The parser selected the wrong skill",
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["normalized_value"] == "sql"
    assert corrected.json()["original_extraction"]["normalized_value"] == "python"
    assert corrected.json()["user_corrected_at"]
    assert (await client.get("/v1/dashboard")).json()["top_opportunities"] == []
    assert (await client.get(f"/v1/jobs/{job['id']}/analyses/latest")).status_code == 404

    changed_job = (await client.get(f"/v1/jobs/{job['id']}")).json()
    assert changed_job["requirements_reviewed_at"] is None
    assert (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).status_code == 200

    second = await client.post(f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]})
    assert second.status_code == 200
    assert second.json()["requirement_matches"][0]["status"] == "missing"

    denied_add = await client.post(
        f"/v1/jobs/{job['id']}/requirements",
        headers={"X-User-Id": "other-owner"},
        json={
            "category": "skill",
            "importance": "mandatory",
            "text": "Python is required",
            "normalized_value": "python",
            "correction_reason": "Missing from extraction",
        },
    )
    assert denied_add.status_code == 404
    added = await client.post(
        f"/v1/jobs/{job['id']}/requirements",
        json={
            "category": "skill",
            "importance": "mandatory",
            "text": "Python is required",
            "normalized_value": "python",
            "correction_reason": "Missing from extraction",
        },
    )
    assert added.status_code == 201
    assert added.json()["user_added"] is True
    retired = await client.post(
        f"/v1/jobs/{job['id']}/requirements/{requirement['id']}/retire",
        json={"correction_reason": "SQL is not actually a requirement"},
    )
    assert retired.status_code == 200
    assert retired.json()["is_active"] is False
    assert (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).status_code == 200
    third = await client.post(f"/v1/jobs/{job['id']}/analyze", json={"profile_id": profile["id"]})
    assert third.status_code == 200
    assert len(third.json()["requirement_matches"]) == 1
    assert third.json()["requirement_matches"][0]["status"] == "matched"


async def test_requirement_review_is_idempotent_and_preserves_current_analysis(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Backend Engineer",
                "company": "Example",
                "description": "Python is required.",
            },
        )
    ).json()

    first_review = (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).json()
    analysis = (
        await client.post(
            f"/v1/jobs/{job['id']}/analyze",
            json={"profile_id": profile["id"]},
        )
    ).json()
    second_review = (await client.post(f"/v1/jobs/{job['id']}/requirements/review")).json()
    latest = await client.get(f"/v1/jobs/{job['id']}/analyses/latest")

    assert second_review["requirements_revision"] == first_review["requirements_revision"]
    assert latest.status_code == 200
    assert latest.json()["id"] == analysis["id"]


async def test_saving_the_same_job_twice_returns_conflict(
    client: httpx.AsyncClient,
) -> None:
    profile, _source = await create_profile_and_source(client)
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Data Analyst",
                "company": "Example",
                "description": "SQL is required.",
            },
        )
    ).json()
    payload = {"profile_id": profile["id"], "job_id": job["id"], "status": "saved"}

    first = await client.post("/v1/applications", json=payload)
    duplicate = await client.post("/v1/applications", json=payload)
    applications = await client.get("/v1/applications")

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert len(applications.json()) == 1


async def test_tracker_notes_remain_editable_after_linked_analysis_becomes_stale(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact = (
        await client.post(
            f"/v1/profiles/{profile['id']}/facts",
            json={"source_id": source["id"], "category": "skill", "label": "Python"},
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={
                "title": "Backend Engineer",
                "company": "Example",
                "description": "Python is required.",
            },
        )
    ).json()
    await client.post(f"/v1/jobs/{job['id']}/requirements/review")
    analysis = (
        await client.post(
            f"/v1/jobs/{job['id']}/analyze",
            json={"profile_id": profile["id"]},
        )
    ).json()
    application = (
        await client.post(
            "/v1/applications",
            json={
                "profile_id": profile["id"],
                "job_id": job["id"],
                "analysis_id": analysis["id"],
                "status": "saved",
            },
        )
    ).json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/unconfirm")

    notes_update = await client.patch(
        f"/v1/applications/{application['id']}",
        json={"notes": "Refresh the analysis before preparing documents"},
    )
    stale_relink = await client.patch(
        f"/v1/applications/{application['id']}",
        json={"analysis_id": analysis["id"]},
    )

    assert notes_update.status_code == 200, notes_update.text
    assert notes_update.json()["notes"] == "Refresh the analysis before preparing documents"
    assert stale_relink.status_code == 422


async def test_ready_application_requires_reviewed_cv(client: httpx.AsyncClient) -> None:
    profile, _source = await create_profile_and_source(client)
    identity = await _confirmed_identity(client, profile["id"])
    job = (
        await client.post(
            "/v1/jobs/manual",
            json={"title": "Designer", "company": "Example", "description": "Portfolio."},
        )
    ).json()
    document = (
        await client.post(
            "/v1/documents",
            json={
                "profile_id": profile["id"],
                "job_id": job["id"],
                "kind": "cv",
                "language": "ar",
                "title": "CV",
                "status": "export_ready",
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
    assert document["status"] == "draft"
    rejected = await client.post(
        "/v1/applications",
        json={
            "profile_id": profile["id"],
            "job_id": job["id"],
            "cv_document_id": document["id"],
            "status": "ready",
        },
    )
    assert rejected.status_code == 422
    assert (await client.post(f"/v1/documents/{document['id']}/review")).status_code == 200
    accepted = await client.post(
        "/v1/applications",
        json={
            "profile_id": profile["id"],
            "job_id": job["id"],
            "cv_document_id": document["id"],
            "status": "ready",
        },
    )
    assert accepted.status_code == 201, accepted.text
