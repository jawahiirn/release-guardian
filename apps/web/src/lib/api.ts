import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

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
