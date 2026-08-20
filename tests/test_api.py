from datetime import date

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.schemas import (
    GSCPerformanceResponse,
    GSCPerformanceRow,
)


client = TestClient(app)


def test_health_reports_pending_gsc_without_credentials():
    get_settings.cache_clear()

    response = client.get("/health")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["integrations"]["gsc"] == "pending"
    assert body["integrations"]["ga4"] == "planned"


def test_shopify_endpoint_is_read_only_and_requires_configuration():
    response = client.get(
        "/v1/brands/nolix/shopify/products"
    )

    assert response.status_code == 503

    assert (
        "not configured"
        in response.json()["detail"].lower()
    )


def test_unknown_brand_is_rejected():
    response = client.get(
        "/v1/brands/other/shopify/products"
    )

    assert response.status_code == 422


def test_gsc_endpoint_requires_configuration():
    response = client.get(
        "/v1/brands/nolix/gsc/queries",
        params={
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        },
    )

    assert response.status_code == 503

    assert (
        "search console"
        in response.json()["detail"].lower()
    )


def test_gsc_rejects_reverse_date_range():
    response = client.get(
        "/v1/brands/nolix/gsc/pages",
        params={
            "start_date": "2026-08-10",
            "end_date": "2026-08-01",
        },
    )

    assert response.status_code == 422


def test_opportunities_are_derived_without_google_call(
    monkeypatch,
):
    from app import main

    async def fake_query(*args, **kwargs):
        return GSCPerformanceResponse(
            brand="nolix",
            site_url="sc-domain:nolix.ai",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            dimensions=[
                "query",
                "page",
            ],
            rows=[
                GSCPerformanceRow(
                    keys=[
                        "rodent detection device",
                        (
                            "https://nolix.ai/"
                            "products/example"
                        ),
                    ],
                    clicks=20,
                    impressions=3000,
                    ctr=0.0067,
                    position=8.4,
                ),
                GSCPerformanceRow(
                    keys=[
                        "brand query",
                        "https://nolix.ai/",
                    ],
                    clicks=500,
                    impressions=600,
                    ctr=0.83,
                    position=1.2,
                ),
            ],
        )

    monkeypatch.setattr(
        main,
        "_gsc_query",
        fake_query,
    )

    response = client.get(
        "/v1/brands/nolix/gsc/opportunities",
        params={
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body["opportunities"]) == 1

    assert (
        body["opportunities"][0]["opportunity"]
        == "striking_distance"
    )


def test_openapi_has_stable_gsc_operation_ids():
    schema = client.get(
        "/openapi.json"
    ).json()

    assert (
        schema["paths"][
            "/v1/brands/{brand}/gsc/queries"
        ]["get"]["operationId"]
        == "list_gsc_queries"
    )

    assert (
        schema["paths"][
            "/v1/brands/{brand}/gsc/opportunities"
        ]["get"]["operationId"]
        == "list_gsc_opportunities"
    )