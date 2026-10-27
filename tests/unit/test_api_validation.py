from fastapi.testclient import TestClient

from apps.api.app.main import app, require_csrf


def test_invalid_integration_id_is_rejected_before_database_lookup() -> None:
    app.dependency_overrides[require_csrf] = lambda: {"user_id": "test-user"}
    try:
        response = TestClient(app).post("/api/v1/integrations/not-a-uuid/test")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
