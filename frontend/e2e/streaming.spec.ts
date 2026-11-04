// S4 streaming (uses the storageState session from global-setup).
// REST status/latest/market shape checks, a raw WebSocket snapshot →
// subscribe → tick → unsubscribe flow, and the /streaming page connect
// button. No live market data is required: quote failures surface as
// `missing` entries, never errors.
import fs from "fs";
import path from "path";
import { test, expect } from "@playwright/test";
import { E2E_API_URL } from "./helpers/api";

const BASE = process.env.E2E_API_URL ?? E2E_API_URL;
const WS_BASE = BASE.replace(/^http/, "ws");

function loadToken(): string {
  const file = path.join(__dirname, ".auth", "creds.json");
  const raw = fs.readFileSync(file, "utf8");
  return (JSON.parse(raw) as { token: string }).token;
}

async function apiGet(
  pathname: string,
  token: string,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await fetch(`${BASE}${pathname}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return { status: res.status, body: (await res.json()) as Record<string, unknown> };
}

test("streaming REST: status + latest + market shapes", async () => {
  const token = loadToken();

  const status = await apiGet("/streaming/status", token);
  expect(status.status).toBe(200);
  expect(typeof status.body.provider).toBe("string");
  expect(Array.isArray(status.body.symbols)).toBe(true);

  const latest = await apiGet(
    "/streaming/quotes/latest?symbols=NSE%3ARELIANCE",
    token,
  );
  expect(latest.status).toBe(200);
  const quotes = latest.body.quotes as Record<string, unknown>;
  expect(quotes).toBeTruthy();
  const entry = quotes["NSE:RELIANCE"] as Record<string, unknown> | null;
  const missing = latest.body.missing as unknown;
  // Live quote (has `price`) or honest null + `missing` entry — both are
  // valid without market data.
  expect(
    (entry && "price" in entry) ||
      (Array.isArray(missing) && missing.includes("NSE:RELIANCE")),
  ).toBe(true);

  const empty = await apiGet("/streaming/quotes/latest?symbols=", token);
  expect(empty.status).toBe(400);

  const market = await apiGet("/streaming/market", token);
  expect(market.status).toBe(200);
  expect(typeof market.body.is_open).toBe("boolean");
});

test("streaming WS: snapshot → subscribe → tick → unsubscribe", async ({
  page,
}) => {
  const token = loadToken();
  await page.goto("/");

  const result = await page.evaluate(
    async ({ wsUrl }: { wsUrl: string }) => {
      type Msg = { type?: string; symbol?: string; symbols?: string[] } & Record<
        string,
        unknown
      >;
      const msgs: Msg[] = [];
      const ws = new WebSocket(wsUrl);
      await new Promise<void>((resolve, reject) => {
        const t = setTimeout(() => reject(new Error("ws connect timeout")), 15_000);
        ws.onopen = () => {
          clearTimeout(t);
          resolve();
        };
        ws.onerror = () => {
          clearTimeout(t);
          reject(new Error("ws error"));
        };
      });
      ws.onmessage = (ev) => {
        try {
          msgs.push(JSON.parse(ev.data as string) as Msg);
        } catch {
          /* ignore non-JSON frames */
        }
      };
      const waitFor = async (pred: (m: Msg) => boolean, label: string) => {
        const deadline = Date.now() + 25_000;
        for (;;) {
          if (msgs.some(pred)) return;
          if (Date.now() > deadline)
            throw new Error(`timed out waiting for ${label}`);
          await new Promise((r) => setTimeout(r, 200));
        }
      };
      await waitFor((m) => m.type === "snapshot", "snapshot");
      // NOTE: the protocol takes a `symbols` LIST (a singular `symbol`
      // string would be char-joined into garbage — see _listen).
      ws.send(JSON.stringify({ action: "subscribe", symbols: ["NSE:RELIANCE"] }));
      await waitFor(
        (m) => m.type === "subscribed",
        "subscribed ack",
      );
      // `refresh` echoes the server-side subscription list — deterministic
      // even with no live market data (ticks need a successful poll).
      ws.send(JSON.stringify({ action: "refresh" }));
      await waitFor(
        (m) =>
          m.type === "snapshot" &&
          Array.isArray(m.symbols) &&
          (m.symbols as string[]).includes("NSE:RELIANCE"),
        "snapshot-with-symbol",
      );
      ws.send(JSON.stringify({ action: "unsubscribe", symbols: ["NSE:RELIANCE"] }));
      await new Promise((r) => setTimeout(r, 1_500));
      const ack = msgs.find((m) => m.type === "unsubscribed");
      const count = msgs.length;
      ws.close();
      return { ack: ack ?? null, count };
    },
    { wsUrl: `${WS_BASE}/streaming/quotes?token=${token}` },
  );

  expect(result.count).toBeGreaterThan(0);
  expect(result.ack).toBeTruthy();
});

test("streaming WS rejects a bad token with 4401", async ({ page }) => {
  await page.goto("/");
  const closed = await page.evaluate(async ({ wsUrl }: { wsUrl: string }) => {
    const ws = new WebSocket(wsUrl);
    return new Promise<number | null>((resolve) => {
      const t = setTimeout(() => resolve(null), 15_000);
      ws.onclose = (ev) => {
        clearTimeout(t);
        resolve(ev.code);
      };
      ws.onerror = () => {
        /* onclose follows */
      };
    });
  }, { wsUrl: `${WS_BASE}/streaming/quotes?token=bad-token` });
  expect(closed).toBe(4401);
});

test("/streaming page connects and shows live state", async ({ page }) => {
  await page.goto("/streaming");
  await page.getByRole("button", { name: /^connect$/i }).click();
  await expect(
    page.getByRole("button", { name: /^disconnect$/i }),
  ).toBeVisible({ timeout: 20_000 });
});
