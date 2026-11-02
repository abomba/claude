import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CheckBadge, ErrorBox, Field, Loading, ToolStatusBadge, VerdictBadge } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, formatNumber, formatRule, formatValue, NAMESPACE_LABEL, unitLabel } from "../lib/i18n";
import type { ResultDetail, SampleField, Tool, Version, VersionSummary } from "../lib/types";
import { useApi } from "../lib/useApi";

function Header({ detail, version }: { detail: ResultDetail; version: Version | null }) {
  return (
    <div className="card">
      <div className="row" style={{ alignItems: "center" }}>
        <h1 style={{ margin: 0 }} data-testid="sample-code">{detail.sample_code}</h1>
        <span data-testid="verdict"><VerdictBadge verdict={version?.verdict} /></span>
        {version && !version.is_current && <span className="badge v-WARN">wersja archiwalna {version.version_no}</span>}
      </div>
      <dl className="kv" style={{ marginTop: 10 }}>
        <dt>Przebieg</dt>
        <dd>
          <Link to={`/przebiegi/${encodeURIComponent(detail.run.run_code)}`}>{detail.run.run_code}</Link> · {detail.run.run_date ?? "brak daty przebiegu"}
        </dd>
        <dt>Zlecenia</dt>
        <dd>
          {detail.orders.length === 0 && <span className="muted">brak</span>}
          {detail.orders.map((o) => (
            <span key={o.id} style={{ marginRight: 12 }}>
              <Link to={`/zlecenia/${o.id}`}>{o.order_code}</Link>
              {o.owner && <> · <Link to={`/zleceniodawcy/${o.owner.id}`}>{o.owner.erased ? `Zleceniodawca #${o.owner.id}` : o.owner.full_name}</Link></>}
            </span>
          ))}
        </dd>
        {version?.thresholds && (
          <>
            <dt>Profil progów</dt>
            <dd>
              {version.thresholds.profile} · {version.thresholds.read_length_profile ?? "–"} · gatunek progów: {version.thresholds.species ?? "–"}
            </dd>
            <dt>Łańcuch progów</dt>
            <dd className="mono">{version.thresholds.chain.join(" → ")}</dd>
            <dt>Progi (sha256)</dt>
            <dd className="mono" title={version.thresholds.sha256} data-testid="thresholds-sha">{version.thresholds.sha256.slice(0, 12)}…</dd>
          </>
        )}
        {version && (
          <>
            <dt>Kompletność</dt>
            <dd>
              ocena QC (qc.json): {version.has_qc ? "tak" : <b>brak</b>} · raport (report.json): {version.has_report ? "tak" : <b>brak</b>}
            </dd>
            <dt>Wersja wyniku</dt>
            <dd>
              {version.version_no} z {detail.n_versions} · wczytano {formatDateTime(version.created_at)} · qceval {version.evaluator_version ?? "–"}
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}

function Checks({ version }: { version: Version }) {
  if (!version.has_qc) return <p className="notice">Brak oceny QC (qc.json) dla tej wersji – werdykt nie jest dostępny.</p>;
  return (
    <div className="card">
      <h2>Kontrola jakości</h2>
      <div className="table-wrap">
        <table data-testid="checks">
          <thead>
            <tr>
              <th>Metryka</th>
              <th className="num">Wartość</th>
              <th>Jednostka</th>
              <th>Reguła</th>
              <th>Wymagana</th>
              <th>Status</th>
              <th>Powód</th>
            </tr>
          </thead>
          <tbody>
            {version.checks.map((c) => (
              <tr key={c.ordinal} data-metric={c.metric}>
                <td>
                  {c.label ?? c.metric} {c.label && <span className="muted mono">{c.metric}</span>}
                </td>
                <td className="num">{formatValue(c.value)}</td>
                <td>{unitLabel(c.unit)}</td>
                <td className="mono">{formatRule(c.rule)}</td>
                <td>{c.required ? "tak" : "nie"}</td>
                <td className="wrap"><CheckBadge status={c.status} /></td>
                <td className="wrap">{c.reason ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {version.reasons.length > 0 && (<><h3>Powody werdyktu</h3><ul>{version.reasons.map((r) => <li key={r}>{r}</li>)}</ul></>)}
      {version.advisory.length > 0 && (<><h3>Uwagi (nie wpływają na werdykt)</h3><ul>{version.advisory.map((r) => <li key={r}>{r}</li>)}</ul></>)}
      {version.notes.length > 0 && (<><h3>Notatki</h3><ul>{version.notes.map((r) => <li key={r}>{r}</li>)}</ul></>)}
    </div>
  );
}

function ToolCard({ tool }: { tool: Tool }) {
  const [showAbsent, setShowAbsent] = useState(false);
  return (
    <div className="tool" data-tool={tool.tool}>
      <header>
        <b>{tool.tool}</b>
        <ToolStatusBadge status={tool.status} />
        <span className="muted">
          wersja {tool.tool_version}
          {tool.database_version && ` · baza ${tool.database_version}`} · parser {tool.parser_name} {tool.parser_version}
        </span>
      </header>
      {tool.messages && tool.messages.length > 0 && <ul>{tool.messages.map((m) => <li key={m}>{m}</li>)}</ul>}
      {tool.metrics.length > 0 && (
        <table>
          <tbody>
            {tool.metrics.map((m) => (
              <tr key={m.key} data-metric={m.key}>
                <td>{m.label}</td>
                <td className="num">{m.is_null ? <span className="null">brak wartości (null)</span> : formatValue(m.value)}</td>
                <td className="muted">{unitLabel(m.unit)}</td>
              </tr>
            ))}
            {showAbsent && tool.absent_metrics.map((k) => (
              <tr key={k}>
                <td className="absent">{k}</td>
                <td className="absent num">nieobecna</td>
                <td />
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {tool.absent_metrics.length > 0 && (
        <button className="secondary" style={{ marginTop: 6, fontSize: "0.8rem" }} onClick={() => setShowAbsent(!showAbsent)}>
          {showAbsent ? "ukryj nieobecne" : `pokaż nieobecne (${tool.absent_metrics.length})`}
        </button>
      )}
    </div>
  );
}

function Typing({ version }: { version: Version }) {
  const t = version.typing;
  const species = t.report_species as { name?: string; pct?: number; source?: string; match?: boolean } | null;
  return (
    <div className="card">
      <h2>Typowanie</h2>
      <dl className="kv">
        <dt>Gatunek (raport)</dt>
        <dd>{species?.name ? `${species.name} (${formatNumber(species.pct)}%, ${species.source ?? ""}${species.match === false ? ", niezgodny z oczekiwanym" : ""})` : "–"}</dd>
        <dt>MLST</dt>
        <dd data-testid="mlst">ST {t.mlst_sequence_type ?? "nie przypisano"} · schemat {t.mlst_scheme ?? "–"}</dd>
        {t.mlst_alleles && Object.keys(t.mlst_alleles).length > 0 && (
          <><dt>Allele MLST</dt><dd className="mono">{Object.entries(t.mlst_alleles).map(([k, v]) => `${k}(${v})`).join(" ")}</dd></>
        )}
        <dt>Serotyp (SeqSero2)</dt>
        <dd>{t.seqsero2_serotype ?? "–"} {t.seqsero2_antigenic_profile && <span className="muted">({t.seqsero2_antigenic_profile})</span>}</dd>
        <dt>Serotyp (ECTyper)</dt>
        <dd>{t.ectyper_serotype ?? "–"}</dd>
        {t.ectyper_qc_flag && (<><dt>Flaga narzędzia ECTyper</dt><dd>{t.ectyper_qc_flag} <span className="muted">(nie jest werdyktem QC)</span></dd></>)}
      </dl>
    </div>
  );
}

function Amr({ version }: { version: Version }) {
  const [type, setType] = useState("");
  const [cls, setCls] = useState("");
  if (version.amr_hits.length === 0) return null;
  const types = [...new Set(version.amr_hits.map((h) => h.type ?? ""))];
  const hits = version.amr_hits.filter((h) => (!type || h.type === type) && (!cls || (h.class ?? "").toLowerCase().includes(cls.toLowerCase())));
  return (
    <div className="card">
      <h2>AMR (AMRFinderPlus)</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <Field label="Typ">
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">wszystkie</option>
            {types.map((t) => <option key={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Klasa">
          <input value={cls} onChange={(e) => setCls(e.target.value)} />
        </Field>
      </div>
      <table data-testid="amr">
        <thead>
          <tr><th>Gen</th><th>Nazwa</th><th>Typ</th><th>Podtyp</th><th>Klasa</th><th>Metoda</th><th className="num">% identyczności</th><th className="num">% pokrycia</th></tr>
        </thead>
        <tbody>
          {hits.map((h) => (
            <tr key={h.ordinal}>
              <td className="mono">{h.symbol}</td><td className="wrap">{h.name}</td><td>{h.type}</td><td>{h.subtype}</td><td>{h.class}</td><td>{h.method}</td>
              <td className="num">{formatNumber(h.pct_identity)}</td><td className="num">{formatNumber(h.pct_coverage)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Software({ version }: { version: Version }) {
  const sw = version.software;
  return (
    <div className="card">
      <h2>Oprogramowanie i bazy danych</h2>
      {sw && <p>Pipeline {sw.pipeline ?? "–"} {sw.pipeline_version ?? ""} · Nextflow {sw.nextflow_version ?? "–"} · samplereport {version.report_generator_version ?? "–"}</p>}
      <table>
        <thead><tr><th>Etap</th><th>Narzędzie</th><th>Wersje</th><th>Bazy danych</th></tr></thead>
        <tbody>
          {sw?.groups.flatMap((g) => g.tools.map((t) => (
            <tr key={`${g.stage}-${t.tool}`}><td>{g.stage}</td><td>{t.label}</td><td>{t.versions.join(", ")}</td><td>{t.databases.join(", ")}</td></tr>
          )))}
          {version.tools.map((t) => (
            <tr key={`m-${t.tool}`}><td className="muted">{NAMESPACE_LABEL[t.namespace] ?? t.namespace}</td><td>{t.tool}</td><td>{t.tool_version}</td><td>{t.database_version ?? ""}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function History({ id, onChange }: { id: string; onChange: () => void }) {
  const { canEdit } = useAuth();
  const { data, reload } = useApi<VersionSummary[]>(`/results/${id}/versions`);
  const [error, setError] = useState<string>();
  if (!data || data.length === 0) return null;
  const setCurrent = async (no: number) => {
    try {
      await api(`/results/${id}/current`, { method: "POST", body: { version_no: no } });
      reload();
      onChange();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div className="card">
      <h2>Historia przetwarzania</h2>
      <ErrorBox error={error} />
      <table data-testid="history">
        <thead><tr><th>Wersja</th><th>Wczytano</th><th>Werdykt</th><th>Profil</th><th>Progi (sha256)</th><th>Zmiany sprawdzeń</th><th /></tr></thead>
        <tbody>
          {data.map((v) => (
            <tr key={v.version_no}>
              <td><Link to={`?wersja=${v.version_no}`}>{v.version_no}</Link>{v.is_current && <b> (bieżąca)</b>}</td>
              <td>{formatDateTime(v.created_at)}</td>
              <td><VerdictBadge verdict={v.verdict} /></td>
              <td>{v.profile ?? "–"}</td>
              <td className="mono">{v.thresholds_sha256?.slice(0, 12) ?? "–"}</td>
              <td className="wrap">{v.check_changes.map((c) => `${c.metric}: ${c.old_status ?? "–"} → ${c.new_status ?? "–"}`).join("; ")}</td>
              <td>{canEdit && !v.is_current && <button className="secondary" onClick={() => void setCurrent(v.version_no)}>Ustaw jako bieżącą</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metadata({ detail, onSaved }: { detail: ResultDetail; onSaved: () => void }) {
  const { canEdit } = useAuth();
  const fields = useApi<SampleField[]>("/sample-fields");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(detail.sample?.metadata ?? {}).map(([k, v]) => [k, String(v)])),
  );
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();
  if (!detail.sample) return <div className="card"><h2>Metadane próbki</h2><p className="muted">Wynik nie jest powiązany z próbką biologiczną.</p></div>;
  const active = (fields.data ?? []).filter((f) => f.is_active || values[f.key] !== undefined);
  const save = async () => {
    setError(undefined);
    const metadata: Record<string, unknown> = {};
    for (const f of active) {
      const v = values[f.key] ?? "";
      metadata[f.key] = v === "" ? null : f.data_type === "number" ? Number(v) : v;
    }
    try {
      await api(`/samples/${detail.sample!.id}`, { method: "PATCH", body: { metadata } });
      setMessage("Zapisano");
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <div className="card" data-testid="metadata">
      <h2>Metadane próbki {detail.sample.sample_code}</h2>
      <div className="row">
        {active.map((f) => (
          <Field key={f.key} label={`${f.label}${f.required ? " *" : ""}`}>
            {f.data_type === "choice" ? (
              <select name={f.key} disabled={!canEdit} value={values[f.key] ?? ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                <option value="" />
                {f.choices?.map((c) => <option key={c}>{c}</option>)}
              </select>
            ) : (
              <input name={f.key} disabled={!canEdit} type={f.data_type === "date" ? "date" : f.data_type === "number" ? "number" : "text"}
                value={values[f.key] ?? ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            )}
          </Field>
        ))}
        {canEdit && <button onClick={() => void save()}>Zapisz metadane</button>}
        {message && <span className="muted">{message}</span>}
      </div>
      <ErrorBox error={error} />
    </div>
  );
}

function Technical({ version }: { version: Version }) {
  const t = version.technical;
  if (!t) return null;
  return (
    <details className="card">
      <summary><b>Dane techniczne</b> (pliki, ścieżki, surowe dane)</summary>
      <dl className="kv" style={{ marginTop: 8 }}>
        <dt>Plik progów</dt><dd className="mono">{t.thresholds_file ?? "–"}</dd>
        <dt>Wczytanie</dt><dd className="mono">#{t.load_batch_id} · {t.load_invoked_by} · {t.load_source_dir}</dd>
        <dt>meta (report.json)</dt><dd className="mono">{JSON.stringify(t.meta)}</dd>
      </dl>
      {t.load_warnings.length > 0 && (<><h3>Ostrzeżenia loadera</h3><ul>{t.load_warnings.map((w) => <li key={w}>{w}</li>)}</ul></>)}
      <h3>Dokumenty</h3>
      <table>
        <tbody>{t.documents.map((d) => <tr key={d.sha256}><td>{d.kind}</td><td>{d.tool ?? ""}</td><td className="mono">{d.file_name}</td><td className="mono">{d.sha256.slice(0, 16)}…</td></tr>)}</tbody>
      </table>
      <h3>Surowe dane narzędzi</h3>
      {Object.entries(t.tools).map(([tool, v]) => (
        <details key={tool}><summary className="mono">{tool}</summary><pre>{JSON.stringify(v, null, 2)}</pre></details>
      ))}
    </details>
  );
}

export function ResultPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const versionNo = params.get("wersja");
  const path = versionNo ? `/results/${id}/versions/${versionNo}` : `/results/${id}`;
  const { data, error, loading, reload } = useApi<ResultDetail>(path);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading show={loading} />;
  const v = data.version;
  const namespaces = v ? [...new Set(v.tools.map((t) => t.namespace))] : [];
  return (
    <div>
      <p><Link to="/probki">‹ Próbki</Link></p>
      <Header detail={data} version={v} />
      {!v && <p className="notice">Próbka jest znana w przebiegu, ale nie ma wyników (np. report: false w run.json).</p>}
      {v && <Checks version={v} />}
      <Metadata key={data.sample?.id ?? 0} detail={data} onSaved={reload} />
      {v && (
        <div className="card">
          <h2>Metryki wg etapu</h2>
          {namespaces.map((ns) => (
            <section key={ns}>
              <h3>{NAMESPACE_LABEL[ns] ?? ns}</h3>
              {v.tools.filter((t) => t.namespace === ns).map((t) => <ToolCard key={t.tool} tool={t} />)}
            </section>
          ))}
        </div>
      )}
      {v && <Typing version={v} />}
      {v && <Amr version={v} />}
      {v && v.abundances.length > 0 && (
        <div className="card">
          <h2>Skład gatunkowy (Bracken)</h2>
          <table><thead><tr><th>Gatunek</th><th className="num">taxid</th><th className="num">Odczyty</th><th className="num">%</th></tr></thead>
            <tbody>{v.abundances.map((a) => <tr key={a.ordinal}><td>{a.name}</td><td className="num">{a.taxid}</td><td className="num">{formatNumber(a.reads)}</td><td className="num">{formatNumber(a.pct)}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      {v && <Software version={v} />}
      <History id={id} onChange={reload} />
      {v && <Technical version={v} />}
    </div>
  );
}
