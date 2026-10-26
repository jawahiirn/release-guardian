import logging
import os
import time
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

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
        time.sleep(10)


if __name__ == "__main__":
    main()
