import logging
import os
import time
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

from apps.worker.app.analyzer import analyze_pending_events
from apps.worker.app.delivery import deliver_due_notifications
from apps.worker.app.poller import poll_due_projects

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://release_guardian:change-me-in-local-env@localhost:5432/release_guardian",
)
WORKER_NAME = os.getenv("WORKER_NAME", "release-guardian-worker")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def record_heartbeat() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO worker_heartbeats (worker_name, last_seen_at)
                VALUES (:worker_name, :last_seen_at)
                ON CONFLICT (worker_name) DO UPDATE
                SET last_seen_at = EXCLUDED.last_seen_at
                """
            ),
            {"worker_name": WORKER_NAME, "last_seen_at": datetime.now(UTC)},
        )


def main() -> None:
    logger.info("worker started")
    while True:
        record_heartbeat()
        try:
            created = poll_due_projects(engine, WORKER_NAME)
            if created:
                logger.info("persisted %s new monitoring events", created)
            delivered = deliver_due_notifications(engine, WORKER_NAME)
            if delivered:
                logger.info("delivered %s notifications", delivered)
            analyzed = analyze_pending_events(engine, limit=1)
            if analyzed:
                logger.info("persisted %s event analyses", analyzed)
        except Exception:  # noqa: BLE001 - keep the heartbeat loop alive after a cycle failure
            logger.exception("monitoring cycle failed")
        time.sleep(10)


if __name__ == "__main__":
    main()
