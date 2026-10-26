# ADR 0003: Encrypt integration credentials at rest

Status: accepted

Provider secrets are write-only through the API and stored as authenticated-encrypted blobs using an operator-supplied master key. Operations resolve the active credential version at execution time, allowing live rotation without service restart. Logs, audit metadata, queued jobs, and responses never contain plaintext secrets.
