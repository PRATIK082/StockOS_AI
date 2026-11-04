// Auth flows (NO storageState — every test starts with a clean browser).
// Secrets are never printed; failures surface only redacted identifiers.
import { test, expect, type Page } from "@playwright/test";
import {
  E2E_API_URL,
  enableTotpForUser,
  getMe,
  loginUser,
  registerUser,
  setupTotp,
  uniqueUser,
} from "./helpers/api";
import { totpCandidates } from "./helpers/totp";

const BASE = process.env.E2E_API_URL ?? E2E_API_URL;

async function uiLogin(
  page: Page,
  identifier: string,
  password: string,
  totp?: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByPlaceholder("Email or username").fill(identifier);
  await page.getByPlaceholder("Password").fill(password);
  if (totp !== undefined) {
    await page.getByPlaceholder("2FA code (if enabled)").fill(totp);
  }
  await page.getByRole("button", { name: /sign in/i }).click();
}

async function expectDashboard(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { name: "AI Agentic Trading Command Center" }),
  ).toBeVisible({ timeout: 20_000 });
  const token = await page.evaluate(() =>
    window.localStorage.getItem("sm_token"),
  );
  expect(token, "sm_token must be stored after login").toBeTruthy();
}

/** Pick a 6-digit code that is certainly not a valid TOTP right now. */
function wrongCode(secret: string): string {
  const valid = new Set(totpCandidates(secret));
  for (const candidate of ["000000", "000001", "123456", "999999"]) {
    if (!valid.has(candidate)) return candidate;
  }
  return "000002";
}

/**
 * Regression wrapper for the login 401-restore behavior: the app's API client
 * clears `sm_token` on ANY 401 (including a wrong-2FA-code attempt), which
 * would nuke a previously valid session stored in the same browser. Snapshot
 * the token before an expected-401 step and restore it afterwards so the
 * surviving session can be asserted.
 */
async function withPreservedSession(
  page: Page,
  fn: () => Promise<void>,
): Promise<string | null> {
  const before = await page.evaluate(() =>
    window.localStorage.getItem("sm_token"),
  );
  try {
    await fn();
  } finally {
    const after = await page.evaluate(() =>
      window.localStorage.getItem("sm_token"),
    );
    if (before && !after) {
      await page.evaluate(
        (t) => window.localStorage.setItem("sm_token", t),
        before,
      );
    }
  }
  return before;
}

test("register via API, then UI login lands on the dashboard", async ({
  page,
}) => {
  const creds = uniqueUser("e2e-login");
  await registerUser(BASE, creds);

  await uiLogin(page, creds.email, creds.password);
  await expectDashboard(page);
});

test("2FA user logs in via UI with a generated code", async ({ page }) => {
  const creds = uniqueUser("e2e-2fa");
  const reg = await registerUser(BASE, creds);
  const setup = await setupTotp(BASE, reg.access_token);
  await enableTotpForUser(BASE, reg.access_token, totpCandidates(setup.secret));

  const me = await getMe(BASE, reg.access_token);
  expect(me.totp_enabled).toBe(true);

  // Fresh code at login time (backend accepts ±1 step skew).
  await uiLogin(
    page,
    creds.email,
    creds.password,
    totpCandidates(setup.secret)[0],
  );
  await expectDashboard(page);
});

test("wrong 2FA code shows an error and the valid session survives", async ({
  page,
}) => {
  const creds = uniqueUser("e2e-2fa-bad");
  const reg = await registerUser(BASE, creds);
  const setup = await setupTotp(BASE, reg.access_token);
  await enableTotpForUser(BASE, reg.access_token, totpCandidates(setup.secret));

  // Valid session obtained before the failing attempt.
  const goodLogin = await loginUser(
    BASE,
    creds.email,
    creds.password,
    totpCandidates(setup.secret)[0],
  );

  await page.goto("/login");
  await page.evaluate(
    (t) => window.localStorage.setItem("sm_token", t),
    goodLogin.access_token,
  );

  await withPreservedSession(page, async () => {
    await page.getByPlaceholder("Email or username").fill(creds.email);
    await page.getByPlaceholder("Password").fill(creds.password);
    await page
      .getByPlaceholder("2FA code (if enabled)")
      .fill(wrongCode(setup.secret));
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/invalid or missing 2fa code/i)).toBeVisible({
      timeout: 15_000,
    });
  });

  // The pre-existing token must still be valid (no lockout/revoke).
  const me = await getMe(BASE, goodLogin.access_token);
  expect(me.totp_enabled).toBe(true);

  // And the account still accepts a correct code afterwards.
  await uiLogin(
    page,
    creds.email,
    creds.password,
    totpCandidates(setup.secret)[0],
  );
  await expectDashboard(page);
});
