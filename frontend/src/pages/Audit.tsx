import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { AuditEntry } from "../types";
import { PageHeader } from "../components/PageHeader";
import { Banner, DataTable, EmptyState, Panel, Pill, SearchInput, Toolbar } from "../components/ui";
import type { Column, Tone } from "../components/ui";

const ACTOR_LABEL: Record<string, string> = { user: "Person", model: "MediBytes", system: "System" };

function describe(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not recorded";
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

  // ---------- Render-only values ----------
  const actorTone = (type: string): Tone => (type === "model" ? "ai" : type === "system" ? "neutral" : "info");
  const actionTone = (type: string): Tone => (type === "model" ? "ai" : type === "system" ? "neutral" : "success");
  const changesOf = (e: AuditEntry) => (e.after && typeof e.after === "object" ? Object.entries(e.after) : []);
  const columns: Column<AuditEntry>[] = [
    {
      key: "time", header: "Time", sort: (e) => Date.parse(e.created_at), className: "nowrap",
      cell: (e) => (
        <time className="mono" dateTime={e.created_at}>
          {new Date(e.created_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </time>
      ),
    },
    {
      key: "who", header: "Who", sort: (e) => e.actor_name,
      cell: (e) => (
        <div className="audit-who">
          <span className="cell-strong">{e.actor_name}</span>
          <Pill tone={actorTone(e.actor_type)}>{ACTOR_LABEL[e.actor_type] || e.actor_type}</Pill>
        </div>
      ),
    },
    { key: "action", header: "Action", sort: (e) => e.action, cell: (e) => <Pill tone={actionTone(e.actor_type)}>{e.action.replaceAll("_", " ")}</Pill> },
    {
      key: "record", header: "Record", sort: (e) => `${e.entity_type} ${e.entity_id}`,
      cell: (e) => <><div>{e.entity_type}</div><div className="cell-sub mono">{e.entity_id}</div></>,
    },
    {
      key: "details", header: "Details", align: "right",
      cell: (e) => {
        const open = openId === e.id;
        return changesOf(e).length ? (
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setOpenId(open ? null : e.id)} aria-expanded={open}>
            {open ? "Hide" : "Show"}
            <span className="sr-only"> details for {e.action.replaceAll("_", " ")}</span>
          </button>
        ) : <span className="muted">None</span>;
      },
    },
  ];
  const showEverything = () => { setQuery(""); setActor("all"); };

  return (
    <div className="page pg-audit">
      <PageHeader
        title="Audit log"
        description="A read-only record of every change, approval, dismissal and clinical analysis. Entries cannot be edited."
        meta={audit.data ? <span>{entries.length} most recent entries</span> : null}
      />

      {audit.isError ? <Banner tone="danger" role="alert">Could not load the audit log: {(audit.error as Error).message}</Banner> : null}

      <Panel>
        <Toolbar label="Audit log filters">
          <SearchInput value={query} onChange={setQuery} placeholder="Search action, person or record" label="Search audit log" />
          <div className="segmented" role="group" aria-label="Filter by who acted">
            {["all", "user", "model", "system"].map((key) => (
              <button key={key} type="button" className={actor === key ? "active" : ""} aria-pressed={actor === key} onClick={() => setActor(key)}>
                {key === "all" ? "Everyone" : ACTOR_LABEL[key]}
              </button>
            ))}
          </div>
          <span className="toolbar-count">{rows.length} shown</span>
        </Toolbar>

        {audit.isError ? null : (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(e) => e.id}
            loading={audit.isLoading}
            defaultSort={{ key: "time", dir: "desc" }}
            pageSize={20}
            caption="Audit log entries"
            expanded={(e) => (openId === e.id && changesOf(e).length ? (
              <dl className="kv">
                {changesOf(e).map(([key, value]) => <Fragment key={key}><dt>{key.replaceAll("_", " ")}</dt><dd className="break">{describe(value)}</dd></Fragment>)}
              </dl>
            ) : null)}
            empty={entries.length ? (
              <EmptyState icon="search" title="No entries match"
                action={<button type="button" className="btn btn-sm" onClick={showEverything}>Show all entries</button>}>
                Clear the search or choose Everyone to see the full log.
              </EmptyState>
            ) : (
              <EmptyState icon="audit" title="No entries yet">
                Changes, approvals, dismissals and clinical analyses are recorded here as they happen.
              </EmptyState>
            )}
          />
        )}
      </Panel>
    </div>
  );
}
