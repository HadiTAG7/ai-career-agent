import httpx
from conftest import create_profile_and_source


async def create_job(client: httpx.AsyncClient, owner: str, company: str) -> dict:
    response = await client.post(
        "/v1/jobs/manual",
        headers={"X-User-Id": owner},
        json={
            "title": "Backend Developer",
            "company": company,
            "description": "Python is required.",
            "requirements": [
                {
                    "category": "skill",
                    "importance": "mandatory",
                    "text": "Python is required",
                    "normalized_value": "python",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_export_and_delete_are_owner_scoped(client: httpx.AsyncClient) -> None:
    profile_a, _ = await create_profile_and_source(client, user_id="owner-a")
    profile_b, _ = await create_profile_and_source(client, user_id="owner-b")
    job_a = await create_job(client, "owner-a", "Company A")
    job_b = await create_job(client, "owner-b", "Company B")

    exported = await client.get("/v1/me/export", headers={"X-User-Id": "owner-a"})
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["profile"]["id"] == profile_a["id"]
    assert [job["id"] for job in payload["jobs"]] == [job_a["id"]]
    assert job_b["id"] not in exported.text
    assert "attachment" in exported.headers["content-disposition"]

    deleted = await client.delete("/v1/me/data", headers={"X-User-Id": "owner-a"})
    assert deleted.status_code == 200, deleted.text
    receipt = deleted.json()
    assert receipt["deleted_counts"]["profiles"] == 1
    assert receipt["deleted_counts"]["jobs"] == 1
    assert "owner-a" not in deleted.text

    missing_a = await client.get("/v1/profiles", headers={"X-User-Id": "owner-a"})
    assert missing_a.status_code == 404
    jobs_a = await client.get("/v1/jobs", headers={"X-User-Id": "owner-a"})
    assert jobs_a.json() == []

    surviving_b = await client.get("/v1/profiles", headers={"X-User-Id": "owner-b"})
    assert surviving_b.status_code == 200
    assert surviving_b.json()["id"] == profile_b["id"]
    jobs_b = await client.get("/v1/jobs", headers={"X-User-Id": "owner-b"})
    assert [job["id"] for job in jobs_b.json()] == [job_b["id"]]


async def test_export_and_delete_are_available_before_onboarding(
    client: httpx.AsyncClient,
) -> None:
    headers = {"X-User-Id": "empty-account"}
    exported = await client.get("/v1/me/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["profile"] is None
    assert exported.json()["jobs"] == []

    deleted = await client.delete("/v1/me/data", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_counts"]["profiles"] == 0
