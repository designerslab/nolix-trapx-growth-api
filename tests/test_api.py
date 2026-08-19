from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_planned_integrations() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["integrations"]["gsc"] == "planned"
    assert response.json()["integrations"]["ga4"] == "planned"


def test_shopify_endpoint_is_read_only_and_requires_configuration() -> None:
    response = client.get("/v1/brands/nolix/shopify/products")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_unknown_brand_is_rejected() -> None:
    response = client.get("/v1/brands/other/shopify/products")

    assert response.status_code == 422
