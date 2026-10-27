from fastapi.testclient import TestClient

from apps.api.app.main import app


def test_invalid_integration_id_is_rejected_before_database_lookup() -> None:
    response = TestClient(app).post("/api/v1/integrations/not-a-uuid/test")
    assert response.status_code == 422
