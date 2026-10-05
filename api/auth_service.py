from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
import jwt


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    session_id: UUID
    email: str
    display_name: str
    employee_role: str
    access_token: str


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    display_name: str


class AuthenticationError(ValueError):
    pass


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthenticatedUser: ...


class AuthClient(Protocol):
    async def login(self, email: str, password: str) -> AuthTokens: ...
    async def refresh(self, refresh_token: str) -> AuthTokens: ...
    async def logout(self, access_token: str) -> None: ...
    async def close(self) -> None: ...


def _display_name(user: dict) -> str:
    metadata = user.get("user_metadata") or {}
    email = user.get("email") or "Employee"
    return metadata.get("display_name") or metadata.get("full_name") or email.split("@", 1)[0]


class SupabaseAuthClient:
    def __init__(self, url: str, publishable_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = url.rstrip("/")
        self._key = publishable_key
        self._client = client or httpx.AsyncClient(timeout=15)
        self._owns_client = client is None

    @classmethod
    def from_env(cls) -> SupabaseAuthClient:
        return cls(os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"])

    @property
    def _headers(self) -> dict[str, str]:
        return {"apikey": self._key, "Content-Type": "application/json"}

    def _tokens(self, data: dict) -> AuthTokens:
        user = data.get("user") or {}
        return AuthTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=int(data["expires_in"]),
            display_name=_display_name(user),
        )

    async def login(self, email: str, password: str) -> AuthTokens:
        response = await self._client.post(
            f"{self._url}/auth/v1/token?grant_type=password",
            headers=self._headers,
            json={"email": email, "password": password},
        )
        if response.status_code >= 400:
            raise AuthenticationError("Invalid email or password.")
        return self._tokens(response.json())

    async def refresh(self, refresh_token: str) -> AuthTokens:
        response = await self._client.post(
            f"{self._url}/auth/v1/token?grant_type=refresh_token",
            headers=self._headers,
            json={"refresh_token": refresh_token},
        )
        if response.status_code >= 400:
            raise AuthenticationError("Session is invalid or has expired.")
        return self._tokens(response.json())

    async def logout(self, access_token: str) -> None:
        response = await self._client.post(
            f"{self._url}/auth/v1/logout",
            headers={**self._headers, "Authorization": f"Bearer {access_token}"},
        )
        if response.status_code not in {200, 204, 401, 403}:
            response.raise_for_status()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SupabaseTokenVerifier:
    def __init__(self, url: str) -> None:
        self._issuer = f"{url.rstrip('/')}/auth/v1"
        self._jwks = jwt.PyJWKClient(f"{self._issuer}/.well-known/jwks.json", cache_keys=True)

    @classmethod
    def from_env(cls) -> SupabaseTokenVerifier:
        return cls(os.environ["SUPABASE_URL"])

    async def verify(self, token: str) -> AuthenticatedUser:
        try:
            signing_key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
                issuer=self._issuer,
                options={"require": ["exp", "sub", "session_id"]},
            )
            user_id = UUID(claims["sub"])
            session_id = UUID(claims["session_id"])
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise AuthenticationError("Session is invalid or has expired.") from exc

        email = claims.get("email") or ""
        return AuthenticatedUser(
            id=user_id,
            session_id=session_id,
            email=email,
            display_name=_display_name({"email": email, "user_metadata": claims.get("user_metadata")}),
            employee_role="employee",
            access_token=token,
        )
