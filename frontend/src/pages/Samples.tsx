import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ResultsTable, type Filters } from "../components/ResultsTable";
import { Field } from "../components/ui";
import { NO_VERDICT, VERDICT_LABEL } from "../lib/i18n";
import type { Order, Owner, Page, RunOut, Verdict } from "../lib/types";
import { useApi } from "../lib/useApi";

const TEXT_FILTERS = ["q", "species", "date_from", "date_to", "amr_gene", "amr_class", "composition_species", "composition_min_pct"] as const;
const SELECT_FILTERS = ["run", "owner_id", "order_id"] as const;

export function readFilters(params: URLSearchParams): Filters {
  const f: Filters = {};
  for (const k of [...TEXT_FILTERS, ...SELECT_FILTERS]) {
    const v = params.get(k);
    if (v) f[k] = v;
  }
  const verdicts = params.getAll("verdict");
  if (verdicts.length) f.verdict = verdicts;
  return f;
}

export function SamplesPage() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const [draft, setDraft] = useState<Filters>(filters);
  useEffect(() => setDraft(readFilters(params)), [params]);
  const runs = useApi<Page<RunOut>>("/runs?page_size=500");
  const owners = useApi<Page<Owner>>("/owners?page_size=500");
  const orders = useApi<Page<Order>>("/orders?page_size=500");
  const sort = params.get("sort") ?? "-run_date";
  const page = Number(params.get("page") ?? "1");

  const apply = (next: Filters, extra: Record<string, string> = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) {
      for (const x of Array.isArray(v) ? v : v ? [v] : []) p.append(k, x);
    }
    for (const [k, v] of Object.entries(extra)) p.set(k, v);
    setParams(p);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    apply(draft, { sort });
  };
  const set = (key: string, value: string) => setDraft({ ...draft, [key]: value || undefined });
  const verdicts = (draft.verdict as string[] | undefined) ?? [];
  const toggleVerdict = (v: string) =>
    setDraft({ ...draft, verdict: verdicts.includes(v) ? verdicts.filter((x) => x !== v) : [...verdicts, v] });

  return (
    <div>
      <h1>Próbki</h1>
      <form className="card" onSubmit={submit} data-testid="filters">
        <div className="row">
          <Field label="Szukaj (próbka, przebieg, zlecenie)">
            <input name="q" value={(draft.q as string) ?? ""} onChange={(e) => set("q", e.target.value)} />
          </Field>
          <Field label="Przebieg">
            <select name="run" value={(draft.run as string) ?? ""} onChange={(e) => set("run", e.target.value)}>
              <option value="">wszystkie</option>
              {runs.data?.items.map((r) => <option key={r.run_code} value={r.run_code}>{r.run_code}</option>)}
            </select>
          </Field>
          <Field label="Zleceniodawca">
            <select name="owner_id" value={(draft.owner_id as string) ?? ""} onChange={(e) => set("owner_id", e.target.value)}>
              <option value="">wszyscy</option>
              {owners.data?.items.map((o) => <option key={o.id} value={o.id}>{o.full_name ?? `Zleceniodawca #${o.id}`}</option>)}
            </select>
          </Field>
          <Field label="Zlecenie">
            <select name="order_id" value={(draft.order_id as string) ?? ""} onChange={(e) => set("order_id", e.target.value)}>
              <option value="">wszystkie</option>
              {orders.data?.items.map((o) => <option key={o.id} value={o.id}>{o.order_code}</option>)}
            </select>
          </Field>
          <Field label="Gatunek">
            <input name="species" value={(draft.species as string) ?? ""} onChange={(e) => set("species", e.target.value)} />
          </Field>
          <Field label="Data przebiegu od">
            <input name="date_from" type="date" value={(draft.date_from as string) ?? ""} onChange={(e) => set("date_from", e.target.value)} />
          </Field>
          <Field label="do">
            <input name="date_to" type="date" value={(draft.date_to as string) ?? ""} onChange={(e) => set("date_to", e.target.value)} />
          </Field>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <div className="field">
            Werdykt
            <div className="checks">
              {(["PASS", "WARN", "FAIL"] as Verdict[]).map((v) => (
                <label key={v}>
                  <input type="checkbox" name={`verdict-${v}`} checked={verdicts.includes(v)} onChange={() => toggleVerdict(v)} /> {VERDICT_LABEL[v]}
                </label>
              ))}
              <label>
                <input type="checkbox" name="verdict-none" checked={verdicts.includes("none")} onChange={() => toggleVerdict("none")} /> {NO_VERDICT}
              </label>
            </div>
          </div>
          <Field label="Gen AMR">
            <input name="amr_gene" value={(draft.amr_gene as string) ?? ""} onChange={(e) => set("amr_gene", e.target.value)} />
          </Field>
          <Field label="Klasa AMR">
            <input name="amr_class" value={(draft.amr_class as string) ?? ""} onChange={(e) => set("amr_class", e.target.value)} />
          </Field>
          <Field label="Gatunek w składzie (Bracken)">
            <input name="composition_species" value={(draft.composition_species as string) ?? ""} onChange={(e) => set("composition_species", e.target.value)} />
          </Field>
          <Field label="≥ %">
            <input name="composition_min_pct" type="number" min={0} max={100} step="0.1" style={{ minWidth: 70, width: 80 }}
              value={(draft.composition_min_pct as string) ?? ""} onChange={(e) => set("composition_min_pct", e.target.value)} />
          </Field>
          <button type="submit">Filtruj</button>
          <button type="button" className="secondary" onClick={() => { setDraft({}); apply({}); }}>
            Wyczyść
          </button>
        </div>
      </form>
      <ResultsTable
        filters={filters}
        sort={sort}
        page={page}
        onSort={(s) => apply(filters, { sort: s })}
        onPage={(p) => apply(filters, { sort, page: String(p) })}
      />
    </div>
  );
}
