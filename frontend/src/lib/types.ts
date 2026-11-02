// Shapes of the qcdb API (backend/openapi.json).
export type Verdict = "PASS" | "WARN" | "FAIL";
export type Role = "admin" | "bioinformatician" | "viewer";
export type Scalar = number | string | boolean | null;

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface Me {
  id: number;
  username: string;
  role: Role;
  csrf_token: string;
}
export interface OwnerRef {
  id: number;
  full_name: string | null;
  erased: boolean;
}
export interface OrderRef {
  id: number;
  order_code: string;
  owner: OwnerRef | null;
}
export interface ResultItem {
  sample_run_id: number;
  run_code: string;
  run_date: string | null;
  sample_code: string;
  sample_id: number | null;
  version_no: number | null;
  n_versions: number;
  has_results: boolean;
  has_qc: boolean;
  has_report: boolean;
  verdict: Verdict | null;
  profile: string | null;
  species: string | null;
  mlst_st: string | null;
  serotype: string | null;
  n_amr_genes: number | null;
  thresholds_sha256: string | null;
  orders: OrderRef[];
  [column: string]: unknown;
}
export interface Check {
  ordinal: number;
  metric: string;
  label: string | null;
  value: Scalar;
  unit: string | null;
  rule: Record<string, number>;
  required: boolean;
  status: "PASS" | "WARN" | "FAIL" | "NA";
  reason: string | null;
}
export interface Metric {
  key: string;
  name: string;
  label: string;
  unit: string;
  value_type: string;
  value: Scalar;
  is_null: boolean;
}
export type ToolStatus = "ok" | "empty" | "skipped" | "failed" | "missing";
export interface Tool {
  tool: string;
  namespace: string;
  status: ToolStatus;
  messages: string[] | null;
  tool_version: string;
  database_version: string | null;
  parser_name: string;
  parser_version: string;
  metrics: Metric[];
  absent_metrics: string[];
}
export interface AmrHit {
  ordinal: number;
  symbol: string | null;
  name: string | null;
  type: string | null;
  subtype: string | null;
  class: string | null;
  subclass: string | null;
  method: string | null;
  pct_identity: number | null;
  pct_coverage: number | null;
  contig: string | null;
}
export interface Abundance {
  ordinal: number;
  name: string | null;
  taxid: number | null;
  reads: number | null;
  pct: number | null;
}
export interface Version {
  version_no: number;
  created_at: string;
  is_current: boolean;
  verdict: Verdict | null;
  has_qc: boolean;
  has_report: boolean;
  evaluator_version: string | null;
  report_generator_version: string | null;
  thresholds: { sha256: string; profile: string; read_length_profile: string | null; species: string | null; chain: string[] } | null;
  context: { expected_taxid: number | null; read_length: number | null; depth_basis: string | null } | null;
  checks: Check[];
  reasons: string[];
  advisory: string[];
  notes: string[];
  unused_inputs: string[];
  tools: Tool[];
  typing: {
    mlst_scheme: string | null;
    mlst_sequence_type: string | null;
    mlst_alleles: Record<string, string> | null;
    seqsero2_serotype: string | null;
    seqsero2_antigenic_profile: string | null;
    ectyper_serotype: string | null;
    ectyper_qc_flag: string | null;
    report_species: Record<string, unknown> | null;
  };
  amr_hits: AmrHit[];
  abundances: Abundance[];
  software: { pipeline: string | null; pipeline_version: string | null; nextflow_version: string | null; groups: { stage: string; tools: { tool: string; label: string; versions: string[]; databases: string[] }[] }[]; other: { tool: string; label: string; versions: string[]; databases: string[] }[] } | null;
  technical?: {
    thresholds_file: string | null;
    meta: Record<string, string> | null;
    load_warnings: string[];
    load_batch_id: number;
    load_invoked_by: string;
    load_source_dir: string;
    documents: { kind: string; tool: string | null; file_name: string; sha256: string }[];
    tools: Record<string, { inputs: unknown; data: unknown }>;
  };
}
export interface ResultDetail {
  sample_run_id: number;
  sample_code: string;
  run: { run_code: string; run_date: string | null };
  sample: { id: number; sample_code: string; metadata: Record<string, unknown> } | null;
  orders: OrderRef[];
  n_versions: number;
  version: Version | null;
}
export interface VersionSummary {
  version_no: number;
  created_at: string;
  is_current: boolean;
  verdict: Verdict | null;
  thresholds_sha256: string | null;
  profile: string | null;
  check_changes: { metric: string; old_status: string | null; new_status: string | null }[];
}
export interface RunOut {
  run_code: string;
  run_date: string | null;
  run_date_source: string | null;
  n_samples: number;
  n_pass: number;
  n_warn: number;
  n_fail: number;
  n_missing: number;
}
export interface RunDetail extends RunOut {
  run_document_summary: Record<string, number> | null;
  summary_matches_run_document: boolean | null;
}
export interface Outlier {
  column: string;
  label: string;
  unit: string | null;
  sample_run_id: number;
  sample_code: string;
  value: number;
  low_fence: number;
  high_fence: number;
  direction: "low" | "high";
}
export interface MetricDefinition {
  key: string;
  source: "dictionary" | "check";
  tool: string | null;
  namespace: string | null;
  unit: string | null;
  value_type: string;
  numeric: boolean;
  label: string;
  label_en: string | null;
  description: string | null;
}
export interface TrendPoint {
  sample_run_id: number;
  sample_code: string;
  run_code: string;
  run_date: string;
  value: number;
  verdict: Verdict | null;
  species: string | null;
  profile: string | null;
  thresholds_sha256: string | null;
}
export interface Trend {
  metric: string;
  label: string;
  unit: string | null;
  points: TrendPoint[];
  groups: { key: string | null; n: number; min: number; q1: number; median: number; q3: number; max: number }[];
  group_by: string;
  threshold_changes: { run_date: string; run_code: string; previous_sha256: string; sha256: string }[];
  excluded_without_date: number;
}
export interface Owner {
  id: number;
  full_name: string | null;
  email?: string | null;
  erased: boolean;
  erased_at: string | null;
  n_orders: number;
}
export interface Order {
  id: number;
  order_code: string;
  owner: OwnerRef | null;
  n_samples: number;
  meta?: Record<string, string> | null;
  samples?: { id: number; sample_code: string }[];
}
export interface SampleField {
  id: number;
  key: string;
  label: string;
  data_type: "text" | "number" | "date" | "choice";
  choices: string[] | null;
  required: boolean;
  ordinal: number;
  is_active: boolean;
}
export interface SampleOut {
  id: number;
  sample_code: string;
  metadata: Record<string, unknown>;
  missing_required: string[];
  orders: OrderRef[];
  results: { sample_run_id: number; run_code: string; run_date: string | null; verdict: Verdict | null; has_results: boolean }[];
}
export interface User {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  locked: boolean;
  last_login_at: string | null;
}
