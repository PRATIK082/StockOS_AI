// S1 E2E harness — Playwright config.
//
// READ THIS BEFORE RUNNING:
// - The backend entry below uses `reuseExistingServer: false` and binds :8000
//   with its own temp SQLite DB. If another backend (e.g. `run.py` / dev) is
//   already listening on :8000, uvicorn will fail to bind and this run will
//   ERROR OUT instead of silently testing the wrong server. That is intentional.
//   Fix: stop the other backend first — run `kill-all.bat` from the repo root,
//   then re-run `npx playwright test` from `frontend/`.
// - NEVER kill :3000 automatically (another agent may own the frontend dev
//   server); the frontend entry uses `reuseExistingServer: true` for that reason.
// - Safety: `e2e/global-setup.ts` refuses to run unless the backend reports
//   execution_mode != LIVE_ENABLED and broker == paper.

import { defineConfig } from "@playwright/test";
import fs from "fs";
import path from "path";

const repoRoot = path.resolve(__dirname, "..");
const backendDir = path.join(repoRoot, "backend");
const pythonExe = path.join(backendDir, ".venv", "Scripts", "python.exe");

// Temp E2E DB lives under frontend/test-results (gitignored). The directory must
// exist BEFORE the backend webServer starts (SQLite won't create parent dirs,
// and webServers boot before global-setup), so create it at config load time.
const testResultsDir = path.resolve(__dirname, "test-results");
fs.mkdirSync(testResultsDir, { recursive: true });
const e2eDbPath = path.join(testResultsDir, "e2e.db").replace(/\\/g, "/");

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  retries: 0, // fail loudly — never hide flakiness
  workers: 1, // serial: all specs share one backend DB
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "auth",
      testMatch: /auth\.spec\.ts/,
    },
    {
      name: "approval",
      testMatch: /approval\.spec\.ts/,
      use: {
        storageState: "./e2e/.auth/user.json",
      },
    },
  ],
  webServer: [
    {
      // Fresh E2E backend on :8000 with an absolute-path temp SQLite DB.
      // NOTE: engine binds STOCKOS_DATABASE_URL at import, so a relative path
      // would resolve against the backend CWD — always use the absolute path.
      command: `"${pythonExe}" -m uvicorn app.main:app --port 8000`,
      cwd: backendDir,
      url: "http://localhost:8000/healthz",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        STOCKOS_DATABASE_URL: `sqlite+aiosqlite:///${e2eDbPath}`,
        STOCKOS_EXECUTION_MODE: "REQUIRE_APPROVAL",
        // Canonical pydantic name is STOCKOS_SELECTED_EXECUTION_BROKER; also set
        // the documented STOCKOS_EXECUTION_BROKER alias in case config gains it.
        STOCKOS_EXECUTION_BROKER: "paper",
        STOCKOS_SELECTED_EXECUTION_BROKER: "paper",
        STOCKOS_RATE_LIMIT_AUTH_PER_MINUTE: "100",
        STOCKOS_IP_BAN_THRESHOLD: "100",
      },
    },
    {
      command: "npm.cmd run dev -- -p 3000",
      url: "http://localhost:3000",
      timeout: 180_000,
      reuseExistingServer: true,
    },
  ],
});
