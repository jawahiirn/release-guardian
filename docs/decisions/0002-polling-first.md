# ADR 0002: Poll GitLab before adding webhooks

Status: accepted

The MVP polls GitLab because a self-hosted laptop or VPS may have no public endpoint. Each project owns persisted polling state and a lease. Polling defaults to 300 seconds, uses bounded jitter and retry/backoff, and deduplicates overlapping observations. A webhook adapter can be added later behind the same event normalization boundary.
