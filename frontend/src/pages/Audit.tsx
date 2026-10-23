import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { AuditEntry } from "../types";
import { PageHeader } from "../components/PageHeader";

const ACTOR_LABEL: Record<string, string> = { user: "Person", model: "AI model", system: "System" };

function describe(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function AuditPage() {
  const audit = useQuery<{ audit: AuditEntry[] }>({ queryKey: ["audit", "page"], queryFn: () => get("/audit?limit=80") });
  const [actor, setActor] = useState("all");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const entries = audit.data?.audit || [];

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => (actor === "all" || e.actor_type === actor)
      && (!q || `${e.action} ${e.actor_name} ${e.entity_type} ${e.entity_id}`.toLowerCase().includes(q)));
  }, [entries, actor, query]);

  return (
    <div className="page">
      <PageHeader
        title="Audit log"
        description="A read-only record of every change, approval, dismissal and AI draft. Entries cannot be edited."
        meta={audit.data ? <span>{entries.length} most recent entries</span> : null}
      />

      <section className="panel">
        <div className="toolbar">
          <input className="input toolbar-search" placeholder="Search action, person or record" aria-label="Search audit log" value={query} onChange={(e) => setQuery(e.target.value)} />
          <div className="segmented" role="group" aria-label="Filter by who acted">
            {["all", "user", "model", "system"].map((key) => (
              <button key={key} type="button" className={actor === key ? "active" : ""} aria-pressed={actor === key} onClick={() => setActor(key)}>
                {key === "all" ? "Everyone" : ACTOR_LABEL[key]}
              </button>
            ))}
          </div>
          <span className="toolbar-count">{rows.length} shown</span>
        </div>

        {audit.isLoading ? <div className="loading">Loading audit log…</div> : null}
        {audit.isError ? <div className="error-box m-16">Could not load the audit log: {(audit.error as Error).message}</div> : null}
        {audit.data && !rows.length ? <div className="empty"><div className="empty-title">No matching entries</div>Clear the search or choose “Everyone”.</div> : null}

        {rows.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Time</th><th>Who</th><th>Action</th><th>Record</th><th className="right">Details</th></tr></thead>
              <tbody>
                {rows.map((e) => {
                  const open = openId === e.id;
                  const changes = e.after && typeof e.after === "object" ? Object.entries(e.after) : [];
                  return (
                    <Fragment key={e.id}>
                      <tr>
                        <td className="nowrap mono">{new Date(e.created_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
                        <td>
                          <div className="cell-strong">{e.actor_name}</div>
                          <div className="cell-sub">{ACTOR_LABEL[e.actor_type] || e.actor_type}</div>
                        </td>
                        <td><span className={`badge ${e.actor_type === "model" ? "badge-ai" : e.actor_type === "system" ? "badge-neutral" : "badge-success"}`}>{e.action.replaceAll("_", " ")}</span></td>
                        <td><div>{e.entity_type}</div><div className="cell-sub mono">{e.entity_id}</div></td>
                        <td className="right">
                          {changes.length ? (
                            <button className="btn btn-sm btn-ghost" onClick={() => setOpenId(open ? null : e.id)} aria-expanded={open}>{open ? "Hide" : "Show"}</button>
                          ) : <span className="muted">—</span>}
                        </td>
                      </tr>
                      {open ? (
                        <tr className="row-detail">
                          <td colSpan={5}>
                            <dl className="kv">
                              {changes.map(([key, value]) => <Fragment key={key}><dt>{key.replaceAll("_", " ")}</dt><dd className="break">{describe(value)}</dd></Fragment>)}
                            </dl>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
