import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Chart } from "../components/Chart";
import { ErrorBox, Field, Loading } from "../components/ui";
import { query } from "../lib/api";
import { NAMESPACE_LABEL, NO_VERDICT, unitLabel, VERDICT_LABEL } from "../lib/i18n";
import type { MetricDefinition, Trend, Verdict } from "../lib/types";
import { useApi } from "../lib/useApi";

const COLORS: Record<string, string> = { PASS: "#1d7a3e", WARN: "#c98a00", FAIL: "#b3261e", none: "#8a94a3" };
const GROUP_LABEL: Record<string, string> = { species: "gatunek", run: "przebieg", profile: "profil" };

export function TrendsPage() {
  const [params, setParams] = useSearchParams();
  const metric = params.get("metric") ?? "";
  const groupBy = params.get("group_by") ?? "species";
  const metrics = useApi<MetricDefinition[]>("/metrics");
  const filters = { metric, group_by: groupBy, date_from: params.get("date_from"), date_to: params.get("date_to"), species: params.get("species"), profile: params.get("profile") };
  const trend = useApi<Trend>(metric ? `/trends${query(filters)}` : null);
  const update = (key: string, value: string) => {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p);
  };
  const numeric = (metrics.data ?? []).filter((m) => m.numeric);
  const groups = new Map<string, MetricDefinition[]>();
  for (const m of numeric) {
    const g = m.source === "check" ? "Metryki kontroli QC (qceval)" : `${NAMESPACE_LABEL[m.namespace ?? ""] ?? m.namespace ?? "inne"} – ${m.tool}`;
    groups.set(g, [...(groups.get(g) ?? []), m]);
  }
  const t = trend.data;
  const scatter = useMemo(() => {
    if (!t) return null;
    const series = (["PASS", "WARN", "FAIL", "none"] as const).map((v) => ({
      name: v === "none" ? NO_VERDICT : VERDICT_LABEL[v as Verdict],
      type: "scatter",
      itemStyle: { color: COLORS[v] },
      symbol: v === "FAIL" ? "triangle" : v === "WARN" ? "diamond" : v === "none" ? "emptyCircle" : "circle",
      symbolSize: 10,
      data: t.points.filter((p) => (p.verdict ?? "none") === v).map((p) => ({ value: [p.run_date, p.value], name: `${p.sample_code} (${p.run_code})` })),
    }));
    const marks = t.threshold_changes.map((c) => ({
      xAxis: c.run_date,
      label: { formatter: `zmiana progów\n${c.previous_sha256.slice(0, 7)} → ${c.sha256.slice(0, 7)}`, color: "#1f5fae" },
      lineStyle: { color: "#1f5fae", type: "dashed", width: 2 },
    }));
    if (series[0]) Object.assign(series[0], { markLine: { symbol: "none", data: marks } });
    return {
      tooltip: { trigger: "item", formatter: (p: { name: string; value: [string, number] }) => `${p.name}<br/>${p.value[0]}: ${p.value[1]} ${unitLabel(t.unit)}` },
      legend: { top: 0 },
      grid: { left: 70, right: 30, top: 60, bottom: 40 },
      xAxis: { type: "time", name: "data przebiegu" },
      yAxis: { type: "value", name: `${t.label} [${unitLabel(t.unit)}]`, scale: true },
      series,
    };
  }, [t]);
  const box = useMemo(() => {
    if (!t) return null;
    return {
      tooltip: { trigger: "item" },
      grid: { left: 70, right: 30, top: 30, bottom: 60 },
      xAxis: { type: "category", data: t.groups.map((g) => `${g.key ?? "brak"} (n=${g.n})`) },
      yAxis: { type: "value", name: `${t.label} [${unitLabel(t.unit)}]`, scale: true },
      series: [{ type: "boxplot", itemStyle: { color: "#e6eef9", borderColor: "#1f5fae" }, data: t.groups.map((g) => [g.min, g.q1, g.median, g.q3, g.max]) }],
    };
  }, [t]);
  return (
    <div>
      <h1>Trendy</h1>
      <div className="card row">
        <Field label="Metryka">
          <select name="metric" value={metric} onChange={(e) => update("metric", e.target.value)} style={{ minWidth: 320 }}>
            <option value="">wybierz metrykę…</option>
            {[...groups.entries()].map(([g, ms]) => (
              <optgroup key={g} label={g}>
                {ms.map((m) => <option key={m.key} value={m.key}>{m.label} [{unitLabel(m.unit)}]</option>)}
              </optgroup>
            ))}
          </select>
        </Field>
        <Field label="Rozkład wg">
          <select name="group_by" value={groupBy} onChange={(e) => update("group_by", e.target.value)}>
            {Object.entries(GROUP_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Od"><input type="date" value={params.get("date_from") ?? ""} onChange={(e) => update("date_from", e.target.value)} /></Field>
        <Field label="Do"><input type="date" value={params.get("date_to") ?? ""} onChange={(e) => update("date_to", e.target.value)} /></Field>
        <Field label="Gatunek"><input defaultValue={params.get("species") ?? ""} onBlur={(e) => update("species", e.target.value)} /></Field>
        <Field label="Profil"><input defaultValue={params.get("profile") ?? ""} onBlur={(e) => update("profile", e.target.value)} /></Field>
      </div>
      <ErrorBox error={trend.error} />
      <Loading show={trend.loading} />
      {!metric && <p className="muted">Wybierz metrykę, aby zobaczyć jej wartości w czasie (tylko bieżące wersje wyników).</p>}
      {t && scatter && box && (
        <>
          <div className="card">
            <h2>{t.label} w czasie <span className="muted mono">{t.metric}</span></h2>
            <p className="muted" data-testid="trend-summary">
              {t.points.length} wyników · zmian progów (thresholds.sha256): {t.threshold_changes.length}
              {t.excluded_without_date > 0 && ` · pominięto ${t.excluded_without_date} wyników bez daty przebiegu`}
            </p>
            <Chart option={scatter} testId="trend-chart" />
          </div>
          <div className="card">
            <h2>Rozkład wg: {GROUP_LABEL[groupBy]}</h2>
            <Chart option={box} testId="box-chart" />
          </div>
        </>
      )}
    </div>
  );
}
