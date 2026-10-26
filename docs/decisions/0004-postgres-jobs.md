# ADR 0004: PostgreSQL-backed jobs and transactional outbox

Status: accepted

PostgreSQL is the only supported database in development, testing, and production. Critical jobs and notifications use database state with leases and retries; no Redis, RabbitMQ, or separate orchestration service is introduced for the MVP. The notification outbox is durable and at-least-once. Exactly-once delivery to external providers is not guaranteed unless a provider supplies idempotency support.
