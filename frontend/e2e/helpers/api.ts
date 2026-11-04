// Minimal fetch-based API client for E2E seeding/assertions (Bearer JWT only,
// so CSRF middleware exempts these calls — no CSRF handling needed).
// Secrets (passwords, tokens, TOTP secrets) are never logged here.

export const E2E_API_URL =
  process.env.E2E_API_URL ?? "http://localhost:8000/api";

export interface E2eCreds {
  email: string;
  username: string;
  password: string;
}

export interface E2eToken {
  access_token: string;
  user: { id: string; email: string; username: string; role: string };
}

export interface E2eActionItem {
  id: string;
  symbol: string;
  side: string;
  quantity: string;
  price: number;
  status: string;
  order_type: string | null;
}

async function req<T>(
  base: string,
  method: string,
  path: string,
  token?: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* ignore parse errors */
    }
    throw new Error(`${method} ${path} failed: ${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function uniqueUser(prefix = "e2e"): E2eCreds {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  return {
    email: `${prefix}-${stamp}@example.com`,
    username: `${prefix}_${stamp}`.replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 32),
    password: `E2e-${stamp}-pw!9`,
  };
}

export function registerUser(base: string, creds: E2eCreds): Promise<E2eToken> {
  return req<E2eToken>(base, "POST", "/auth/register", undefined, {
    email: creds.email,
    username: creds.username,
    password: creds.password,
  });
}

export function loginUser(
  base: string,
  identifier: string,
  password: string,
  totp_code?: string,
): Promise<E2eToken> {
  const body: Record<string, string> = { identifier, password };
  if (totp_code) body.totp_code = totp_code;
  return req<E2eToken>(base, "POST", "/auth/login", undefined, body);
}

export function setupTotp(
  base: string,
  token: string,
): Promise<{ secret: string; provisioning_uri: string; enabled: boolean }> {
  return req(base, "POST", "/auth/totp/setup", token, {});
}

export function verifyTotp(
  base: string,
  token: string,
  code: string,
): Promise<{ enabled: boolean }> {
  return req(base, "POST", "/auth/totp/verify", token, { code });
}

export function getMe(
  base: string,
  token: string,
): Promise<{ totp_enabled: boolean } & Record<string, unknown>> {
  return req(base, "GET", "/auth/me", token);
}

export function getSettings(
  base: string,
  token?: string,
): Promise<{
  execution_mode: string;
  selected_execution_broker: string;
}> {
  return req(base, "GET", "/v1/settings/", token);
}

/** Enable TOTP for a user, trying prev/curr/next codes until one verifies. */
export async function enableTotpForUser(
  base: string,
  token: string,
  codes: string[],
): Promise<string> {
  const setup = await setupTotp(base, token);
  let lastErr: unknown = null;
  for (const code of codes) {
    try {
      await verifyTotp(base, token, code);
      return setup.secret;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("TOTP verify failed");
}

/** Seed a pending approval item (REQUIRE_APPROVAL mode, no market data needed). */
export function seedPendingItem(
  base: string,
  token: string,
  overrides: { symbol?: string; side?: string; quantity?: number; order_type?: string } = {},
): Promise<{ id: string; status: string }> {
  return req(base, "POST", "/v1/orders/submit", token, {
    symbol: "NSE:RELIANCE",
    side: "BUY",
    quantity: 1,
    order_type: "MARKET",
    ...overrides,
  });
}

export function getActionItems(
  base: string,
  token: string,
  status_filter?: string,
): Promise<E2eActionItem[]> {
  const qs = status_filter ? `?status_filter=${status_filter}` : "";
  return req(base, "GET", `/action-center${qs}`, token);
}

export function getOrders(base: string, token: string): Promise<unknown[]> {
  return req(base, "GET", "/v1/orders", token);
}
