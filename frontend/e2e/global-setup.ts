import { execFileSync } from "node:child_process";
import { E2E_DB, PASSWORD } from "../playwright.config";

export default function globalSetup(): void {
  execFileSync(process.env.QCDB_PYTHON ?? "../backend/.venv/bin/python", ["../backend/scripts/seed_fixtures.py", "--recreate"], {
    env: { ...process.env, QCDB_DATABASE_URL: E2E_DB, QCDB_SEED_PASSWORD: PASSWORD },
    stdio: "inherit",
  });
}
