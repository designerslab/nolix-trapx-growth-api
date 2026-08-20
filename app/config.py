from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    growth_api_public_url: str = "http://localhost:8000"
    growth_api_key: SecretStr | None = None

    nolix_shopify_store_domain: str | None = None
    nolix_shopify_access_token: SecretStr | None = None

    trapx_shopify_store_domain: str | None = None
    trapx_shopify_access_token: SecretStr | None = None

    google_service_account_json: SecretStr | None = None

    nolix_gsc_site_url: str | None = None
    trapx_gsc_site_url: str | None = None
    def gsc_site_url(
        self,
        brand: str,
    ) -> str | None:
        return {
            "nolix": self.nolix_gsc_site_url,
            "trapx": self.trapx_gsc_site_url,
        }[brand]

    def shopify_credentials(self, brand: str) -> tuple[str | None, str | None]:
        credentials = {
            "nolix": (self.nolix_shopify_store_domain, self.nolix_shopify_access_token),
            "trapx": (self.trapx_shopify_store_domain, self.trapx_shopify_access_token),
        }
        return credentials[brand]


@lru_cache
def get_settings() -> Settings:
    return Settings()
