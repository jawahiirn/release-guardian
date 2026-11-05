from fastapi.testclient import TestClient

from apps.api.app.main import app


def test_liveness() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_operational_health_requires_authentication() -> None:
    response = TestClient(app).get("/api/v1/admin/health")
    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}
