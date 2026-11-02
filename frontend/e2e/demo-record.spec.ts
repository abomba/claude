// Records the API responses the dashboard makes while visiting every view, for the static
// read-only demo on GitHub Pages. Runs only with QCDB_DEMO_OUT=<directory>.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { demoKey } from "../src/lib/demoKey";
import { login } from "./helpers";

const out = process.env.QCDB_DEMO_OUT;
test.skip(!out, "set QCDB_DEMO_OUT to record the demo data");

function record(page: Page, dir: string): () => number {
  let count = 0;
  mkdirSync(dir, { recursive: true });
  page.on("response", async (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/v1/") || response.request().method() !== "GET") return;
    if (!response.ok() || !(response.headers()["content-type"] ?? "").includes("json")) return;
    const key = demoKey(url.pathname + url.search);
    writeFileSync(`${dir}/${key}.json`, await response.text());
    count++;
  });
  return () => count;
}

async function visit(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

test("record demo data", async ({ page }) => {
  test.setTimeout(600_000);
  const recorded = record(page, out!);
  await login(page, "bioinformatyk");
  const api = async (path: string) => (await page.request.get(`/api/v1${path}`)).json();

  await visit(page, "/probki");
  for (const q of ["verdict=FAIL", "verdict=WARN", "verdict=none", "verdict=PASS", "amr_gene=blaTEM-1",
    "species=Salmonella+enterica", "species=Escherichia+coli", "sort=raw_reads", "sort=-raw_reads",
    "sort=sample_code", "sort=verdict", "sort=-contamination"]) {
    await visit(page, `/probki?${q}`);
  }
  for (const run of (await api("/runs?page_size=500")).items) {
    await visit(page, `/probki?run=${encodeURIComponent(run.run_code)}`);
  }
  for (const owner of (await api("/owners?page_size=500")).items) {
    await visit(page, `/probki?owner_id=${owner.id}`);
    await visit(page, `/zleceniodawcy/${owner.id}`);
  }
  for (const order of (await api("/orders?page_size=500")).items) {
    await visit(page, `/probki?order_id=${order.id}`);
    await visit(page, `/zlecenia/${order.id}`);
  }
  for (const r of (await api("/results?page_size=500")).items) {
    await visit(page, `/wyniki/${r.sample_run_id}`);
    for (const v of await api(`/results/${r.sample_run_id}/versions`)) {
      await visit(page, `/wyniki/${r.sample_run_id}?wersja=${v.version_no}`);
    }
  }
  await visit(page, "/przebiegi");
  for (const run of (await api("/runs?page_size=500")).items) {
    await visit(page, `/przebiegi/${encodeURIComponent(run.run_code)}`);
  }
  await visit(page, "/zleceniodawcy");
  await visit(page, "/zlecenia");
  await visit(page, "/trendy");
  for (const m of await api("/metrics")) {
    if (!m.numeric) continue;
    for (const g of ["species", "run", "profile"]) await visit(page, `/trendy?metric=${m.key}&group_by=${g}`);
  }
  expect(recorded()).toBeGreaterThan(100);
  writeFileSync(`${out}/README.txt`, "Recorded qcdb API responses (fictional fixture data) for the static demo.\n");
});
