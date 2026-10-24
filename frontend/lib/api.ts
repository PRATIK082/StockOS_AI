export const API_BASE = process.env.NEXT_PUBLIC_API_URL ? `${process.env.NEXT_PUBLIC_API_URL}/api` : "http://localhost:8000/api";

export interface User {
  id: string;
  email: string;
  username: string;
  role: string;
}

export interface Quote {
  symbol: string;
  name: string | null;
  price: number | null;
  previous_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  currency: string | null;
  day_change_pct: number | null;
  market_cap: number | null;
  sector: string | null;
  provider: string | null;
}

export interface Candle {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface History {
  symbol: string;
  interval: string;
  period: string;
  provider: string | null;
  candles: Candle[];
}

export interface AgentSection {
  agent: string;
  content: string;
  confidence: number;
}

export interface ResearchResult {
  task: string;
  symbol: string | null;
  plan: string[];
  confidence: number;
  sources: string[];
  sections: AgentSection[];
  answer: string;
}

export interface ChatResult extends ResearchResult {}

// --- Vibe Trading Chat (SSE) -------------------------------------------------

export interface VibePlanEvent {
  type: "plan";
  plan: Array<{ key: string; label: string }>;
}

export interface VibeStageEvent {
  type: "stage";
  status: "done" | "skipped" | "error";
  key: string;
  data: Record<string, any>;
}

export interface VibeAnswerEvent {
  type: "answer";
  data: {
    answer: string;
    confidence: number;
    symbol: string | null;
    sources: string[];
  };
}

export interface VibeErrorEvent {
  type: "error";
  data: { detail: string };
}

export type VibeEvent = VibePlanEvent | VibeStageEvent | VibeAnswerEvent | VibeErrorEvent;

export interface Watchlist {
  id: string;
  name: string;
  symbols: string[];
}

export interface Holding {
  id: string;
  symbol: string;
  quantity: string;
  average_cost: string;
  current_price: number;
  invested: number;
  value: number;
  pnl: number;
  pnl_pct: number;
}

export interface Portfolio {
  holdings: Holding[];
  summary: {
    invested: number;
    value: number;
    pnl: number;
    pnl_pct: number;
  };
}

export interface SearchResult {
  symbol: string;
  name: string;
  market: "india" | "us";
  currency: string;
  index: boolean;
}

export interface OptionPosition {
  id: string;
  symbol: string;
  option_type: "CALL" | "PUT";
  strike: number;
  expiry: string;
  quantity: number;
  premium: number;
  created_at: string | null;
}

export type OptionPositionInput = Omit<OptionPosition, "id" | "created_at"> & { option_type: "CALL" | "PUT" | "CE" | "PE" };

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
  if (typeof window !== "undefined") {
    if (token) window.localStorage.setItem("sm_token", token);
    else window.localStorage.removeItem("sm_token");
  }
}

export function getAuthToken(): string | null {
  if (!authToken && typeof window !== "undefined") {
    authToken = window.localStorage.getItem("sm_token");
  }
  return authToken;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      `Cannot reach backend at ${API_BASE} - is it running?`,
      0,
    );
  }
  if (res.status === 401) {
    setAuthToken(null);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// --- Domain helpers ---------------------------------------------------------

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtCompact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return n.toFixed(2);
}

export function pctColor(n: number | null | undefined): string {
  if (n == null || n === 0) return "text-muted-foreground";
  return n > 0 ? "text-positive" : "text-negative";
}
