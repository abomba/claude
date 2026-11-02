import type { Role, ToolStatus, Verdict } from "./types";

// Display texts only; stored values stay exactly as documented (PASS, ok, ...).
export const VERDICT_LABEL: Record<Verdict, string> = {
  PASS: "PASS – zaliczona",
  WARN: "WARN – ostrzeżenie",
  FAIL: "FAIL – niezaliczona",
};
export const NO_VERDICT = "brak wyniku";
export const CHECK_STATUS_LABEL: Record<string, string> = {
  PASS: "PASS",
  WARN: "WARN",
  FAIL: "FAIL",
  NA: "brak danych (nie wpływa na werdykt)",
};
export const TOOL_STATUS_LABEL: Record<ToolStatus, string> = {
  ok: "OK",
  empty: "brak wyników narzędzia",
  skipped: "pominięto",
  failed: "błąd",
  missing: "brak dokumentu",
};
export const NAMESPACE_LABEL: Record<string, string> = {
  input: "Dane wejściowe",
  demux: "Demultipleksacja",
  reads: "Odczyty",
  composition: "Skład taksonomiczny",
  species: "Gatunek",
  assembly: "Składanie genomu",
  characterisation: "Charakterystyka",
};
export const ROLE_LABEL: Record<Role, string> = {
  admin: "administrator",
  bioinformatician: "bioinformatyk",
  viewer: "podgląd",
};
export const RULE_LABEL: Record<string, string> = {
  min: "min",
  max: "max",
  warn_min: "warn_min",
  warn_max: "warn_max",
  expected_taxid: "oczekiwany taxid",
};

// Summary columns of the run document (D3) with units; reads are pairs × 2.
export const SUMMARY_COLUMNS: { id: string; label: string; unit: string | null; scale?: "kb" | "Mb" }[] = [
  { id: "raw_reads", label: "Odczyty (surowe)", unit: "reads" },
  { id: "raw_bases", label: "Zasady (surowe)", unit: "bp", scale: "Mb" },
  { id: "raw_q30", label: "Q30 (surowe)", unit: "percent" },
  { id: "raw_read_length", label: "Długość odczytu", unit: "bp" },
  { id: "reads", label: "Odczyty po QC", unit: "reads" },
  { id: "bases", label: "Zasady po QC", unit: "bp", scale: "Mb" },
  { id: "q30", label: "Q30 po QC", unit: "percent" },
  { id: "trimmed_read_length", label: "Długość po QC", unit: "bp" },
  { id: "pct_reads_passed", label: "% odczytów po filtrze", unit: "percent" },
  { id: "n_contigs", label: "Kontigi", unit: "contigs" },
  { id: "assembly_length", label: "Długość złożenia", unit: "bp", scale: "Mb" },
  { id: "n50", label: "N50", unit: "bp", scale: "kb" },
  { id: "gc", label: "GC", unit: "percent" },
  { id: "depth", label: "Pokrycie", unit: "x" },
  { id: "completeness", label: "Kompletność", unit: "percent" },
  { id: "contamination", label: "Zanieczyszczenie", unit: "percent" },
];

const UNIT_LABEL: Record<string, string> = { percent: "%", reads: "odczyty", pairs: "pary odczytów" };
export function unitLabel(unit: string | null | undefined, scale?: string): string {
  if (!unit) return "";
  if (scale) return scale === "Mb" ? "Mb" : "kb";
  return UNIT_LABEL[unit] ?? unit;
}

const nf = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 4 });
export function formatNumber(value: unknown, scale?: string): string {
  if (value === null || value === undefined) return "–";
  if (typeof value !== "number") return String(value);
  if (scale === "Mb") return nf.format(Math.round(value / 1e4) / 100);
  if (scale === "kb") return nf.format(Math.round(value / 10) / 100);
  return nf.format(value);
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "boolean") return value ? "tak" : "nie";
  return formatNumber(value);
}

export function formatRule(rule: Record<string, number>): string {
  return Object.entries(rule)
    .map(([k, v]) => `${RULE_LABEL[k] ?? k} ${formatNumber(v)}`)
    .join(" · ");
}

export function formatDateTime(value: string | null): string {
  if (!value) return "–";
  return new Date(value).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}
