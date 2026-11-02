import { expect, test } from "@playwright/test";
import { clear, fixture, login, rows, SHOTS } from "./helpers";

test("filtering the sample table", async ({ page }) => {
  await login(page, "przegladajacy");
  await expect(rows(page)).toHaveCount(6);
  await page.screenshot({ path: `${SHOTS}/01-probki.png`, fullPage: true });

  await page.getByLabel("FAIL – niezaliczona").check();
  await page.getByRole("button", { name: "Filtruj" }).click();
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toHaveAttribute("data-sample", "260630_5158");
  await expect(page).toHaveURL(/verdict=FAIL/);

  await clear(page);
  await page.getByLabel("brak wyniku").check();
  await page.getByRole("button", { name: "Filtruj" }).click();
  await expect(rows(page)).toHaveCount(2);

  await clear(page);
  await page.locator("select[name=run]").selectOption("RUN_2607");
  await page.getByRole("button", { name: "Filtruj" }).click();
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toHaveAttribute("data-run", "RUN_2607");

  await clear(page);
  await page.locator("input[name=species]").fill("Salmonella enterica");
  await page.locator("input[name=date_from]").fill("2026-06-01");
  await page.locator("input[name=date_to]").fill("2026-06-30");
  await page.getByRole("button", { name: "Filtruj" }).click();
  await expect(rows(page)).toHaveCount(2);

  await clear(page);
  await page.locator("input[name=amr_gene]").fill("blaTEM-1");
  await page.getByRole("button", { name: "Filtruj" }).click();
  await expect(rows(page)).toHaveCount(1);
  const csv = page.getByRole("link", { name: "Eksport CSV" });
  await expect(csv).toHaveAttribute("href", /export\.csv\?amr_gene=blaTEM-1/);
  await page.screenshot({ path: `${SHOTS}/02-probki-filtr-amr.png`, fullPage: true });

  await clear(page);
  await page.getByRole("columnheader", { name: /Odczyty \(surowe\)/ }).click();
  await expect(page).toHaveURL(/sort=raw_reads/);
  await expect(rows(page).first()).toHaveAttribute("data-sample", "260630_5160");
});

for (const sample of ["260630_5156", "260630_5157", "260630_5158"]) {
  test(`sample detail verdict matches qc.json (${sample})`, async ({ page }) => {
    const qc = fixture(`RUN_2606/${sample}.qc.json`);
    await login(page, "przegladajacy");
    await page.locator(`tr[data-sample="${sample}"][data-run="RUN_2606"] a`).first().click();
    await expect(page.getByTestId("sample-code")).toHaveText(sample);
    await expect(page.getByTestId("verdict").locator(".badge")).toHaveAttribute("data-verdict", qc.verdict);
    await expect(page.getByTestId("thresholds-sha")).toHaveAttribute("title", qc.thresholds.sha256);
    const checkRows = page.getByTestId("checks").locator("tbody tr");
    await expect(checkRows).toHaveCount(qc.checks.length);
    for (const [i, check] of qc.checks.entries()) {
      const row = checkRows.nth(i);
      await expect(row).toHaveAttribute("data-metric", check.metric);
      await expect(row.locator(".badge")).toHaveAttribute("data-status", check.status);
      if (check.reason) await expect(row).toContainText(check.reason);
    }
    // viewer: no technical section, no server paths
    await expect(page.getByText("Dane techniczne")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("/mnt/ngs_data");
    if (sample === "260630_5157") {
      await expect(page.locator('[data-tool="mlst"] [data-metric="mlst.sequence_type"]')).toContainText("brak wartości (null)");
      await expect(page.locator('[data-tool="kraken2"] .badge')).toHaveText("brak dokumentu");
      await page.screenshot({ path: `${SHOTS}/03-szczegoly-warn.png`, fullPage: true });
    }
    if (sample === "260630_5156") {
      await expect(page.getByTestId("mlst")).toContainText("ST 19");
      await expect(page.getByTestId("amr").locator("tbody tr")).toHaveCount(7);
    }
  });
}

test("technical data only for bioinformatician", async ({ page }) => {
  await login(page, "bioinformatyk");
  await page.locator('tr[data-sample="260630_5156"][data-run="RUN_2606"] a').first().click();
  await page.getByText("Dane techniczne").click();
  await expect(page.locator("details").first()).toContainText("qc_thresholds.yml");
});

test("assigning an owner to an order", async ({ page }) => {
  const name = `Ewa Testowa ${Date.now()}`;
  await login(page, "bioinformatyk");
  await page.getByRole("link", { name: "Zleceniodawcy" }).click();
  await page.locator("input[name=full_name]").fill(name);
  await page.locator("input[name=email]").fill("ewa.testowa@example.org");
  await page.getByRole("button", { name: "Dodaj zleceniodawcę" }).click();
  await expect(page.getByTestId("owners")).toContainText(name);
  await expect(page.getByTestId("owners")).toContainText("ewa.testowa@example.org");

  await page.getByRole("link", { name: "Zlecenia" }).click();
  await page.getByRole("link", { name: "ZL/2026/001" }).click();
  await page.locator("select[name=owner]").selectOption({ label: name });
  await expect(page.getByTestId("order-owner")).toHaveText(name);

  await page.locator("input[name=sample_search]").fill("5158");
  await page.getByTestId("sample-candidates").getByRole("button", { name: "Przypisz" }).click();
  await expect(page.getByTestId("order-samples")).toContainText("260630_5158");
  await page.screenshot({ path: `${SHOTS}/04-zlecenie-przypisanie.png`, fullPage: true });

  await page.getByRole("link", { name: "Próbki" }).click();
  await page.locator("select[name=owner_id]").selectOption({ label: name });
  await page.getByRole("button", { name: "Filtruj" }).click();
  await expect(rows(page)).toHaveCount(4); // 5156 in two runs, 5157, 5158
  await expect(rows(page).first()).toContainText(name);
});

test("viewer sees owners without e-mail and cannot edit", async ({ page }) => {
  await login(page, "przegladajacy");
  await page.getByRole("link", { name: "Zleceniodawcy" }).click();
  await expect(page.getByTestId("owners")).not.toContainText("@");
  await expect(page.getByRole("button", { name: "Dodaj zleceniodawcę" })).toHaveCount(0);
});

test("metric trend with threshold change", async ({ page }) => {
  await login(page, "przegladajacy");
  await page.getByRole("link", { name: "Trendy" }).click();
  await page.locator("select[name=metric]").selectOption("fastp.pct_q30_after_filter");
  await expect(page.getByTestId("trend-summary")).toContainText("5 wyników");
  await expect(page.getByTestId("trend-summary")).toContainText("zmian progów (thresholds.sha256): 1");
  await expect(page.getByTestId("trend-chart").locator("svg")).toContainText("zmiana progów");
  await page.locator("select[name=group_by]").selectOption("run");
  await expect(page.getByTestId("box-chart").locator("svg")).toContainText("RUN_2607 (n=1)");
  await page.screenshot({ path: `${SHOTS}/05-trendy.png`, fullPage: true });
});

test("run page summary", async ({ page }) => {
  await login(page, "przegladajacy");
  await page.getByRole("link", { name: "Przebiegi" }).click();
  await page.getByTestId("runs").getByRole("link", { name: "RUN_2606" }).click();
  const tiles = page.getByTestId("run-summary");
  await expect(tiles).toContainText("PASS – zaliczona1");
  await expect(tiles).toContainText("brak wyniku2");
  await expect(page.getByText("Zgodne z podsumowaniem w run.json.")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-przebieg.png`, fullPage: true });
});
