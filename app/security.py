from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings


api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


def require_api_key(
    api_key: str | None = Security(api_key_header),
) -> None:
    """
    Require an API key in deployed environments.

    If GROWTH_API_KEY is not configured,
    local development remains accessible.
    """

    secret = get_settings().growth_api_key

    expected_key = (
        secret.get_secret_value()
        if secret
        else None
    )

    if (
        expected_key is not None
        and api_key != expected_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )