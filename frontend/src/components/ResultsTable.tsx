import { Link } from "react-router-dom";
import { csvUrl, DEMO, query } from "../lib/api";
import { formatNumber, SUMMARY_COLUMNS, unitLabel } from "../lib/i18n";
import type { Page, ResultItem } from "../lib/types";
import { useApi } from "../lib/useApi";
import { ErrorBox, Loading, Pager, SortHeader, VerdictBadge } from "./ui";

export type Filters = Record<string, string | string[] | undefined>;

export function ResultsTable({ filters, sort, page, onSort, onPage, hideRun }: {
  filters: Filters;
  sort: string;
  page: number;
  onSort: (s: string) => void;
  onPage: (p: number) => void;
  hideRun?: boolean;
}) {
  const pageSize = 50;
  const q = query({ ...filters, sort, page, page_size: pageSize });
  const { data, error, loading } = useApi<Page<ResultItem>>(`/results${q}`);
  const exportHref = csvUrl(`/results/export.csv${query({ ...filters, sort })}`);
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <span className="muted">{data ? `${data.total} wyników` : ""}</span>
        {!DEMO && (
          <a className="button secondary" href={exportHref} download>
            Eksport CSV
          </a>
        )}
      </div>
      <ErrorBox error={error} />
      <Loading show={loading && !data} />
      {data && (
        <>
          <div className="table-wrap card" style={{ padding: 0 }}>
            <table data-testid="results-table">
              <thead>
                <tr>
                  <SortHeader id="sample_code" label="Próbka" sort={sort} onSort={onSort} />
                  {!hideRun && <SortHeader id="run_code" label="Przebieg" sort={sort} onSort={onSort} />}
                  <SortHeader id="run_date" label="Data" sort={sort} onSort={onSort} />
                  <th>Zlecenie / zleceniodawca</th>
                  <SortHeader id="verdict" label="Werdykt" sort={sort} onSort={onSort} />
                  <SortHeader id="profile" label="Profil" sort={sort} onSort={onSort} />
                  <SortHeader id="species" label="Gatunek" sort={sort} onSort={onSort} />
                  <SortHeader id="mlst_st" label="ST" sort={sort} onSort={onSort} />
                  <SortHeader id="serotype" label="Serotyp" sort={sort} onSort={onSort} />
                  <SortHeader id="n_amr_genes" label="AMR" sort={sort} onSort={onSort} className="num" />
                  {SUMMARY_COLUMNS.map((c) => (
                    <SortHeader key={c.id} id={c.id} sort={sort} onSort={onSort} className="num"
                      label={<>{c.label}<br /><span className="muted">{unitLabel(c.unit, c.scale)}</span></>} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.sample_run_id} data-sample={r.sample_code} data-run={r.run_code}>
                    <td>
                      <Link to={`/wyniki/${r.sample_run_id}`}>{r.sample_code}</Link>
                      {(!r.has_qc || !r.has_report) && r.has_results && (
                        <span className="muted" title="brak qc.json lub report.json"> · niekompletny</span>
                      )}
                      {r.n_versions > 1 && <span className="muted"> · v{r.version_no}/{r.n_versions}</span>}
                    </td>
                    {!hideRun && (
                      <td>
                        <Link to={`/przebiegi/${encodeURIComponent(r.run_code)}`}>{r.run_code}</Link>
                      </td>
                    )}
                    <td>{r.run_date ?? <span className="muted">brak daty</span>}</td>
                    <td>
                      {r.orders.map((o) => (
                        <div key={o.id}>
                          <Link to={`/zlecenia/${o.id}`}>{o.order_code}</Link>
                          {o.owner && <span className="muted"> · {o.owner.erased ? `Zleceniodawca #${o.owner.id}` : o.owner.full_name}</span>}
                        </div>
                      ))}
                    </td>
                    <td><VerdictBadge verdict={r.verdict} /></td>
                    <td>{r.profile ?? "–"}</td>
                    <td>{r.species ?? "–"}</td>
                    <td>{r.mlst_st ?? "–"}</td>
                    <td>{r.serotype ?? "–"}</td>
                    <td className="num">{formatNumber(r.n_amr_genes)}</td>
                    {SUMMARY_COLUMNS.map((c) => (
                      <td key={c.id} className="num">{formatNumber(r[c.id], c.scale)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageSize={pageSize} total={data.total} onPage={onPage} />
        </>
      )}
    </div>
  );
}
