// Global setup: runs AFTER webServers are up. Registers one shared user and
// writes Playwright storageState (localStorage `sm_token` for the frontend
// origin) plus the API creds the approval spec needs for seeding.
import fs from "fs";
import path from "path";
import type { FullConfig } from "@playwright/test";
import {
  E2E_API_URL,
  getMe,
  getSettings,
  registerUser,
  uniqueUser,
} from "./helpers/api";

const FRONTEND_ORIGIN = "http://localhost:3000";

async function globalSetup(config: FullConfig): Promise<void> {
  const base = process.env.E2E_API_URL ?? E2E_API_URL;

  // --- Safety gate: never run E2E against a live broker --------------------
  const settings = await getSettings(base);
  if (settings.execution_mode === "LIVE_ENABLED") {
    throw new Error(
      `E2E REFUSED: backend execution_mode is LIVE_ENABLED (base=${base}). ` +
        `Run E2E only against the paper backend started by playwright.config.ts.`,
    );
  }
  if ((settings.selected_execution_broker ?? "").toLowerCase() !== "paper") {
    throw new Error(
      `E2E REFUSED: backend broker is "${settings.selected_execution_broker}", ` +
        `expected "paper" (base=${base}).`,
    );
  }

  // --- Shared user -----------------------------------------------------------
  const creds = uniqueUser("e2e-shared");
  const reg = await registerUser(base, creds);
  const me = await getMe(base, reg.access_token);
  if (!me || typeof me.totp_enabled !== "boolean") {
    throw new Error("E2E setup: /auth/me did not return a valid session");
  }

  const authDir = path.join(__dirname, ".auth");
  fs.mkdirSync(authDir, { recursive: true });

  // storageState: seed localStorage token for the frontend origin. The app's
  // baseURL is FRONTEND_ORIGIN; derive from config when it differs.
  const configuredBase = config.projects?.[0]?.use?.baseURL;
  const origin =
    typeof configuredBase === "string" && configuredBase.startsWith("http")
      ? configuredBase.replace(/\/$/, "")
      : FRONTEND_ORIGIN;

  const storageState = {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [{ name: "sm_token", value: reg.access_token }],
      },
    ],
  };
  fs.writeFileSync(
    path.join(authDir, "user.json"),
    JSON.stringify(storageState),
  );
  // API creds for specs that seed via the backend (never committed: .gitignored).
  fs.writeFileSync(
    path.join(authDir, "creds.json"),
    JSON.stringify({ ...creds, token: reg.access_token }),
  );
}

export default globalSetup;
