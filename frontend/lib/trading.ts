"use client"

import { api } from "@/lib/api-client"

// --- Terminal API types ---------------------------------------------------

export interface TerminalPosition {
  symbol: string
  quantity: number
  average_price: number
  last_price: number
  market_value: number
  invested: number
  unrealised_pnl: number
  unrealised_pnl_pct: number
  realised_pnl: number
  exchange: string
}

export interface PositionState {
  positions: TerminalPosition[]
  summary: {
    invested: number
    value: number
    unrealised_pnl: number
    unrealised_pnl_pct: number
    count: number
  }
}

export interface EquityPoint {
  date: string
  equity: number
  drawdown: number
}

export interface TerminalAnalytics {
  portfolio: {
    holdings: Array<Record<string, unknown>>
    summary: {
      invested: number
      value: number
      pnl: number
      pnl_pct: number
    }
  }
  equity_curve: EquityPoint[]
  summary: {
    base_capital: number
    current_equity: number
    total_pnl: number
    pnl_pct: number
    max_drawdown_pct: number
    daily_pnl: number
    n_filled_orders: number
  }
  risk: {
    execution_mode: string
    max_daily_loss_rupees: number
    max_order_risk_rupees: number
    max_open_positions: number
    max_capital_deployed_percent: number
    daily_pnl_rupees: number
    open_positions: number
    capital_deployed_pct: number
  }
}

export interface JournalEntry {
  id: string
  symbol: string
  side: string
  rationale: string
  pnl: number
  outcome: string
  tags: string[]
  created_at: string | null
}

export interface TradebotSignal {
  symbol: string
  name: string
  price: number
  change_pct: number
  signal_strength: number
  criteria: string[]
}

export interface TradebotState {
  enabled: boolean
  mode: string
  signals: TradebotSignal[]
  strategy: string
  updated_at: string
}

export interface OrderRecord {
  id: string
  order_id?: string | null
  symbol: string
  side: string
  quantity: number
  fill_price?: number | null
  price: number
  status: string
  message?: string | null
  risk_notes?: Record<string, unknown> | null
  created_at?: string | null
}

// --- API helpers ----------------------------------------------------------

export async function fetchPositions(): Promise<PositionState> {
  const { data } = await api.get<PositionState>("/api/terminal/positions")
  return data
}

export async function fetchAnalytics(): Promise<TerminalAnalytics> {
  const { data } = await api.get<TerminalAnalytics>("/api/terminal/analytics")
  return data
}

export async function fetchOrders(): Promise<OrderRecord[]> {
  const { data } = await api.get<OrderRecord[]>("/api/v1/orders")
  return data
}

export async function submitOrder(body: {
  symbol: string
  side: "BUY" | "SELL"
  quantity: number
  price?: number
  order_type?: "MARKET" | "LIMIT"
}): Promise<OrderRecord> {
  const { data } = await api.post<OrderRecord>("/api/v1/orders/submit", body)
  return data
}

export async function fetchJournal(): Promise<{ entries: JournalEntry[] }> {
  const { data } = await api.get<{ entries: JournalEntry[] }>("/api/terminal/journal")
  return data
}

export async function createJournalEntry(body: {
  symbol: string
  side: string
  rationale: string
  pnl: number
  outcome: string
  tags: string[]
}): Promise<{ id: string; created: boolean }> {
  const { data } = await api.post<{ id: string; created: boolean }>("/api/terminal/journal", body)
  return data
}

export async function deleteJournalEntry(id: string): Promise<{ deleted: boolean }> {
  const encoded = encodeURIComponent(id.replace(/^journal:/, ""))
  const { data } = await api.delete<{ deleted: boolean }>(`/api/terminal/journal/${encoded}`)
  return data
}

export async function fetchTradebot(): Promise<TradebotState> {
  const { data } = await api.get<TradebotState>("/api/terminal/tradebot")
  return data
}

export async function toggleTradebot(enabled: boolean): Promise<{ enabled: boolean }> {
  const { data } = await api.post<{ enabled: boolean }>("/api/terminal/tradebot/toggle", { enabled })
  return data
}

export async function executeTradebotSignal(body: {
  symbol: string
  side: "BUY" | "SELL"
  quantity: number
}): Promise<OrderRecord> {
  const { data } = await api.post<OrderRecord>("/api/terminal/tradebot/execute", body)
  return data
}

export async function fetchSettings(): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>("/api/v1/settings/")
  return data
}

export async function updateSettings(patch: Record<string, unknown>): Promise<Record<string, unknown>> {
  const { data } = await api.patch<Record<string, unknown>>("/api/v1/settings/", patch)
  return data
}

// --- Agent Autopilot (multi-agent supervisor) ------------------------------

export interface AutopilotConfig {
  enabled: boolean
  market: string
  scanners: string[]
  watchlist: string[]
  max_new_entries: number
  entry_qty: number
  take_profit_pct: number
  stop_loss_pct: number
  trail_enabled: boolean
  trail_drop_pct: number
  option_enabled: boolean
  option_max_plays: number
  option_lots: number
  use_llm: boolean
}

export interface AutopilotReview {
  score: number
  halt_recommended: boolean
  n_fills: number
  n_rejects: number
  n_entries: number
  n_exits: number
  n_option_tracks: number
  realised_pnl: number
  mission: string
  notes: string[]
}

export interface AutopilotRunNode {
  id: string
  position: number
  phase: string
  agent: string
  status: string
  evidence: Record<string, unknown> | null
  error: string | null
}

export interface AutopilotRun {
  id: string
  mission: string
  status: string
  error: string | null
  summary: Record<string, unknown> | null
  report: string | null
  started_at: string | null
  finished_at: string | null
  nodes?: AutopilotRunNode[]
  node_count?: number
}

export interface AutopilotState {
  enabled: boolean
  config: AutopilotConfig
  mode: string
  halt_recommended: boolean
  last_review: AutopilotReview | null
  last_run: AutopilotRun | null
}

export async function fetchAutopilotState(): Promise<AutopilotState> {
  const { data } = await api.get<AutopilotState>("/api/autopilot/state")
  return data
}

export async function toggleAutopilot(enabled: boolean): Promise<{ enabled: boolean }> {
  const { data } = await api.post<{ enabled: boolean }>("/api/autopilot/toggle", { enabled })
  return data
}

export async function saveAutopilotConfig(
  patch: Partial<AutopilotConfig>
): Promise<{ saved: boolean; config: AutopilotConfig }> {
  const { data } = await api.post<{ saved: boolean; config: AutopilotConfig }>("/api/autopilot/config", patch)
  return data
}

export async function runAutopilot(monitorOnly = false): Promise<AutopilotRun> {
  const { data } = await api.post<AutopilotRun>(`/api/autopilot/run?monitor_only=${monitorOnly}`)
  return data
}

export async function fetchAutopilotRuns(limit = 20): Promise<{ runs: AutopilotRun[] }> {
  const { data } = await api.get<{ runs: AutopilotRun[] }>(`/api/autopilot/runs?limit=${limit}`)
  return data
}

export async function fetchAutopilotRun(id: string): Promise<AutopilotRun> {
  const { data } = await api.get<AutopilotRun>(`/api/autopilot/runs/${id}`)
  return data
}

// --- Formatting helpers ---------------------------------------------------

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—"
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtCurrency(n: number | null | undefined, symbol = "₹"): string {
  if (n == null || Number.isNaN(n)) return "—"
  return `${symbol}${fmt(n, 2)}`
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${fmt(n, 2)}%`
}

export function pnlClass(n: number | null | undefined): string {
  if (n == null || n === 0) return "text-muted-foreground"
  return n > 0 ? "text-positive" : "text-negative"
}

export function pnlFmt(n: number | null | undefined, symbol = "₹"): string {
  if (n == null || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${symbol}${fmt(Math.abs(n), 2)}`
}

export function sideClass(side: string): string {
  const s = (side || "").toUpperCase()
  if (s === "BUY") return "text-positive"
  if (s === "SELL") return "text-negative"
  return "text-muted-foreground"
}

export function statusClass(status: string): string {
  const s = (status || "").toLowerCase()
  if (s === "filled" || s === "open") return "text-positive"
  if (s === "cancelled" || s === "rejected" || s === "loss") return "text-negative"
  return "text-muted-foreground"
}