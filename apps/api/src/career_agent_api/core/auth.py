import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from career_agent_api.core.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str


@lru_cache(maxsize=8)
def _jwk_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True)


def _validate_clerk_token(token: str, settings: Settings) -> str:
    if not settings.clerk_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth unavailable"
        )
    try:
        signing_key = _jwk_client(settings.clerk_jwks_url).get_signing_key_from_jwt(token)
        options = {"verify_aud": bool(settings.clerk_audience)}
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.clerk_audience,
            issuer=settings.clerk_issuer,
            options=options,
        )
    except (jwt.PyJWTError, PyJWKClientError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has no subject")
    authorized_party = payload.get("azp")
    if settings.clerk_authorized_parties and (
        not isinstance(authorized_party, str)
        or authorized_party.rstrip("/") not in settings.clerk_authorized_parties
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has an unauthorized party",
        )
    return subject


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> AuthenticatedUser:
    # A configured Clerk project always wins, including in development.
    if settings.clerk_jwks_url:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token required",
            )
        subject = await asyncio.to_thread(_validate_clerk_token, credentials.credentials, settings)
        return AuthenticatedUser(id=subject)
    if credentials:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth unavailable",
        )
    if settings.environment in {"development", "test"}:
        return AuthenticatedUser(id=x_user_id or "demo-user")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
