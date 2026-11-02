import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { PASSWORD } from "../playwright.config";

export const SHOTS = "../docs/screenshots";

export async function login(page: Page, username: "admin" | "bioinformatyk" | "przegladajacy"): Promise<void> {
  await page.goto("/probki");
  await page.getByLabel("Użytkownik").fill(username);
  await page.getByLabel("Hasło").fill(PASSWORD);
  await page.getByRole("button", { name: "Zaloguj" }).click();
  await expect(page.getByRole("heading", { name: "Próbki" })).toBeVisible();
}

export function fixture(path: string): any {
  return JSON.parse(readFileSync(`../fixtures/${path}`, "utf-8"));
}

export function rows(page: Page) {
  return page.getByTestId("results-table").locator("tbody tr");
}

export async function clear(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Wyczyść" }).click();
  await expect(page).toHaveURL(/\/probki$/);
  await expect(rows(page)).toHaveCount(6); // re-rendered with the cleared filters
}
