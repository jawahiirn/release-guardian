import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

export type Organization = { id: string; name: string; slug: string; role: string };

export async function listOrganizations(): Promise<Organization[]> {
  const response = await api.get<Organization[]>("/api/v1/organizations");
  return response.data;
}
