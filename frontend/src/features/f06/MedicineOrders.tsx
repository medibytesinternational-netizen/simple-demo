import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import { useCan } from "../../session";
import { Banner, DataTable, EmptyState, Panel, Pill } from "../../components/ui";
import { noteOk } from "./rules";
import { MIN_NOTE } from "./types";
import type { ActiveMedicine, Administration, DoseStatus, NewAlert, OrderAction } from "./types";

const FIELDS = ["dose", "route", "frequency", "indication"] as const;

function OrderForm() {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<OrderAction>("start");
  const [drug, setDrug] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [alerts, setAlerts] = useState<NewAlert[]>([]);
  const order = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = { action, drug: drug.trim(), reason: reason.trim() };
      for (const field of FIELDS) if (values[field]?.trim()) body[field] = values[field].trim();
      return post<{ new_alerts: NewAlert[] }>("/medications/orders", body);
    },
    onSuccess: (result) => {
      setError("");
      setAlerts(result.new_alerts);
      setReason("");
      setValues({});
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  return (
    <Panel title="Order a medicine" sub="Only a doctor can order. Ordering is not giving: a nurse records each dose." padded>
      <div className="form-row">
        <div className="form-field">
          <label className="field-label">Action</label>
          <select className="input" value={action} onChange={(event) => setAction(event.target.value as OrderAction)}>
            <option value="start">Start</option>
            <option value="change">Change</option>
            <option value="stop">Stop</option>
          </select>
        </div>
        <div className="form-field">
          <label className="field-label">Medicine</label>
          <input className="input" value={drug} onChange={(event) => setDrug(event.target.value)} />
        </div>
        {action !== "stop"
          ? FIELDS.map((field) => (
              <div className="form-field" key={field}>
                <label className="field-label">{field[0].toUpperCase() + field.slice(1)}</label>
                <input
                  className="input"
                  value={values[field] || ""}
                  onChange={(event) => setValues({ ...values, [field]: event.target.value })}
                />
              </div>
            ))
          : null}
      </div>
      <div className="form-row mt-3">
        <div className="form-field order-reason">
          <label className="field-label">Reason</label>
          <input
            className="input"
            value={reason}
            placeholder={`At least ${MIN_NOTE} characters`}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
        <button
          className="btn btn-primary"
          disabled={drug.trim().length < 2 || !noteOk(reason) || order.isPending}
          onClick={() => order.mutate()}
          aria-busy={order.isPending || undefined}
        >
          {order.isPending ? <span className="spinner" /> : null}
          Place order
        </button>
      </div>
      {error ? <div className="error-box mt-3" role="alert">{error}</div> : null}
      {alerts.length ? (
        <div className="flex-col gap-2 mt-3">
          {alerts.map((alert) => (
            <Banner tone="danger" key={alert.id} title={`${alert.rule_id} · ${alert.title}`}>
              {alert.explanation}
            </Banner>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

function GiveForm({ med, onDone }: { med: ActiveMedicine; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<DoseStatus>("given");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const give = useMutation({
    mutationFn: () => post(`/medications/orders/${med.event_id}/administrations`, { status, note: note.trim() || undefined }),
    onSuccess: () => {
      setNote("");
      setError("");
      queryClient.invalidateQueries();
      onDone();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  return (
    <div className="give-form">
      <select className="input select-sm" aria-label="Dose outcome" value={status} onChange={(event) => setStatus(event.target.value as DoseStatus)}>
        <option value="given">Given</option>
        <option value="held">Held</option>
        <option value="refused">Refused</option>
      </select>
      <input className="input" aria-label="Dose note" value={note} placeholder="Note (optional)" onChange={(event) => setNote(event.target.value)} />
      <button className="btn btn-sm btn-primary" disabled={give.isPending} onClick={() => give.mutate()} aria-busy={give.isPending || undefined}>
        {give.isPending ? <span className="spinner" /> : null}
        Record dose
      </button>
      {error ? <span className="give-error" role="alert">{error}</span> : null}
    </div>
  );
}

export default function MedicineOrders() {
  const canOrder = useCan("order_medicine");
  const canGive = useCan("give_medicine");
  const [giving, setGiving] = useState<string | null>(null);
  const meds = useQuery<{ current_medications: ActiveMedicine[] }>({
    queryKey: ["medications"],
    queryFn: () => get("/medications"),
  });
  const doses = useQuery<{ administrations: Administration[] }>({
    queryKey: ["administrations"],
    queryFn: () => get("/medications/administrations"),
  });

  return (
    <section className="section" aria-labelledby="orders-and-doses">
      <div className="section-head">
        <h2 className="section-title" id="orders-and-doses">Orders and doses</h2>
        <span className="small muted">Ordering is not giving: a nurse records each dose.</span>
      </div>

      <Panel title="Current orders" count={meds.data?.current_medications.length ?? 0}>
        <DataTable<ActiveMedicine>
          caption="Current medicine orders"
          rows={meds.data?.current_medications ?? []}
          rowKey={(med) => med.event_id}
          loading={meds.isLoading}
          empty={<EmptyState icon="pill" title="No active orders.">A doctor can start a medicine with the order form below.</EmptyState>}
          columns={[
            { key: "drug", header: "Drug", sort: (med) => med.drug, cell: (med) => <span className="cell-strong">{med.drug}</span> },
            { key: "dose", header: "Dose", cell: (med) => med.dose },
            { key: "route", header: "Route", cell: (med) => med.route },
            { key: "frequency", header: "Frequency", cell: (med) => med.frequency },
            { key: "indication", header: "Indication", cell: (med) => med.indication || <span className="muted">not documented</span> },
            {
              key: "give", header: <span className="sr-only">Record a dose</span>,
              cell: (med) => canGive ? (
                giving === med.event_id ? (
                  <GiveForm med={med} onDone={() => setGiving(null)} />
                ) : (
                  <button className="btn btn-sm" onClick={() => setGiving(med.event_id)}>Record a dose</button>
                )
              ) : null,
            },
          ]}
        />
      </Panel>

      {canOrder ? <OrderForm /> : null}

      <Panel title="Doses recorded by nurses" count={doses.isError ? undefined : doses.data?.administrations.length ?? 0}>
        {doses.isError ? (
          <div className="panel-body">
            <Banner tone="warning">The dose record is not available right now, so recorded doses cannot be shown.</Banner>
          </div>
        ) : (
          <DataTable<Administration>
            caption="Doses recorded by nurses"
            rows={doses.data?.administrations ?? []}
            rowKey={(dose) => dose.event_id}
            loading={doses.isLoading}
            empty={<EmptyState icon="clock" title="No dose has been recorded yet.">A nurse records each dose from the current orders above.</EmptyState>}
            columns={[
              { key: "status", header: "Outcome", sort: (dose) => dose.status, cell: (dose) => <Pill tone={dose.status === "given" ? "success" : "warning"}>{dose.status}</Pill> },
              { key: "drug", header: "Medicine", sort: (dose) => dose.drug, cell: (dose) => <span className="cell-strong">{dose.drug} {dose.dose}</span> },
              { key: "given", header: "Recorded at", sort: (dose) => dose.given_at, cell: (dose) => <span className="small muted">{new Date(dose.given_at).toLocaleString()}</span> },
              { key: "by", header: "By", cell: (dose) => <span className="small muted">{dose.recorded_by}</span> },
              { key: "note", header: "Note", cell: (dose) => <span className="small">{dose.note}</span> },
            ]}
          />
        )}
      </Panel>
    </section>
  );
}
