// Flow builder + strategy host E2E (uses the storageState session from
// global-setup). Covers the real contracts in backend/app/api/routers/flow.py
// (/flow/graphs, /flow/validate, /flow/run, /flow/import, /flow/export) and
// backend/app/api/routers/strategy_host.py (/strategy-host/scripts,
// .../run, .../stop, .../logs, .../env). Strategy runs spawn real
// out-of-process children; the timeout test kills a sleeping script.
import fs from "fs";
import path from "path";
import { test, expect } from "@playwright/test";
import { E2E_API_URL } from "./helpers/api";

const BASE = process.env.E2E_API_URL ?? E2E_API_URL;
const TAG = `e2e${Date.now().toString(36)}`;

function loadToken(): string {
  const file = path.join(__dirname, ".auth", "creds.json");
  const raw = fs.readFileSync(file, "utf8");
  return (JSON.parse(raw) as { token: string }).token;
}

async function api(
  method: string,
  pathname: string,
  token: string,
  body?: unknown,
): Promise<{ status: number; body: unknown; text: string }> {
  const res = await fetch(`${BASE}${pathname}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  return { status: res.status, body: parsed, text };
}

const asRec = (v: unknown): Record<string, unknown> =>
  (v ?? {}) as Record<string, unknown>;

// Minimal valid graph (mirrors backend/tests/test_flow.py): market_data ->
// indicator -> condition -> order -> notification.
function validGraph(symbol: string): Record<string, unknown> {
  return {
    nodes: [
      { id: "md1", type: "market_data", params: { symbol } },
      { id: "ind1", type: "indicator", params: { function: "sma", period: 5, input: "md1" } },
      { id: "cond1", type: "condition", params: { operator: "gt", left: { node: "ind1" }, right: { value: 0 } } },
      { id: "ord1", type: "order", params: { symbol, side: "BUY", quantity: 1 } },
      { id: "note1", type: "notification", params: { message: "flow e2e" } },
    ],
    edges: [
      { from: "md1", to: "ind1" },
      { from: "ind1", to: "cond1" },
      { from: "cond1", to: "ord1" },
      { from: "ord1", to: "note1" },
    ],
  };
}

test("flow API: create + get + validate-bad-graph + dry-run", async () => {
  const token = loadToken();

  const created = await api("POST", "/flow/graphs", token, {
    name: `flow-${TAG}`,
    graph: validGraph("NSE:RELIANCE"),
  });
  expect(created.status).toBe(201);
  const graphId = String(asRec(created.body).id);
  expect(graphId.length).toBeGreaterThan(0);

  const got = await api("GET", `/flow/graphs/${graphId}`, token);
  expect(got.status).toBe(200);
  expect(String(asRec(got.body).name)).toContain(TAG);

  // Unknown node type is rejected at the API boundary with 422.
  const badType = await api("POST", "/flow/validate", token, {
    graph: { nodes: [{ id: "x", type: "teleport", params: {} }], edges: [] },
  });
  expect(badType.status).toBe(422);

  // Dangling edge is a finding, not a rejection: 200 + valid:false.
  const dangling = await api("POST", "/flow/validate", token, {
    graph: {
      nodes: [{ id: "a", type: "market_data", params: { symbol: "X" } }],
      edges: [{ from: "a", to: "ghost" }],
    },
  });
  expect(dangling.status).toBe(200);
  expect(asRec(dangling.body).valid).toBe(false);
  expect((asRec(dangling.body).findings as unknown[]).length).toBeGreaterThan(0);

  // Dry-run executes without touching the broker (quote failures degrade to
  // honest nulls, never errors).
  const run = await api("POST", "/flow/run", token, {
    graph_id: graphId,
    mode: "dry_run",
  });
  expect(run.status).toBe(200);
  expect(asRec(run.body).mode).toBe("dry_run");
  expect(Array.isArray(asRec(run.body).step_results)).toBe(true);
});

test("flow API: import + export round-trip", async () => {
  const token = loadToken();
  const name = `imported-${TAG}`;
  const imported = await api("POST", "/flow/import", token, {
    name,
    graph: validGraph("NSE:INFY"),
  });
  expect(imported.status).toBe(201);
  const graphId = String(asRec(imported.body).id);

  const exported = await api("GET", `/flow/export/${graphId}`, token);
  expect(exported.status).toBe(200);
  expect(String(asRec(exported.body).name)).toBe(name);
  expect(typeof asRec(exported.body).exported_at).toBe("string");
});

async function createScript(
  token: string,
  name: string,
  code: string,
): Promise<string> {
  const res = await api("POST", "/strategy-host/scripts", token, { name, code });
  expect(res.status).toBe(201);
  return String(asRec(res.body).id);
}

async function waitForTerminalLog(
  token: string,
  scriptId: string,
  deadlineMs: number,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + deadlineMs;
  for (;;) {
    const res = await api("GET", `/strategy-host/scripts/${scriptId}/logs`, token);
    expect(res.status).toBe(200);
    const payload = asRec(res.body);
    const terminal = ["completed", "failed", "killed", "stopped"];
    if (payload.run_id && terminal.includes(String(payload.status))) return payload;
    if (Date.now() > deadline) {
      throw new Error(`timed out waiting for terminal run (last=${res.text.slice(0, 200)})`);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

test("strategy API: run trivial script to completion, logs captured", async () => {
  const token = loadToken();
  const scriptId = await createScript(token, `strat-${TAG}`, 'print("e2e-ok")\n');

  const run = await api("POST", `/strategy-host/scripts/${scriptId}/run`, token, {});
  expect(run.status).toBe(200);
  expect(String(asRec(run.body).run_id).length).toBeGreaterThan(0);

  const payload = await waitForTerminalLog(token, scriptId, 25_000);
  expect(payload.status).toBe("completed");
  const logs = payload.logs as Array<{ line?: string } | string>;
  const text = logs
    .map((l) => (typeof l === "string" ? l : (l.line ?? "")))
    .join("\n");
  expect(text).toContain("e2e-ok");
});

test("strategy API: timeout kills a sleeping script; stop on never-ran is 404", async () => {
  const token = loadToken();
  const scriptId = await createScript(
    token,
    `sleeper-${TAG}`,
    "import time\ntime.sleep(120)\n",
  );

  const run = await api("POST", `/strategy-host/scripts/${scriptId}/run`, token, {
    timeout_seconds: 2,
  });
  expect(run.status).toBe(200);

  const payload = await waitForTerminalLog(token, scriptId, 30_000);
  expect(payload.status).toBe("killed");

  // A second run while none is active is fine; stopping a script that never
  // ran must 404 (idempotent-stop contract).
  const freshId = await createScript(token, `fresh-${TAG}`, 'print("x")\n');
  const stop = await api("POST", `/strategy-host/scripts/${freshId}/stop`, token, {});
  expect(stop.status).toBe(404);
});

test("strategy API: concurrent run returns 409 single-flight, then stop works", async () => {
  const token = loadToken();
  const scriptId = await createScript(
    token,
    `singleflight-${TAG}`,
    "import time\nwhile True:\n    time.sleep(0.1)\n",
  );

  const first = await api("POST", `/strategy-host/scripts/${scriptId}/run`, token, {});
  expect(first.status).toBe(200);

  // Second run while one is active must be rejected, not queued.
  const second = await api("POST", `/strategy-host/scripts/${scriptId}/run`, token, {});
  expect(second.status).toBe(409);

  const stop = await api("POST", `/strategy-host/scripts/${scriptId}/stop`, token, {});
  expect(stop.status).toBe(200);
  expect(asRec(stop.body).stopped).toBe(true);
  const payload = await waitForTerminalLog(token, scriptId, 30_000);
  expect(payload.status).toBe("stopped");
});

test("strategy API: env is write-only (names listed, values never echoed)", async () => {
  const token = loadToken();
  const scriptId = await createScript(token, `env-${TAG}`, 'print("x")\n');

  const put = await api("PUT", `/strategy-host/scripts/${scriptId}/env`, token, {
    E2E_FLOW_SECRET: "s3cr3t-value",
  });
  expect(put.status).toBe(200);
  expect((asRec(put.body).keys as string[])).toContain("E2E_FLOW_SECRET");

  const get = await api("GET", `/strategy-host/scripts/${scriptId}/env`, token);
  expect(get.status).toBe(200);
  expect((asRec(get.body).keys as string[])).toContain("E2E_FLOW_SECRET");
  expect(get.text).not.toContain("s3cr3t-value");
});

test("/flow page lists the API-created graph", async ({ page }) => {
  const token = loadToken();
  const name = `ui-flow-${TAG}`;
  await api("POST", "/flow/graphs", token, { name, graph: validGraph("NSE:TCS") });

  await page.goto("/flow");
  await expect(page.getByRole("heading", { name: /flow strategies/i })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText(name)).toBeVisible({ timeout: 20_000 });
});

test("/strategies page lists the API-created script", async ({ page }) => {
  const token = loadToken();
  const name = `ui-strat-${TAG}`;
  await createScript(token, name, 'print("ui")\n');

  await page.goto("/strategies");
  await expect(page.getByRole("heading", { name: /^strategies$/i })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText(name)).toBeVisible({ timeout: 20_000 });
});
