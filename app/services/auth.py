"""API-key authentication used by write endpoints."""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="ApiKeyAuth",
    auto_error=False,
    description="API key sent in the `X-API-Key` header. Required for write operations.",
)


def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    expected = os.environ.get("PRODUCT_API_KEY", "change-me")
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid API key")
