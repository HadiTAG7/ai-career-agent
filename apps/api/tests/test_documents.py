import httpx
from conftest import create_profile_and_source


async def test_factual_claim_requires_confirmed_evidence(client: httpx.AsyncClient) -> None:
    profile, source = await create_profile_and_source(client)
    fact_response = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Python",
            "detail": "Built APIs with Python",
        },
    )
    assert fact_response.status_code == 201
    fact = fact_response.json()
    document_payload = {
        "profile_id": profile["id"],
        "kind": "cv",
        "language": "en",
        "title": "Backend CV",
        "status": "export_ready",
        "content": "Injected statement that was not annotated",
        "claims": [
            {
                "claim_type": "skill",
                "text": "Built APIs with Python",
                "evidence_fact_ids": [fact["id"]],
            }
        ],
    }

    rejected = await client.post("/v1/documents", json=document_payload)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "unsupported_claims"

    confirmed = await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    assert confirmed.status_code == 200
    accepted = await client.post("/v1/documents", json=document_payload)
    assert accepted.status_code == 201, accepted.text
    document = accepted.json()
    assert document["status"] == "draft"
    assert document["content"] == "Built APIs with Python"
    assert document["claims"][0]["supported"] is True

    validation = await client.post(f"/v1/documents/{document['id']}/validate")
    assert validation.json() == {
        "document_id": document["id"],
        "valid": True,
        "unsupported_claim_ids": [],
        "export_allowed": False,
    }
    reviewed = await client.post(f"/v1/documents/{document['id']}/review")
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "export_ready"
    assert reviewed.json()["review_hash"]
    validated_review = await client.post(f"/v1/documents/{document['id']}/validate")
    assert validated_review.json()["export_allowed"] is True


async def test_factual_claim_without_any_evidence_is_rejected(client: httpx.AsyncClient) -> None:
    profile, _source = await create_profile_and_source(client)
    response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cover_letter",
            "language": "ar",
            "title": "رسالة تقديم",
            "claims": [
                {
                    "claim_type": "achievement",
                    "text": "رفعت الأداء بنسبة 40%",
                    "evidence_fact_ids": [],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["claims"][0]["reason"] == "Factual claim has no evidence"


async def test_claim_cannot_invent_number_missing_from_confirmed_evidence(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact_response = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "achievement",
            "label": "Improved application performance",
            "detail": "Reduced response time through query optimization",
        },
    )
    fact = fact_response.json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cv",
            "language": "en",
            "title": "CV",
            "claims": [
                {
                    "claim_type": "achievement",
                    "text": "Improved application performance by 40%",
                    "evidence_fact_ids": [fact["id"]],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "40%" in response.json()["detail"]["claims"][0]["reason"]


async def test_non_factual_type_cannot_hide_a_career_claim(client: httpx.AsyncClient) -> None:
    profile, _source = await create_profile_and_source(client)
    response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cover_letter",
            "language": "en",
            "title": "Cover letter",
            "claims": [
                {
                    "claim_type": "transition",
                    "text": "Led a team of 12 engineers",
                    "evidence_fact_ids": [],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "approved server template" in response.json()["detail"]["claims"][0]["reason"]


async def test_factual_claim_rejects_unsupported_qualifiers(client: httpx.AsyncClient) -> None:
    profile, source = await create_profile_and_source(client)
    fact_response = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "skill",
            "label": "Python",
            "detail": "Built APIs with Python",
        },
    )
    fact = fact_response.json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")

    response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cv",
            "language": "en",
            "title": "CV",
            "claims": [
                {
                    "claim_type": "skill",
                    "text": "Senior Python expert who led enterprise API programs",
                    "evidence_fact_ids": [fact["id"]],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "fully grounded" in response.json()["detail"]["claims"][0]["reason"]


async def test_approved_non_factual_template_is_accepted(client: httpx.AsyncClient) -> None:
    profile, _source = await create_profile_and_source(client)
    response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cover_letter",
            "language": "en",
            "title": "Cover letter",
            "claims": [
                {
                    "claim_type": "salutation",
                    "text": "Dear hiring team,",
                    "evidence_fact_ids": [],
                },
                {
                    "claim_type": "intent",
                    "text": "I am applying for this role.",
                    "evidence_fact_ids": [],
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    validation = await client.post(f"/v1/documents/{response.json()['id']}/validate")
    assert validation.json()["valid"] is True
    assert validation.json()["export_allowed"] is False


async def test_claim_cannot_reverse_relationship_between_evidence_terms(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    fact_response = await client.post(
        f"/v1/profiles/{profile['id']}/facts",
        json={
            "source_id": source["id"],
            "category": "experience",
            "label": "Project leadership",
            "detail": "Noura mentored Sara",
        },
    )
    fact = fact_response.json()
    await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
    response = await client.post(
        "/v1/documents",
        json={
            "profile_id": profile["id"],
            "kind": "cv",
            "language": "en",
            "title": "CV",
            "claims": [
                {
                    "claim_type": "experience",
                    "text": "Sara mentored Noura",
                    "evidence_fact_ids": [fact["id"]],
                }
            ],
        },
    )
    assert response.status_code == 422


async def test_atomic_grounding_preserves_relations_negation_and_attribution(
    client: httpx.AsyncClient,
) -> None:
    profile, source = await create_profile_and_source(client)
    cases = [
        ("experience", "Worked with Google", "Worked for Google"),
        ("experience", "عملت مع جوجل", "عملت لدى جوجل"),
        ("skill", "No Python experience", "Python experience"),
        ("skill", "Sara uses Python", "I use Python"),
    ]
    for index, (category, evidence_text, claim_text) in enumerate(cases):
        fact = (
            await client.post(
                f"/v1/profiles/{profile['id']}/facts",
                json={
                    "source_id": source["id"],
                    "category": category,
                    "label": f"Evidence {index}",
                    "detail": evidence_text,
                },
            )
        ).json()
        await client.post(f"/v1/profiles/{profile['id']}/facts/{fact['id']}/confirm")
        response = await client.post(
            "/v1/documents",
            json={
                "profile_id": profile["id"],
                "kind": "cv",
                "language": "en",
                "title": f"CV {index}",
                "claims": [
                    {
                        "claim_type": category,
                        "text": claim_text,
                        "evidence_fact_ids": [fact["id"]],
                    }
                ],
            },
        )
        assert response.status_code == 422, (evidence_text, claim_text, response.text)
