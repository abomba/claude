import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ResultsTable } from "../components/ResultsTable";
import { ErrorBox, Field, Loading } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatNumber, unitLabel } from "../lib/i18n";
import type { Outlier, Page, RunDetail, RunOut } from "../lib/types";
import { useApi } from "../lib/useApi";

export function RunsPage() {
  const { data, error, loading } = useApi<Page<RunOut>>("/runs?page_size=500");
  return (
    <div>
      <h1>Przebiegi</h1>
      <ErrorBox error={error} />
      <Loading show={loading} />
      {data && (
        <table className="card" data-testid="runs">
          <thead><tr><th>Przebieg</th><th>Data</th><th className="num">Próbki</th><th className="num">PASS</th><th className="num">WARN</th><th className="num">FAIL</th><th className="num">brak wyniku</th></tr></thead>
          <tbody>
            {data.items.map((r) => (
              <tr key={r.run_code}>
                <td><Link to={`/przebiegi/${encodeURIComponent(r.run_code)}`}>{r.run_code}</Link></td>
                <td>{r.run_date ?? <span className="muted">brak daty</span>}</td>
                <td className="num">{r.n_samples}</td><td className="num">{r.n_pass}</td><td className="num">{r.n_warn}</td><td className="num">{r.n_fail}</td><td className="num">{r.n_missing}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function RunPage() {
  const { code = "" } = useParams();
  const { canEdit } = useAuth();
  const [params, setParams] = useSearchParams();
  const run = useApi<RunDetail>(`/runs/${encodeURIComponent(code)}`);
  const outliers = useApi<Outlier[]>(`/runs/${encodeURIComponent(code)}/outliers`);
  const [date, setDate] = useState<string>();
  const [error, setError] = useState<string>();
  const sort = params.get("sort") ?? "sample_code";
  const page = Number(params.get("page") ?? "1");
  if (run.error) return <ErrorBox error={run.error} />;
  if (!run.data) return <Loading show />;
  const r = run.data;
  const saveDate = async () => {
    try {
      await api(`/runs/${encodeURIComponent(code)}`, { method: "PATCH", body: { run_date: date || null } });
      setDate(undefined);
      run.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div>
      <p><Link to="/przebiegi">‹ Przebiegi</Link></p>
      <h1>Przebieg {r.run_code}</h1>
      <div className="card row">
        <span>Data przebiegu: <b data-testid="run-date">{r.run_date ?? "brak"}</b> {r.run_date_source && <span className="muted">(źródło: {r.run_date_source})</span>}</span>
        {canEdit && (
          <>
            <Field label="Zmień datę"><input type="date" value={date ?? r.run_date ?? ""} onChange={(e) => setDate(e.target.value)} /></Field>
            <button onClick={() => void saveDate()} disabled={date === undefined}>Zapisz datę</button>
          </>
        )}
        <ErrorBox error={error} />
      </div>
      <div className="tiles" data-testid="run-summary">
        <div className="tile"><div className="muted">Próbki</div><div className="n">{r.n_samples}</div></div>
        <div className="tile"><span className="badge v-PASS">PASS – zaliczona</span><div className="n">{r.n_pass}</div></div>
        <div className="tile"><span className="badge v-WARN">WARN – ostrzeżenie</span><div className="n">{r.n_warn}</div></div>
        <div className="tile"><span className="badge v-FAIL">FAIL – niezaliczona</span><div className="n">{r.n_fail}</div></div>
        <div className="tile"><span className="badge v-none">brak wyniku</span><div className="n">{r.n_missing}</div></div>
      </div>
      {r.summary_matches_run_document === false && (
        <p className="error">Podsumowanie z run.json różni się od bazy: {JSON.stringify(r.run_document_summary)}</p>
      )}
      {r.summary_matches_run_document === true && <p className="muted">Zgodne z podsumowaniem w run.json.</p>}
      <h2>Próbki</h2>
      <ResultsTable hideRun filters={{ run: code }} sort={sort} page={page}
        onSort={(s) => setParams({ sort: s })} onPage={(p) => setParams({ sort, page: String(p) })} />
      <h2>Wartości odstające</h2>
      <p className="muted">Wartości poza granicami Tukeya (Q1 − 1,5·IQR, Q3 + 1,5·IQR) w obrębie przebiegu, liczone przy co najmniej 5 próbkach. To wskazówka statystyczna, nie werdykt QC.</p>
      {outliers.data && outliers.data.length === 0 && <p>Brak wartości odstających.</p>}
      {outliers.data && outliers.data.length > 0 && (
        <table className="card" data-testid="outliers">
          <thead><tr><th>Kolumna</th><th>Próbka</th><th className="num">Wartość</th><th className="num">Granice</th><th>Kierunek</th></tr></thead>
          <tbody>
            {outliers.data.map((o) => (
              <tr key={`${o.column}-${o.sample_run_id}`}>
                <td>{o.label} <span className="muted">{unitLabel(o.unit)}</span></td>
                <td><Link to={`/wyniki/${o.sample_run_id}`}>{o.sample_code}</Link></td>
                <td className="num">{formatNumber(o.value)}</td>
                <td className="num">{formatNumber(o.low_fence)} – {formatNumber(o.high_fence)}</td>
                <td>{o.direction === "high" ? "powyżej" : "poniżej"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
