from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-side configuration. Values are loaded only from environment/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    growth_api_public_url: str = "http://localhost:8000"
    growth_api_key: str | None = None

    nolix_shopify_store_domain: str | None = None
    nolix_shopify_access_token: str | None = None
    trapx_shopify_store_domain: str | None = None
    trapx_shopify_access_token: str | None = None

    def shopify_credentials(self, brand: str) -> tuple[str | None, str | None]:
        credentials = {
            "nolix": (self.nolix_shopify_store_domain, self.nolix_shopify_access_token),
            "trapx": (self.trapx_shopify_store_domain, self.trapx_shopify_access_token),
        }
        return credentials[brand]


@lru_cache
def get_settings() -> Settings:
    return Settings()
