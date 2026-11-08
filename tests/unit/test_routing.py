from typing import Any

from apps.worker.app.delivery import enqueue_event_notifications


class FakeResult:
    def all(self) -> list[tuple[str]]:
        return [("outbox-id",)]


class FakeConnection:
    def __init__(self) -> None:
        self.statement = ""
        self.parameters: dict[str, Any] = {}

    def execute(self, statement: Any, parameters: dict[str, Any]) -> FakeResult:
        self.statement = str(statement)
        self.parameters = parameters
        return FakeResult()


def test_notification_enqueue_applies_destination_routing_rules() -> None:
    connection = FakeConnection()

    inserted = enqueue_event_notifications(connection, "event-id", "organization-id")

    assert inserted == 1
    assert connection.parameters == {
        "event_id": "event-id",
        "organization_id": "organization-id",
    }
    assert "FROM routing_rules" in connection.statement
    assert "rr.project_id IS NULL OR rr.project_id = e.project_id" in connection.statement
    assert "rr.event_types_json @> jsonb_build_array(e.event_type)" in connection.statement
    assert "NOT EXISTS" in connection.statement
