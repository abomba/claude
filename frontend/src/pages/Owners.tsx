import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Field, Loading } from "../components/ui";
import { api, ApiError, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { Order, Owner, Page } from "../lib/types";
import { useApi } from "../lib/useApi";

export function ownerName(o: { id: number; full_name: string | null; erased: boolean }): string {
  return o.erased ? `Zleceniodawca #${o.id} (dane usunięte)` : (o.full_name ?? `#${o.id}`);
}

export function OwnersPage() {
  const { canEdit } = useAuth();
  const [q, setQ] = useState("");
  const { data, error, loading, reload } = useApi<Page<Owner>>(`/owners${query({ q, page_size: 200 })}`);
  const [form, setForm] = useState({ full_name: "", email: "" });
  const [formError, setFormError] = useState<string>();
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/owners", { method: "POST", body: { full_name: form.full_name, email: form.email || null } });
      setForm({ full_name: "", email: "" });
      setFormError(undefined);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    }
  };
  const showEmail = data?.items.some((o) => "email" in o) ?? false;
  return (
    <div>
      <h1>Zleceniodawcy</h1>
      <div className="card row">
        <Field label="Szukaj"><input value={q} onChange={(e) => setQ(e.target.value)} /></Field>
      </div>
      {canEdit && (
        <form className="card row" onSubmit={create} data-testid="owner-form">
          <Field label="Imię i nazwisko *"><input name="full_name" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="E-mail"><input name="email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <button type="submit">Dodaj zleceniodawcę</button>
          <ErrorBox error={formError} />
        </form>
      )}
      <ErrorBox error={error} />
      <Loading show={loading && !data} />
      {data && (
        <table className="card" data-testid="owners">
          <thead><tr><th>Zleceniodawca</th>{showEmail && <th>E-mail</th>}<th className="num">Zlecenia</th></tr></thead>
          <tbody>
            {data.items.map((o) => (
              <tr key={o.id}>
                <td><Link to={`/zleceniodawcy/${o.id}`}>{ownerName(o)}</Link></td>
                {showEmail && <td>{o.email ?? ""}</td>}
                <td className="num">{o.n_orders}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function OwnerDetailPage() {
  const { id = "" } = useParams();
  const { canEdit, isAdmin } = useAuth();
  const owner = useApi<Owner>(`/owners/${id}`);
  const orders = useApi<Page<Order>>(`/orders?owner_id=${id}&page_size=200`);
  const [edit, setEdit] = useState<{ full_name: string; email: string }>();
  const [error, setError] = useState<string>();
  if (owner.error) return <ErrorBox error={owner.error} />;
  if (!owner.data) return <Loading show />;
  const o = owner.data;
  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setEdit(undefined);
      setError(undefined);
      owner.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div>
      <p><Link to="/zleceniodawcy">‹ Zleceniodawcy</Link></p>
      <h1>{ownerName(o)}</h1>
      <ErrorBox error={error} />
      <div className="card">
        {!edit && (
          <dl className="kv">
            <dt>Imię i nazwisko</dt><dd>{o.full_name ?? "–"}</dd>
            {"email" in o && (<><dt>E-mail</dt><dd>{o.email ?? "–"}</dd></>)}
          </dl>
        )}
        {edit && (
          <div className="row">
            <Field label="Imię i nazwisko"><input name="edit_full_name" value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} /></Field>
            <Field label="E-mail"><input name="edit_email" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></Field>
            <button onClick={() => void run(() => api(`/owners/${id}`, { method: "PATCH", body: { full_name: edit.full_name, email: edit.email || null } }))}>Zapisz</button>
            <button className="secondary" onClick={() => setEdit(undefined)}>Anuluj</button>
          </div>
        )}
        {canEdit && !o.erased && !edit && (
          <p><button className="secondary" onClick={() => setEdit({ full_name: o.full_name ?? "", email: o.email ?? "" })}>Edytuj</button></p>
        )}
        {isAdmin && !o.erased && (
          <p>
            <button className="danger" onClick={() => {
              if (window.confirm("Usunąć dane osobowe zleceniodawcy? Zlecenia i wyniki pozostaną (pseudonimizacja). Operacji nie można cofnąć.")) void run(() => api(`/owners/${id}/erase`, { method: "POST" }));
            }}>Usuń dane osobowe</button>
          </p>
        )}
      </div>
      <h2>Zlecenia</h2>
      <table className="card">
        <thead><tr><th>Zlecenie</th><th className="num">Próbki</th></tr></thead>
        <tbody>{orders.data?.items.map((x) => <tr key={x.id}><td><Link to={`/zlecenia/${x.id}`}>{x.order_code}</Link></td><td className="num">{x.n_samples}</td></tr>)}</tbody>
      </table>
    </div>
  );
}
