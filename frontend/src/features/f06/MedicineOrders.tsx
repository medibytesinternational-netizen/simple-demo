import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import { useCan } from "../../session";
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
    <div className="card">
      <div className="card-head"><div className="card-title">Order a medicine</div></div>
      <div className="card-pad">
        <div className="small muted mb-2">Only a doctor can order. Ordering is not giving: a nurse records each dose.</div>
        <div className="form-row">
          <div>
            <label className="field-label">Action</label>
            <select className="input" value={action} onChange={(event) => setAction(event.target.value as OrderAction)}>
              <option value="start">Start</option>
              <option value="change">Change</option>
              <option value="stop">Stop</option>
            </select>
          </div>
          <div>
            <label className="field-label">Medicine</label>
            <input className="input" value={drug} onChange={(event) => setDrug(event.target.value)} />
          </div>
          {action !== "stop"
            ? FIELDS.map((field) => (
                <div key={field}>
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
        <div className="form-row mt-2" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 260 }}>
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
          >
            Place order
          </button>
        </div>
        {error ? <div className="error-box mt-2">{error}</div> : null}
        {alerts.map((alert) => (
          <div className="alert-card critical mt-2" key={alert.id}>
            <div className="alert-title">{alert.rule_id} · {alert.title}</div>
            <div className="alert-explanation">{alert.explanation}</div>
          </div>
        ))}
      </div>
    </div>
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
    <div className="form-row" style={{ alignItems: "flex-end" }}>
      <select className="input" value={status} onChange={(event) => setStatus(event.target.value as DoseStatus)}>
        <option value="given">Given</option>
        <option value="held">Held</option>
        <option value="refused">Refused</option>
      </select>
      <input className="input" value={note} placeholder="Note (optional)" onChange={(event) => setNote(event.target.value)} />
      <button className="btn btn-sm btn-primary" disabled={give.isPending} onClick={() => give.mutate()}>Record dose</button>
      {error ? <span className="small" style={{ color: "var(--critical)" }}>{error}</span> : null}
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
    <div className="flex-col gap-3">
      <div className="card">
        <div className="card-head">
          <div className="card-title">Current orders</div>
          <span className="badge badge-neutral">{meds.data?.current_medications.length ?? 0}</span>
        </div>
        <table className="table">
          <thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Indication</th><th></th></tr></thead>
          <tbody>
            {meds.data?.current_medications.map((med) => (
              <tr key={med.event_id}>
                <td><strong>{med.drug}</strong></td>
                <td>{med.dose}</td>
                <td>{med.route}</td>
                <td>{med.frequency}</td>
                <td>{med.indication || <span className="muted">not documented</span>}</td>
                <td>
                  {canGive ? (
                    giving === med.event_id ? (
                      <GiveForm med={med} onDone={() => setGiving(null)} />
                    ) : (
                      <button className="btn btn-sm" onClick={() => setGiving(med.event_id)}>Record a dose</button>
                    )
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canOrder ? <OrderForm /> : null}

      <div className="card">
        <div className="card-head">
          <div className="card-title">Doses recorded by nurses</div>
          <span className="badge badge-neutral">{doses.isError ? "—" : doses.data?.administrations.length ?? 0}</span>
        </div>
        {doses.isError ? (
          <div className="card-pad small muted">The dose record is not available right now, so recorded doses cannot be shown.</div>
        ) : doses.data && !doses.data.administrations.length ? (
          <div className="card-pad small muted">No dose has been recorded yet.</div>
        ) : null}
        <table className="table">
          <tbody>
            {doses.data?.administrations.map((dose) => (
              <tr key={dose.event_id}>
                <td><span className={`badge ${dose.status === "given" ? "badge-success" : "badge-warning"}`}>{dose.status}</span></td>
                <td>{dose.drug} {dose.dose}</td>
                <td className="small muted">{new Date(dose.given_at).toLocaleString()}</td>
                <td className="small muted">{dose.recorded_by}</td>
                <td className="small">{dose.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
