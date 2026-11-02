import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Field, Loading } from "../components/ui";
import { api, ApiError, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { Order, Owner, Page, SampleOut } from "../lib/types";
import { useApi } from "../lib/useApi";
import { ownerName } from "./Owners";

export function OrdersPage() {
  const { canEdit } = useAuth();
  const { data, error, reload } = useApi<Page<Order>>("/orders?page_size=500");
  const owners = useApi<Page<Owner>>("/owners?page_size=500");
  const [code, setCode] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [formError, setFormError] = useState<string>();
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/orders", { method: "POST", body: { order_code: code, owner_id: ownerId ? Number(ownerId) : null } });
      setCode("");
      setFormError(undefined);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <div>
      <h1>Zlecenia</h1>
      {canEdit && (
        <form className="card row" onSubmit={create}>
          <Field label="Numer zlecenia *"><input name="order_code" required value={code} onChange={(e) => setCode(e.target.value)} /></Field>
          <Field label="Zleceniodawca">
            <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
              <option value="">nieprzypisany</option>
              {owners.data?.items.filter((o) => !o.erased).map((o) => <option key={o.id} value={o.id}>{ownerName(o)}</option>)}
            </select>
          </Field>
          <button type="submit">Dodaj zlecenie</button>
          <ErrorBox error={formError} />
        </form>
      )}
      <ErrorBox error={error} />
      {data && (
        <table className="card" data-testid="orders">
          <thead><tr><th>Zlecenie</th><th>Zleceniodawca</th><th className="num">Próbki</th></tr></thead>
          <tbody>
            {data.items.map((o) => (
              <tr key={o.id}>
                <td><Link to={`/zlecenia/${o.id}`}>{o.order_code}</Link></td>
                <td>{o.owner ? ownerName(o.owner) : <span className="muted">nieprzypisany</span>}</td>
                <td className="num">{o.n_samples}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function OrderDetailPage() {
  const { id = "" } = useParams();
  const { canEdit } = useAuth();
  const order = useApi<Order>(`/orders/${id}`);
  const owners = useApi<Page<Owner>>("/owners?page_size=500");
  const [search, setSearch] = useState("");
  const candidates = useApi<Page<SampleOut>>(canEdit && search.length >= 2 ? `/samples${query({ q: search, page_size: 20 })}` : null);
  const [error, setError] = useState<string>();
  if (order.error) return <ErrorBox error={order.error} />;
  if (!order.data) return <Loading show />;
  const o = order.data;
  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(undefined);
      order.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  const inOrder = new Set(o.samples?.map((s) => s.id));
  return (
    <div>
      <p><Link to="/zlecenia">‹ Zlecenia</Link></p>
      <h1>Zlecenie {o.order_code}</h1>
      <ErrorBox error={error} />
      <div className="card row">
        <span>Zleceniodawca: <b data-testid="order-owner">{o.owner ? ownerName(o.owner) : "nieprzypisany"}</b></span>
        {canEdit && (
          <Field label="Przypisz zleceniodawcę">
            <select name="owner" value={o.owner?.id ?? ""} onChange={(e) => void run(() => api(`/orders/${id}`, { method: "PATCH", body: { owner_id: e.target.value ? Number(e.target.value) : null } }))}>
              <option value="">nieprzypisany</option>
              {owners.data?.items.filter((x) => !x.erased).map((x) => <option key={x.id} value={x.id}>{ownerName(x)}</option>)}
            </select>
          </Field>
        )}
      </div>
      {o.meta && Object.keys(o.meta).length > 0 && <p className="muted">meta z order.json (bez interpretacji): <span className="mono">{JSON.stringify(o.meta)}</span></p>}
      <h2>Próbki w zleceniu ({o.n_samples})</h2>
      <table className="card" data-testid="order-samples">
        <tbody>
          {o.samples?.map((s) => (
            <tr key={s.id}>
              <td>{s.sample_code}</td>
              <td><Link to={`/probki?q=${encodeURIComponent(s.sample_code)}`}>wyniki</Link></td>
              <td>{canEdit && <button className="secondary" onClick={() => void run(() => api(`/orders/${id}/samples/${s.id}`, { method: "DELETE" }))}>Usuń ze zlecenia</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {canEdit && (
        <div className="card">
          <h3>Przypisz próbki</h3>
          <Field label="Szukaj próbki (min. 2 znaki)"><input name="sample_search" value={search} onChange={(e) => setSearch(e.target.value)} /></Field>
          <table data-testid="sample-candidates">
            <tbody>
              {candidates.data?.items.map((s) => (
                <tr key={s.id}>
                  <td>{s.sample_code}</td>
                  <td className="muted">{s.results.map((r) => r.run_code).join(", ")}</td>
                  <td>
                    {inOrder.has(s.id) ? <span className="muted">już w zleceniu</span> : (
                      <button onClick={() => void run(() => api(`/orders/${id}/samples`, { method: "POST", body: { sample_ids: [s.id] } }))}>Przypisz</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
