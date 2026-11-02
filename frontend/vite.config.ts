import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API runs separately; in development and preview /api is proxied to it.
const api = process.env.QCDB_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // GitHub Pages serves the demo below /<repository>/.
  base: mode === "demo" ? (process.env.QCDB_DEMO_BASE ?? "/claude/") : "/",
  build: { outDir: mode === "demo" ? "dist-demo" : "dist", sourcemap: false },
  server: { proxy: { "/api": api } },
  preview: { proxy: { "/api": api } },
  test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
}));
