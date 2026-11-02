import type { ReactNode } from "react";
import type { ApiError } from "../lib/api";
import { CHECK_STATUS_LABEL, NO_VERDICT, TOOL_STATUS_LABEL, VERDICT_LABEL } from "../lib/i18n";
import type { ToolStatus, Verdict } from "../lib/types";

export function VerdictBadge({ verdict }: { verdict: Verdict | null | undefined }) {
  if (!verdict) return <span className="badge v-none" data-verdict="none">{NO_VERDICT}</span>;
  return (
    <span className={`badge v-${verdict}`} data-verdict={verdict}>
      {VERDICT_LABEL[verdict]}
    </span>
  );
}

export function CheckBadge({ status }: { status: string }) {
  return (
    <span className={`badge v-${status}`} data-status={status}>
      {CHECK_STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function ToolStatusBadge({ status }: { status: ToolStatus }) {
  return (
    <span className={`badge s-${status}`} data-status={status} title={status}>
      {TOOL_STATUS_LABEL[status]}
    </span>
  );
}

export function ErrorBox({ error }: { error: ApiError | Error | string | undefined | null }) {
  if (!error) return null;
  return <div className="error" role="alert">{typeof error === "string" ? error : error.message}</div>;
}

export function Loading({ show }: { show: boolean }) {
  return show ? <p className="muted">Wczytywanie…</p> : null;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
    </label>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager">
      <button className="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ‹ Poprzednia
      </button>
      <span>
        Strona {page} z {pages} · {total} {total === 1 ? "wynik" : "wyników"}
      </span>
      <button className="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Następna ›
      </button>
    </div>
  );
}

export function SortHeader({ id, label, sort, onSort, className }: { id: string; label: ReactNode; sort: string; onSort: (s: string) => void; className?: string }) {
  const active = sort === id ? "▲" : sort === `-${id}` ? "▼" : "";
  return (
    <th className={`sortable ${className ?? ""}`} onClick={() => onSort(sort === id ? `-${id}` : id)} aria-sort={active === "▲" ? "ascending" : active === "▼" ? "descending" : "none"}>
      {label} {active}
    </th>
  );
}
