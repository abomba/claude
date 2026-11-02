import { useState, type FormEvent } from "react";
import { ErrorBox, Field } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, ROLE_LABEL } from "../lib/i18n";
import type { Role, User } from "../lib/types";
import { useApi } from "../lib/useApi";

export function UsersPage() {
  const { isAdmin } = useAuth();
  const { data, error, reload } = useApi<User[]>(isAdmin ? "/users" : null);
  const [form, setForm] = useState({ username: "", role: "viewer" as Role, password: "" });
  const [msg, setMsg] = useState<string>();
  if (!isAdmin) return <p>Ta strona jest dostępna tylko dla administratora.</p>;
  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setMsg(undefined);
      reload();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : String(e));
    }
  };
  const create = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api("/users", { method: "POST", body: form });
      setForm({ username: "", role: "viewer", password: "" });
    });
  };
  return (
    <div>
      <h1>Użytkownicy</h1>
      <form className="card row" onSubmit={create}>
        <Field label="Login"><input required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
        <Field label="Rola">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        </Field>
        <Field label="Hasło (min. 12 znaków)"><input type="password" required minLength={12} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <button type="submit">Dodaj użytkownika</button>
      </form>
      <ErrorBox error={error ?? msg} />
      <table className="card">
        <thead><tr><th>Login</th><th>Rola</th><th>Aktywny</th><th>Ostatnie logowanie</th><th /></tr></thead>
        <tbody>
          {data?.map((u) => (
            <tr key={u.id}>
              <td>{u.username}{u.locked && <span className="badge v-WARN"> zablokowany</span>}</td>
              <td>
                <select value={u.role} onChange={(e) => void run(() => api(`/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } }))}>
                  {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
              </td>
              <td>{u.is_active ? "tak" : "nie"}</td>
              <td>{formatDateTime(u.last_login_at)}</td>
              <td>
                <button className="secondary" onClick={() => void run(() => api(`/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }))}>
                  {u.is_active ? "Dezaktywuj" : "Aktywuj"}
                </button>{" "}
                <button className="secondary" onClick={() => {
                  const p = window.prompt("Nowe hasło (min. 12 znaków)");
                  if (p) void run(() => api(`/users/${u.id}/password`, { method: "POST", body: { password: p } }));
                }}>Ustaw hasło</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
