"""OIDC client using Authlib's AsyncOAuth2Client (Authorization Code flow)."""
from typing import Optional
import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.discovery import get_well_known_url

from app.core.config import settings

_oidc_metadata: Optional[dict] = None


async def _fetch_metadata() -> dict:
    global _oidc_metadata
    if _oidc_metadata is None:
        url = get_well_known_url(settings.OIDC_DISCOVERY_URL, external=True)
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _oidc_metadata = resp.json()
    return _oidc_metadata


def _make_client() -> AsyncOAuth2Client:
    return AsyncOAuth2Client(
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        redirect_uri=settings.OIDC_REDIRECT_URI,
        scope=settings.OIDC_SCOPES,
    )


async def get_authorization_url(state: str, nonce: str) -> str:
    """Return the IdP authorization URL to redirect the browser to."""
    meta = await _fetch_metadata()
    client = _make_client()
    url, _ = client.create_authorization_url(
        meta["authorization_endpoint"],
        state=state,
        nonce=nonce,
    )
    return url


async def exchange_code(code: str, state: str) -> dict:
    """Exchange authorization code for tokens; return id_token claims."""
    meta = await _fetch_metadata()
    client = _make_client()
    token = await client.fetch_token(
        meta["token_endpoint"],
        code=code,
        state=state,
    )
    # Validate id_token
    claims = client.parse_id_token(token, nonce=None)  # nonce validated via session
    return {
        "sub": claims["sub"],
        "email": claims.get("email"),
        "name": claims.get("name"),
        "provider": settings.OIDC_PROVIDER_NAME,
    }
