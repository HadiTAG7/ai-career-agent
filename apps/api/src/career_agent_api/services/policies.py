from datetime import date
from typing import Literal
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from career_agent_api.models.domain import SourcePolicy
from career_agent_api.models.enums import IntakeMethod

DEFAULT_POLICIES: dict[str, dict[str, object]] = {
    "manual": {
        "display_name": "User-entered job",
        "permission_basis": "Description and URL supplied directly by the user",
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "permission_basis": "User-supplied text/URL only; no scraping or account automation",
    },
    "indeed": {
        "display_name": "Indeed",
        "permission_basis": "User-supplied text/URL only; no automated agents without permission",
    },
    "bayt": {
        "display_name": "Bayt",
        "permission_basis": "User-supplied text/URL only; no robot access",
    },
    "gulftalent": {
        "display_name": "GulfTalent",
        "permission_basis": "User-supplied text/URL only; no robot access",
    },
}

HOST_SOURCE_MAP = {
    "linkedin.com": "linkedin",
    "indeed.com": "indeed",
    "bayt.com": "bayt",
    "gulftalent.com": "gulftalent",
}


def source_key_for_url(source_url: str | None, requested_key: str) -> str:
    if not source_url:
        return requested_key
    host = (urlparse(source_url).hostname or "").lower()
    for domain, source_key in HOST_SOURCE_MAP.items():
        if host == domain or host.endswith(f".{domain}"):
            return source_key
    return requested_key


async def seed_source_policies(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(SourcePolicy.source_key))).all())
    for key, policy in DEFAULT_POLICIES.items():
        if key in existing:
            continue
        # Another worker starting at the same time may insert the same key; the
        # unique constraint decides, and losing the race is not an error.
        try:
            async with session.begin_nested():
                session.add(
                    SourcePolicy(
                        source_key=key,
                        display_name=str(policy["display_name"]),
                        intake_method=IntakeMethod.MANUAL,
                        permission_basis=str(policy["permission_basis"]),
                        terms_reviewed_at=date(2026, 8, 6),
                        can_search_automatically=False,
                        can_fetch_details=False,
                        can_apply_automatically=False,
                    )
                )
        except IntegrityError:
            continue
    await session.flush()


async def get_or_create_deny_by_default_policy(
    session: AsyncSession, source_key: str
) -> SourcePolicy:
    policy = await session.scalar(select(SourcePolicy).where(SourcePolicy.source_key == source_key))
    if policy:
        return policy
    policy = SourcePolicy(
        source_key=source_key,
        display_name=source_key.replace("-", " ").title(),
        intake_method=IntakeMethod.MANUAL,
        permission_basis="Unreviewed source: user-supplied content only",
        can_search_automatically=False,
        can_fetch_details=False,
        can_apply_automatically=False,
    )
    session.add(policy)
    await session.flush()
    return policy


def require_automatic_permission(
    policy: SourcePolicy, action: Literal["search", "fetch", "apply"]
) -> None:
    allowed = {
        "search": policy.can_search_automatically,
        "fetch": policy.can_fetch_details,
        "apply": policy.can_apply_automatically,
    }[action]
    if not policy.active or not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Automatic {action} is not permitted for source '{policy.source_key}'",
        )
