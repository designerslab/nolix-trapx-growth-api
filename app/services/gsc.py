import json
from datetime import date
from urllib.parse import quote

import httpx

from app.config import Settings
from app.schemas import GSCPerformanceResponse, GSCPerformanceRow

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GSC_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"


class GSCNotConfiguredError(Exception):
    pass


class GSCUpstreamError(Exception):
    pass


class GSCClient:
    """Read-only Google Search Console Search Analytics client."""

    def __init__(self, settings: Settings, brand: str) -> None:
        self.brand = brand
        self.site_url = settings.gsc_site_url(brand)
        credential_secret = settings.google_service_account_json

        if not self.site_url or not credential_secret:
            raise GSCNotConfiguredError(
                f"Google Search Console is not configured for {brand}."
            )

        try:
            from google.oauth2 import service_account

            credential_info = json.loads(
                credential_secret.get_secret_value()
            )

            self.credentials = (
                service_account.Credentials.from_service_account_info(
                    credential_info,
                    scopes=[GSC_SCOPE],
                )
            )

        except ImportError as error:
            raise GSCNotConfiguredError(
                "google-auth is not installed."
            ) from error

        except (ValueError, TypeError, KeyError) as error:
            raise GSCNotConfiguredError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is invalid."
            ) from error

    def _access_token(self) -> str:
        try:
            from google.auth.transport.requests import Request

            if not self.credentials.valid or not self.credentials.token:
                self.credentials.refresh(Request())

        except Exception as error:
            raise GSCUpstreamError(
                "Unable to authenticate to Google Search Console."
            ) from error

        if not self.credentials.token:
            raise GSCUpstreamError(
                "Google Search Console returned no access token."
            )

        return self.credentials.token

    async def query_performance(
        self,
        start_date: date,
        end_date: date,
        dimensions: list[str],
        row_limit: int = 1000,
        start_row: int = 0,
        country: str | None = None,
        device: str | None = None,
    ) -> GSCPerformanceResponse:

        if end_date < start_date:
            raise ValueError(
                "end_date must be on or after start_date"
            )

        dimension_filter_groups = []
        filters = []

        if country:
            filters.append(
                {
                    "dimension": "country",
                    "operator": "equals",
                    "expression": country.lower(),
                }
            )

        if device:
            filters.append(
                {
                    "dimension": "device",
                    "operator": "equals",
                    "expression": device.upper(),
                }
            )

        if filters:
            dimension_filter_groups.append(
                {
                    "groupType": "and",
                    "filters": filters,
                }
            )

        body: dict[str, object] = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "startRow": start_row,
            "dataState": "final",
        }

        if dimension_filter_groups:
            body["dimensionFilterGroups"] = dimension_filter_groups

        encoded_site = quote(self.site_url, safe="")

        url = (
            f"{GSC_API_BASE}/sites/"
            f"{encoded_site}/searchAnalytics/query"
        )

        headers = {
            "Authorization": f"Bearer {self._access_token()}"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=body,
                )

                response.raise_for_status()

        except httpx.HTTPStatusError as error:
            detail = error.response.text[:500]

            raise GSCUpstreamError(
                f"GSC query failed with "
                f"{error.response.status_code}: {detail}"
            ) from error

        except httpx.HTTPError as error:
            raise GSCUpstreamError(
                "Unable to read Google Search Console data."
            ) from error

        payload = response.json()

        rows = [
            GSCPerformanceRow(
                keys=[
                    str(key)
                    for key in item.get("keys", [])
                ],
                clicks=float(item.get("clicks", 0)),
                impressions=float(
                    item.get("impressions", 0)
                ),
                ctr=float(item.get("ctr", 0)),
                position=float(item.get("position", 0)),
            )
            for item in payload.get("rows", [])
        ]

        return GSCPerformanceResponse(
            brand=self.brand,
            site_url=self.site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            rows=rows,
        )