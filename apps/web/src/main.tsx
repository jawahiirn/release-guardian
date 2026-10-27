import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import "./styles.css";
import { Button } from "./components/ui/button";
import {
  createIntegration,
  createOrganization,
  Integration,
  createProject,
  listIntegrations,
  listEvents,
  listOrganizations,
  listProjects,
  login,
  pollProject,
  Project,
  apiErrorMessage,
  rotateIntegrationSecret,
  validateIntegration,
} from "./lib/api";

const queryClient = new QueryClient();

function LoginView({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: onLogin,
  });

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="brand"><span className="brand-mark">RG</span><span>Release Guardian</span></div>
        <p className="eyebrow">Advisory release operations</p>
        <h1>Sign in to your instance.</h1>
        <p className="muted">Use the administrator or invited account created for this installation.</p>
        <form onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }} className="form-stack">
          <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {mutation.isError && <p className="error">Sign in failed. Check the credentials and try again.</p>}
          <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Signing in…" : "Sign in"}</Button>
        </form>
      </section>
    </main>
  );
}

function IntegrationCard({ integration, organizationId }: { integration: Integration; organizationId: string }) {
  const queryClient = useQueryClient();
  const [secret, setSecret] = useState("");
  const rotate = useMutation({
    mutationFn: () => rotateIntegrationSecret(integration.id, secret),
    onSuccess: () => { setSecret(""); queryClient.invalidateQueries({ queryKey: ["integrations", organizationId] }); },
  });
  const validate = useMutation({
    mutationFn: () => validateIntegration(integration.id),
  });

  return (
    <article className="integration-card">
      <div className="integration-heading"><div><span className="label">{integration.type}</span><h3>{integration.display_name}</h3></div><span className={`pill ${integration.has_secret ? "pill-good" : "pill-muted"}`}>{integration.has_secret ? "Configured" : "Needs secret"}</span></div>
      <p className="muted">Configuration version {integration.config_version}. Secrets are write-only.</p>
      <div className="button-row"><Button variant="ghost" type="button" onClick={() => validate.mutate()} disabled={!integration.has_secret || validate.isPending}>{validate.isPending ? "Checking…" : "Validate configuration"}</Button></div>
      {validate.data && <p className="success">{validate.data.message}</p>}
      {validate.isError && <p className="error">Validation failed. Check the provider secret format.</p>}
      <form onSubmit={(event) => { event.preventDefault(); rotate.mutate(); }} className="secret-form">
        <input aria-label={`Replace ${integration.display_name} secret`} type="password" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="Replace provider secret" required />
        <Button type="submit" disabled={rotate.isPending}>{rotate.isPending ? "Saving…" : "Replace secret"}</Button>
      </form>
      {rotate.isError && <p className="error">Secret replacement failed. Check the value and permissions.</p>}
    </article>
  );
}

function ProjectCard({ project, organizationId }: { project: Project; organizationId: string }) {
  const queryClient = useQueryClient();
  const poll = useMutation({
    mutationFn: () => pollProject(project.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", organizationId] });
      queryClient.invalidateQueries({ queryKey: ["events", organizationId] });
    },
  });
  return (
    <article className="project-card">
      <div className="integration-heading"><div><span className="label">GitLab project</span><h3>{project.name}</h3></div><span className={`pill ${project.enabled ? "pill-good" : "pill-muted"}`}>{project.enabled ? "Enabled" : "Disabled"}</span></div>
      <p className="muted"><span className="code">{project.external_project_id}</span> · polls every {project.polling_interval_seconds}s</p>
      <div className="project-meta"><span>Last success: {project.last_success_at ? new Date(project.last_success_at).toLocaleString() : "Never"}</span><span>Next poll: {project.next_poll_at ? new Date(project.next_poll_at).toLocaleString() : "Pending"}</span></div>
      {project.last_error && <p className="error">{project.last_error}</p>}
      <Button variant="ghost" type="button" onClick={() => poll.mutate()} disabled={poll.isPending || !project.enabled}>{poll.isPending ? "Scheduling…" : "Poll now"}</Button>
    </article>
  );
}

function AuthenticatedApp() {
  const queryClient = useQueryClient();
  const organizations = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const [organizationId, setOrganizationId] = useState<string>();
  const selectedOrganizationId = organizationId ?? organizations.data?.[0]?.id;
  const integrations = useQuery({
    queryKey: ["integrations", selectedOrganizationId],
    queryFn: () => listIntegrations(selectedOrganizationId!),
    enabled: Boolean(selectedOrganizationId),
  });
  const projects = useQuery({
    queryKey: ["projects", selectedOrganizationId],
    queryFn: () => listProjects(selectedOrganizationId!),
    enabled: Boolean(selectedOrganizationId),
  });
  const events = useQuery({
    queryKey: ["events", selectedOrganizationId],
    queryFn: () => listEvents(selectedOrganizationId!),
    enabled: Boolean(selectedOrganizationId),
  });
  const gitlabIntegrations = integrations.data?.filter((integration) => integration.type === "gitlab") ?? [];
  const [organizationName, setOrganizationName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [type, setType] = useState<Integration["type"]>("gitlab");
  const [baseUrl, setBaseUrl] = useState("https://gitlab.com");
  const [model, setModel] = useState("gpt-5-mini");
  const [projectName, setProjectName] = useState("");
  const [externalProjectId, setExternalProjectId] = useState("");
  const [gitlabIntegrationId, setGitlabIntegrationId] = useState("");
  const createOrg = useMutation({
    mutationFn: () => createOrganization(organizationName),
    onSuccess: () => { setOrganizationName(""); queryClient.invalidateQueries({ queryKey: ["organizations"] }); },
  });
  const create = useMutation({
    mutationFn: () => createIntegration(selectedOrganizationId!, { type, display_name: displayName, public_config: type === "gitlab" ? { base_url: baseUrl } : type === "openai" ? { model } : {} }),
    onSuccess: () => { setDisplayName(""); queryClient.invalidateQueries({ queryKey: ["integrations", selectedOrganizationId] }); },
  });
  const createMonitoredProject = useMutation({
    mutationFn: () => createProject(selectedOrganizationId!, {
      gitlab_integration_id: gitlabIntegrationId || gitlabIntegrations[0]?.id || "",
      external_project_id: externalProjectId,
      name: projectName,
    }),
    onSuccess: () => {
      setProjectName("");
      setExternalProjectId("");
      queryClient.invalidateQueries({ queryKey: ["projects", selectedOrganizationId] });
    },
  });

  return (
    <main className="shell">
      <aside className="sidebar"><div className="brand"><span className="brand-mark">RG</span><span>Release Guardian</span></div><nav aria-label="Primary navigation"><a href="#overview">Overview</a><a className="active" href="#integrations">Integrations</a><a href="#projects">Projects</a><a href="#activity">Activity</a></nav></aside>
      <section className="content">
        <header className="topbar"><span>Integrations</span><span className="status"><i /> Session active</span></header>
        <div className="page-heading"><div><p className="eyebrow">Instance configuration</p><h1>Connect your release tools.</h1><p className="muted">Store provider metadata and rotate credentials without restarting the services.</p></div></div>
        <section className="workspace-grid">
          <div className="panel"><span className="label">Organization</span>{organizations.isLoading ? <p className="muted">Loading organizations…</p> : organizations.data?.length ? <select value={selectedOrganizationId} onChange={(event) => setOrganizationId(event.target.value)}>{organizations.data.map((organization) => <option key={organization.id} value={organization.id}>{organization.name} · {organization.role}</option>)}</select> : <p className="muted">Create your first organization to begin.</p>}<form onSubmit={(event) => { event.preventDefault(); createOrg.mutate(); }} className="inline-form"><input value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} placeholder="New organization name" required /><Button type="submit" disabled={createOrg.isPending}>{createOrg.isPending ? "Creating…" : "Create"}</Button></form></div>
          <div className="panel"><span className="label">Add integration</span><form onSubmit={(event) => { event.preventDefault(); create.mutate(); }} className="form-stack"><label>Provider<select value={type} onChange={(event) => setType(event.target.value as Integration["type"])}><option value="gitlab">GitLab</option><option value="openai">OpenAI</option><option value="discord">Discord</option><option value="pushover">Pushover</option></select></label><label>Display name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Staging GitLab" required /></label>{type === "gitlab" && <label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required /></label>}{type === "openai" && <label>Model<input value={model} onChange={(event) => setModel(event.target.value)} required /></label>}<Button type="submit" disabled={!selectedOrganizationId || create.isPending}>{create.isPending ? "Adding…" : "Add integration"}</Button></form></div>
        </section>
        <section className="section-heading"><div><span className="label">Configured providers</span><h2>Integration inventory</h2></div>{integrations.isFetching && <span className="muted">Refreshing…</span>}</section>
        {integrations.isError && <p className="error">Unable to load integrations. Confirm the selected organization and session.</p>}
        <section className="integration-list">{integrations.data?.length ? integrations.data.map((integration) => <IntegrationCard key={integration.id} integration={integration} organizationId={selectedOrganizationId!} />) : <div className="empty-state"><div className="empty-icon">+</div><h2>No integrations yet</h2><p className="muted">Add a provider above. Live provider requests are not made by the local validation action.</p></div>}</section>
        <section id="projects" className="section-heading"><div><span className="label">GitLab monitoring</span><h2>Projects</h2></div>{projects.isFetching && <span className="muted">Refreshing…</span>}</section>
        <section className="workspace-grid">
          <div className="panel"><span className="label">Register project</span>{gitlabIntegrations.length ? <form onSubmit={(event) => { event.preventDefault(); createMonitoredProject.mutate(); }} className="form-stack"><label>GitLab integration<select value={gitlabIntegrationId || gitlabIntegrations[0].id} onChange={(event) => setGitlabIntegrationId(event.target.value)}>{gitlabIntegrations.map((integration) => <option key={integration.id} value={integration.id}>{integration.display_name}</option>)}</select></label><label>Project ID or path<input value={externalProjectId} onChange={(event) => setExternalProjectId(event.target.value)} placeholder="group/project or 123456" required /></label><label>Display name<input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Staging release project" required /></label><p className="muted">Polling defaults to 300 seconds. Branches default to Develop, Stage, and Main.</p><Button type="submit" disabled={createMonitoredProject.isPending}>{createMonitoredProject.isPending ? "Registering…" : "Register project"}</Button></form> : <p className="muted">Add a GitLab integration first, then register a project here.</p>}{createMonitoredProject.isError && <p className="error">{apiErrorMessage(createMonitoredProject.error, "Project registration failed. Check the GitLab integration and permissions.")}</p>}</div>
          <div className="panel"><span className="label">Observed events</span>{events.data?.length ? <div className="event-list">{events.data.map((event) => <div className="event-row" key={event.id}><div><strong>{event.event_type}</strong><span className="muted">{String(event.facts.ref ?? "unknown ref")} · {String(event.facts.sha ?? "unknown SHA")}</span>{event.analysis && <span className="muted">{String(event.analysis.summary ?? "Analysis available")}</span>}</div><span className={`pill ${event.analysis_status === "complete" ? "pill-good" : "pill-muted"}`}>{event.analysis_status === "complete" ? "Analyzed" : event.analysis_status === "fallback" ? "Factual fallback" : "Observed"}</span></div>)}</div> : <p className="muted">No pipeline events observed yet.</p>}</div>
        </section>
        {projects.isError && <p className="error">Unable to load monitored projects for this organization.</p>}
        <section className="project-list">{projects.data?.length ? projects.data.map((project) => <ProjectCard key={project.id} project={project} organizationId={selectedOrganizationId!} />) : <div className="empty-state"><div className="empty-icon">⌁</div><h2>No monitored projects</h2><p className="muted">Register a GitLab project above to start tracking pipeline state.</p></div>}</section>
      </section>
    </main>
  );
}

function App() {
  const [authenticated, setAuthenticated] = useState(false);
  return authenticated ? <AuthenticatedApp /> : <LoginView onLogin={() => setAuthenticated(true)} />;
}

createRoot(document.getElementById("root")!).render(<StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>);
