import { demoKey } from "./demoKey";

export const DEMO = import.meta.env.MODE === "demo";
const BASE = import.meta.env.BASE_URL;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

function detail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d))
      return d
        .map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`)
        .join("; ");
  }
  return `HTTP ${status}`;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const url = `/api/v1${path}`;
  if (DEMO) {
    if (method !== "GET") throw new ApiError(403, "Wersja demonstracyjna: tylko odczyt");
    const response = await fetch(`${BASE}demo/${demoKey(url)}.json`);
    if (!response.ok) throw new ApiError(404, "Ten widok nie jest dostępny w wersji demonstracyjnej");
    return (await response.json()) as T;
  }
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(url, {
    method,
    headers,
    credentials: "same-origin",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, detail(body, response.status));
  return body as T;
}

export function csvUrl(path: string): string {
  return `/api/v1${path}`;
}

export function query(params: Record<string, string | string[] | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    for (const v of Array.isArray(value) ? value : [value]) q.append(key, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
