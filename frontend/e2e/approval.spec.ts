// Approval flow (uses the storageState session from global-setup).
// Seeds a pending item via API, drives Approve → Execute in the UI, then
// confirms `executed` via API. No live market data is required: the paper
// broker falls back to a simulated quote when market data is unreachable.
import fs from "fs";
import path from "path";
import { test, expect } from "@playwright/test";
import {
  E2E_API_URL,
  getActionItems,
  getOrders,
  seedPendingItem,
} from "./helpers/api";

const BASE = process.env.E2E_API_URL ?? E2E_API_URL;

interface E2eStoredCreds {
  email: string;
  username: string;
  password: string;
  token: string;
}

function loadSharedCreds(): E2eStoredCreds {
  const file = path.join(__dirname, ".auth", "creds.json");
  const raw = fs.readFileSync(file, "utf8");
  return JSON.parse(raw) as E2eStoredCreds;
}

test("pending item → approve → execute → executed", async ({ page }) => {
  const { token } = loadSharedCreds();

  // --- Seed ---------------------------------------------------------------
  const seeded = await seedPendingItem(BASE, token);
  expect(seeded.status).toBe("pending_approval");

  // --- Pending tab shows it -------------------------------------------------
  await page.goto("/action-center");
  await page.getByRole("tab", { name: /pending/i }).click();
  const row = page.locator("li", { hasText: "NSE:RELIANCE" }).first();
  await expect(row).toBeVisible({ timeout: 20_000 });

  // --- Approve ---------------------------------------------------------------
  await row.getByRole("button", { name: /^approve$/i }).click();
  await expect(page.getByText(/approved.*execute/i).first()).toBeVisible({
    timeout: 20_000,
  });

  // --- Execute -----------------------------------------------------------------
  await page.getByRole("tab", { name: /approved/i }).click();
  const approvedRow = page.locator("li", { hasText: "NSE:RELIANCE" }).first();
  await expect(approvedRow).toBeVisible({ timeout: 20_000 });
  await approvedRow.getByRole("button", { name: /^execute$/i }).click();
  await expect(page.getByText(/order executed/i).first()).toBeVisible({
    timeout: 30_000,
  });

  // --- API confirmation ---------------------------------------------------------
  const executed = await getActionItems(BASE, token, "executed");
  expect(
    executed.some((item) => item.id === seeded.id),
    "seeded item must appear under status_filter=executed",
  ).toBe(true);

  const orders = (await getOrders(BASE, token)) as Array<{
    symbol?: string;
    status?: string;
  }>;
  expect(
    orders.some((o) => o.symbol === "NSE:RELIANCE" && o.status === "filled"),
    "executed item must produce a filled paper order",
  ).toBe(true);
});
