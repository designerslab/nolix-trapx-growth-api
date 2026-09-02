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

    openai_api_key: SecretStr | None = None
    openai_llm_visibility_model: str = "gpt-5.6-luna"

    nolix_llm_competitors: str | None = None
    trapx_llm_competitors: str | None = None

    llm_visibility_data_path: str | None = None

    nolix_shopify_store_domain: str | None = None
    nolix_shopify_access_token: SecretStr | None = None

    trapx_shopify_store_domain: str | None = None
    trapx_shopify_access_token: SecretStr | None = None
    nolix_ga4_property_id: str | None = None
    trapx_ga4_property_id: str | None = None
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

    def shopify_credentials(
    self,
    brand: str,
    ) -> tuple[str | None, str | None]:
        credentials = {
            "nolix": (
                self.nolix_shopify_store_domain,
                self.nolix_shopify_access_token,
            ),
            "trapx": (
                self.trapx_shopify_store_domain,
                self.trapx_shopify_access_token,
            ),
        }

        domain, token = credentials[brand]

        return (
            domain,
            token.get_secret_value()
            if token
            else None,
        )
    def ga4_property_id(self, brand: str) -> str | None:
        if brand == "nolix":
            return self.nolix_ga4_property_id

        if brand == "trapx":
            return self.trapx_ga4_property_id

        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
