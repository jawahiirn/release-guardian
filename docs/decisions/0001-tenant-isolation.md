# ADR 0001: Organization is the security boundary

Status: accepted

Release Guardian uses independent self-hosted instances. Within an instance, organizations are the tenant boundary. Organization-scoped records carry `organization_id`, and every API, worker, job, integration, report, and notification query must verify membership and scope. Teams are grouping only in the MVP and do not provide independent isolation.
