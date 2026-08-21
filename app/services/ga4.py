import json
from datetime import date

from app.config import Settings


GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


class GA4NotConfiguredError(Exception):
    pass


class GA4UpstreamError(Exception):
    pass


class GA4Client:
    """Read-only Google Analytics 4 Data API client."""

    def __init__(
        self,
        settings: Settings,
        brand: str,
    ) -> None:
        self.brand = brand
        self.property_id = settings.ga4_property_id(
            brand
        )

        credential_secret = (
            settings.google_service_account_json
        )

        if (
            not self.property_id
            or not credential_secret
        ):
            raise GA4NotConfiguredError(
                f"GA4 is not configured for {brand}."
            )

        try:
            from google.oauth2 import service_account
            from google.analytics.data_v1beta import (
                BetaAnalyticsDataClient,
            )

            credential_info = json.loads(
                credential_secret.get_secret_value()
            )

            credentials = (
                service_account.Credentials
                .from_service_account_info(
                    credential_info,
                    scopes=[GA4_SCOPE],
                )
            )

            self.client = BetaAnalyticsDataClient(
                credentials=credentials
            )

        except ImportError as error:
            raise GA4NotConfiguredError(
                "google-analytics-data is not installed."
            ) from error

        except (
            ValueError,
            TypeError,
            KeyError,
        ) as error:
            raise GA4NotConfiguredError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is invalid."
            ) from error

        except Exception as error:
            raise GA4UpstreamError(
                f"Unable to initialize GA4: "
                f"{type(error).__name__}: {error}"
            ) from error

    def _property_name(self) -> str:
        return f"properties/{self.property_id}"

    def run_report(
        self,
        start_date: date,
        end_date: date,
        dimensions: list[str],
        metrics: list[str],
        limit: int = 1000,
    ):
        try:
            from google.analytics.data_v1beta.types import (
                DateRange,
                Dimension,
                Metric,
                RunReportRequest,
            )

            request = RunReportRequest(
                property=self._property_name(),
                date_ranges=[
                    DateRange(
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                    )
                ],
                dimensions=[
                    Dimension(name=name)
                    for name in dimensions
                ],
                metrics=[
                    Metric(name=name)
                    for name in metrics
                ],
                limit=limit,
            )

            return self.client.run_report(
                request=request
            )

        except Exception as error:
            print(
                "GA4 ERROR:",
                type(error).__name__,
                str(error),
            )

            raise GA4UpstreamError(
                f"GA4 query failed: "
                f"{type(error).__name__}: {error}"
            ) from error