import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import "./styles.css";
import { Button } from "./components/ui/button";
import { listOrganizations } from "./lib/api";

const queryClient = new QueryClient();

function App() {
  const organizations = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations, enabled: false });
  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">RG</span><span>Release Guardian</span></div>
        <nav aria-label="Primary navigation">
          <a className="active" href="#overview">Overview</a>
          <a href="#projects">Projects</a>
          <a href="#activity">Activity</a>
          <a href="#notifications">Notifications</a>
          <a href="#integrations">Integrations</a>
          <a href="#organization">Organization</a>
        </nav>
      </aside>
      <section className="content">
        <header className="topbar"><span>Overview</span><Button variant="ghost" type="button">Light / Dark</Button></header>
        <div className="page-heading"><div><p className="eyebrow">Release operations</p><h1>Keep every release moving.</h1><p className="muted">Monitor pipelines, understand failures, and notify the right people.</p></div><span className="status"><i /> Worker ready</span></div>
        <section className="cards" aria-label="Monitoring summary">
          <article><span className="label">Organizations</span><strong>{organizations.data?.length ?? 0}</strong><span className="muted">TanStack Query is ready for API state</span></article>
          <article><span className="label">Active incidents</span><strong>0</strong><span className="muted">No release blockers detected</span></article>
          <article><span className="label">Last poll</span><strong>—</strong><span className="muted">Waiting for configuration</span></article>
        </section>
        <section className="empty-state"><div className="empty-icon">✓</div><h2>Your release overview is ready</h2><p className="muted">Once a project is connected, pipeline health and grounded release analysis will appear here.</p><Button type="button">Connect a GitLab project</Button></section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>);
