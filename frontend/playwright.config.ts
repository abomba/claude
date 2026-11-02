import { defineConfig } from "@playwright/test";

// The e2e run uses the real API (uvicorn) on a database seeded from fixtures/ and the built
// frontend served by `vite preview`, which proxies /api to the API.
const python = process.env.QCDB_PYTHON ?? "../backend/.venv/bin/python";
const server = process.env.QCDB_E2E_SERVER ?? "postgresql://postgres@127.0.0.1:55432";
export const E2E_DB = `${server}/qcdb_e2e`;
export const PASSWORD = process.env.QCDB_SEED_PASSWORD ?? "e2e-password-123";
const env = { QCDB_DATABASE_URL: E2E_DB, QCDB_COOKIE_SECURE: "false", QCDB_SEED_PASSWORD: PASSWORD };

export default defineConfig({
  testDir: "e2e",
  workers: 1,
  fullyParallel: false,
  timeout: 30_000,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: "http://127.0.0.1:4173", locale: "pl-PL", viewport: { width: 1440, height: 900 } },
  webServer: [
    {
      command: `${python} -m uvicorn --factory qcdb.api.app:create_app --port 8011 --no-access-log`,
      url: "http://127.0.0.1:8011/api/v1/health",
      env,
      reuseExistingServer: false,
    },
    {
      command: "npx vite build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      env: { QCDB_API_URL: "http://127.0.0.1:8011" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
