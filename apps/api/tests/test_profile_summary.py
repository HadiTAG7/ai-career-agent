import httpx
from conftest import create_profile_and_source


async def test_profile_summary_and_dashboard_share_the_same_quality_definition(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    initial = (await client.get(f"/v1/profiles/{profile['id']}/summary")).json()
    assert initial["profile_quality_percent"] == 0
    assert initial["confirmed_facts"] == 2
    assert initial["covered_quality_categories"] == []

    created = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Python",
            "detail": "Built a FastAPI service",
        },
    )
    fact_id = created.json()["id"]
    before_confirmation = (
        await client.get(f"/v1/profiles/{profile['id']}/summary")
    ).json()
    assert before_confirmation["profile_quality_percent"] == 0
    assert before_confirmation["unconfirmed_facts"] == 1

    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact_id}/confirm")
    after_confirmation = (
        await client.get(f"/v1/profiles/{profile['id']}/summary")
    ).json()
    dashboard = (await client.get("/v1/dashboard")).json()
    assert after_confirmation["profile_quality_percent"] == 17
    assert after_confirmation["covered_quality_categories"] == ["skill"]
    assert dashboard["profile_quality_percent"] == after_confirmation["profile_quality_percent"]


async def test_no_op_profile_and_fact_mutations_do_not_advance_evidence_revision(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    identity = next(
        fact
        for fact in (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
        if fact["category"] == "identity"
    )

    same_profile = await client.patch(
        "/v1/profiles",
        json={"full_name": profile["full_name"], "completed_fact_categories": []},
    )
    assert same_profile.status_code == 200
    assert same_profile.json()["evidence_revision"] == 0
    unchanged_identity = next(
        fact
        for fact in (await client.get(f"/v1/profiles/{profile['id']}/facts")).json()
        if fact["id"] == identity["id"]
    )
    assert unchanged_identity["verification_status"] == "confirmed"

    created = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "SQL",
        },
    )
    fact_id = created.json()["id"]
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact_id}/confirm")
    revision_after_confirm = (await client.get("/v1/profiles")).json()["evidence_revision"]
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact_id}/confirm")
    assert (await client.get("/v1/profiles")).json()["evidence_revision"] == revision_after_confirm

    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact_id}/unconfirm")
    revision_after_unconfirm = (await client.get("/v1/profiles")).json()["evidence_revision"]
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact_id}/unconfirm")
    repeated_unconfirm_revision = (await client.get("/v1/profiles")).json()[
        "evidence_revision"
    ]
    assert repeated_unconfirm_revision == revision_after_unconfirm


async def test_combined_profile_change_advances_revision_once(client: httpx.AsyncClient) -> None:
    await create_profile_and_source(client)

    response = await client.patch(
        "/v1/profiles",
        json={"city": "جدة", "completed_fact_categories": ["skill"]},
    )

    assert response.status_code == 200
    assert response.json()["evidence_revision"] == 1
