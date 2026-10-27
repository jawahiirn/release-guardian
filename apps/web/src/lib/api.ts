import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export type Organization = { id: string; name: string; slug: string; role: string };
export type Integration = {
  id: string;
  organization_id: string;
  type: "gitlab" | "openai" | "discord" | "pushover";
  display_name: string;
  public_config: Record<string, unknown>;
  status: string;
  config_version: number;
  has_secret: boolean;
  secret_updated_at: string | null;
};
export type Project = {
  id: string;
  organization_id: string;
  gitlab_integration_id: string;
  external_project_id: string;
  name: string;
  branch_config: Record<string, string>;
  polling_interval_seconds: number;
  enabled: boolean;
  last_poll_at: string | null;
  last_success_at: string | null;
  next_poll_at: string | null;
  last_error: string | null;
};
export type ReleaseEvent = {
  id: string;
  organization_id: string;
  project_id: string;
  source: string;
  event_type: string;
  meaningful_state_version: string;
  occurred_at: string | null;
  observed_at: string;
  facts: Record<string, unknown>;
  analysis_status: "complete" | "fallback" | null;
  analysis_model: string | null;
  analysis: Record<string, unknown> | null;
  analysis_created_at: string | null;
};

let csrfToken: string | null = null;

function csrfHeaders() {
  return { "X-CSRF-Token": csrfToken ?? "" };
}

export async function login(email: string, password: string): Promise<void> {
  const response = await api.post<{ csrf_token: string }>("/api/v1/auth/login", { email, password });
  csrfToken = response.data.csrf_token;
}

export async function createOrganization(name: string): Promise<Organization> {
  const response = await api.post<Organization>(
    "/api/v1/organizations",
    { name },
    { headers: csrfHeaders() },
  );
  return response.data;
}

export async function listOrganizations(): Promise<Organization[]> {
  const response = await api.get<Organization[]>("/api/v1/organizations");
  return response.data;
}

export async function listIntegrations(organizationId: string): Promise<Integration[]> {
  const response = await api.get<Integration[]>(
    `/api/v1/organizations/${organizationId}/integrations`,
  );
  return response.data;
}

export async function createIntegration(
  organizationId: string,
  input: { type: Integration["type"]; display_name: string; public_config: Record<string, string> },
): Promise<Integration> {
  const response = await api.post<Integration>(
    `/api/v1/organizations/${organizationId}/integrations`,
    input,
    { headers: csrfHeaders() },
  );
  return response.data;
}

export async function rotateIntegrationSecret(
  integrationId: string,
  secret: string,
): Promise<Integration> {
  const response = await api.put<Integration>(
    `/api/v1/integrations/${integrationId}/secret`,
    { secret },
    { headers: csrfHeaders() },
  );
  return response.data;
}

export async function validateIntegration(integrationId: string): Promise<{ message: string }> {
  const response = await api.post<{ message: string }>(
    `/api/v1/integrations/${integrationId}/test`,
    {},
    { headers: csrfHeaders() },
  );
  return response.data;
}

export async function listProjects(organizationId: string): Promise<Project[]> {
  const response = await api.get<Project[]>(`/api/v1/organizations/${organizationId}/projects`);
  return response.data;
}

export async function createProject(
  organizationId: string,
  input: { gitlab_integration_id: string; external_project_id: string; name: string },
): Promise<Project> {
  const response = await api.post<Project>(
    `/api/v1/organizations/${organizationId}/projects`,
    input,
    { headers: csrfHeaders() },
  );
  return response.data;
}

export async function pollProject(projectId: string): Promise<{ project_id: string; status: string }> {
  const response = await api.post<{ project_id: string; status: string }>(
    `/api/v1/projects/${projectId}/poll-now`,
    {},
    { headers: csrfHeaders() },
  );
  return response.data;
}

export async function listEvents(organizationId: string): Promise<ReleaseEvent[]> {
  const response = await api.get<ReleaseEvent[]>(`/api/v1/organizations/${organizationId}/events`);
  return response.data;
}
