"use client"

import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Activity,
  AlertTriangle,
  Calculator,
  Layers,
  Loader2,
  RefreshCw,
  Sigma,
  TrendingUp,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SymbolSearch } from "@/components/stock/symbol-search"
import { api, ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

// --------------------------------------------------------------------------- types

interface OiProfile {
  symbol: string
  expiry: string | null
  spot: number | null
  strikes: number[]
  rows: Array<{
    strike: number
    call_oi: number
    put_oi: number
    total_oi: number
    pcr: number | null
  }>
  total_call_oi: number
  total_put_oi: number
  pcr: number | null
  max_call_oi_strike: number | null
  max_put_oi_strike: number | null
  support: number | null
  resistance: number | null
  has_oi: boolean
}

interface OiChange {
  symbol: string
  expiry: string | null
  rows: Array<{
    strike: number
    call_oi_change: number
    put_oi_change: number
  }>
  available: boolean
  note: string | null
}

interface IvSmile {
  symbol: string
  expiry: string | null
  spot: number | null
  atm_strike: number | null
  atm_iv: number | null
  atm_iv_pct: number | null
  skew_25d: number | null
  delta_source: string | null
  note?: string | null
  points: Array<{
    strike: number
    call_iv: number | null
    put_iv: number | null
    iv: number | null
    call_delta: number | null
    put_delta: number | null
  }>
  has_iv: boolean
}

interface VolSurface {
  symbol: string
  expiries: string[]
  strikes: number[]
  iv_matrix: Array<Array<number | null>>
  atm_term_structure: Array<{
    expiry: string
    atm_strike: number | null
    atm_iv: number | null
    atm_iv_pct: number | null
    skew_25d: number | null
  }>
  has_iv: boolean
}

interface Gex {
  symbol: string
  expiry: string | null
  spot: number | null
  rows: Array<{
    strike: number
    call_gex: number
    put_gex: number
    total_gex: number
    call_oi: number
    put_oi: number
  }>
  total_gex: number
  call_gex: number
  put_gex: number
  zero_gamma_strike: number | null
  flip_strike: number | null
  max_abs_gex_strike: number | null
  has_oi: boolean
}

interface Straddle {
  symbol: string
  expiry: string | null
  spot: number | null
  strike: number | null
  position: string
  entry_premium: number
  call_premium: number | null
  put_premium: number | null
  breakevens: number[]
  lower_breakeven: number | null
  upper_breakeven: number | null
  max_profit: number
  max_loss: number
  max_profit_price: number | null
  max_loss_price: number | null
  curve: Array<{ price: number; intrinsic: number; pnl: number }>
  note: string | null
}

interface MarginResult {
  symbol: string
  segment: string
  side: string
  product: string
  quantity: number
  price: number
  turnover: number
  span_margin: number
  exposure_margin: number
  total_margin: number
  margin_pct: number
  leverage: number
  available_margin: number | null
  blocked_margin: number
  remaining_after_trade: number | null
  notes: string[]
  is_estimate: boolean
}

interface SyntheticResult {
  symbol: string
  direction: string
  strike: number
  lot_size: number
  quantity: number
  call_premium: number
  put_premium: number
  cost: number
  effective_price: number
  breakeven: number
  total_margin: number
  span_margin: number
  exposure_margin: number
  legs: Array<{ option_type: string; side: string; strike: number; premium: number; quantity: number }>
  notes: string[]
  is_estimate: boolean
}

// --------------------------------------------------------------------------- helpers

function num(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—"
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function compact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—"
  const abs = Math.abs(v)
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(2)}K`
  return v.toFixed(0)
}

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—"
  return `${v.toFixed(2)}%`
}

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return `${err.message}`
    return `${err.message} (HTTP ${err.status})`
  }
  if (err instanceof Error) return err.message
  return fallback
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ""
}

function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string
  value: string
  hint?: string | null
  tone?: "default" | "positive" | "negative" | "warning"
}) {
  const toneClass =
    tone === "positive"
      ? "text-positive"
      : tone === "negative"
        ? "text-negative"
        : tone === "warning"
          ? "text-amber-600 dark:text-amber-500"
          : "text-foreground"
  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-lg font-semibold", toneClass)}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function ErrorNote({ err }: { err: unknown }) {
  return (
    <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {errText(err, "Request failed.")}
    </div>
  )
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading…
    </div>
  )
}

// --------------------------------------------------------------------------- page

export default function OptionsAnalyticsPage() {
  const [symbol, setSymbol] = useState("")
  const [activeSymbol, setActiveSymbol] = useState("")
  const [expiry, setExpiry] = useState("")

  const [marginForm, setMarginForm] = useState({
    symbol: "",
    side: "BUY",
    quantity: "1",
    price: "100",
    segment: "equity",
    product: "MIS",
    lot_size: "1",
    available_margin: "",
  })
  const [syntheticForm, setSyntheticForm] = useState({
    symbol: "",
    direction: "long",
    strike: "",
    quantity: "1",
    lot_size: "1",
    expiry: "",
  })

  const enabled = activeSymbol.length > 0
  const q = useMemo(
    () => query({ symbol: activeSymbol, expiry: expiry || undefined }),
    [activeSymbol, expiry],
  )

  const oiProfile = useQuery<OiProfile>({
    queryKey: ["options-analytics", "oi-profile", q],
    queryFn: () => api.get<OiProfile>(`/options/analytics/oi-profile${q}`),
    enabled: enabled,
    retry: false,
  })

  const oiChange = useQuery<OiChange>({
    queryKey: ["options-analytics", "oi-change", q],
    queryFn: () => api.get<OiChange>(`/options/analytics/oi-change${q}`),
    enabled: enabled,
    retry: false,
  })

  const ivSmile = useQuery<IvSmile>({
    queryKey: ["options-analytics", "iv-smile", q],
    queryFn: () => api.get<IvSmile>(`/options/analytics/iv-smile${q}`),
    enabled: enabled,
    retry: false,
  })

  const volSurface = useQuery<VolSurface>({
    queryKey: ["options-analytics", "vol-surface", activeSymbol],
    queryFn: () =>
      api.get<VolSurface>(
        `/options/analytics/vol-surface${query({ symbol: activeSymbol, max_expiries: 4 })}`,
      ),
    enabled: enabled,
    retry: false,
  })

  const gex = useQuery<Gex>({
    queryKey: ["options-analytics", "gex", q],
    queryFn: () => api.get<Gex>(`/options/analytics/gex${q}`),
    enabled: enabled,
    retry: false,
  })

  const [straddlePosition, setStraddlePosition] = useState("long")
  const straddle = useQuery<Straddle>({
    queryKey: ["options-analytics", "straddle", q, straddlePosition],
    queryFn: () =>
      api.get<Straddle>(
        `/options/analytics/straddle${query({
          symbol: activeSymbol,
          expiry: expiry || undefined,
          position: straddlePosition,
        })}`,
      ),
    enabled: enabled,
    retry: false,
  })

  const marginCalc = useMutation<MarginResult, unknown, Record<string, unknown>>({
    mutationFn: (body) => api.post<MarginResult>("/options/margin/calculate", body),
  })

  const synthetic = useMutation<SyntheticResult, unknown, Record<string, unknown>>({
    mutationFn: (body) => api.post<SyntheticResult>("/options/margin/synthetic-futures", body),
  })

  const load = () => {
    const s = symbol.trim().toUpperCase()
    if (!s) return
    setActiveSymbol(s)
    setMarginForm((f) => ({ ...f, symbol: s }))
    setSyntheticForm((f) => ({ ...f, symbol: s }))
  }

  const refreshAll = () => {
    oiProfile.refetch()
    oiChange.refetch()
    ivSmile.refetch()
    volSurface.refetch()
    gex.refetch()
    straddle.refetch()
  }

  const anyError = oiProfile.error || oiChange.error || ivSmile.error || gex.error || volSurface.error

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">Options Analytics</h1>
          <p className="text-sm text-muted-foreground">
            Open-interest structure, implied volatility, gamma exposure, payoff curves and
            margin estimation — computed from the live provider chain.
          </p>
        </div>
        {enabled ? (
          <Button variant="outline" onClick={refreshAll} disabled={oiProfile.isFetching}>
            <RefreshCw className={cn("mr-2 h-4 w-4", oiProfile.isFetching && "animate-spin")} />
            Refresh
          </Button>
        ) : null}
      </div>

      {/* Symbol picker */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" /> Underlying
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4">
            <div className="md:col-span-2">
              <Label className="mb-1 block text-xs text-muted-foreground">Symbol</Label>
              <SymbolSearch onSelect={setSymbol} placeholder="NSE:NIFTY, NIFTY, AAPL…" />
            </div>
            <div>
              <Label className="mb-1 block text-xs text-muted-foreground">Expiry (optional)</Label>
              <Input
                type="date"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
              />
            </div>
            <div className="flex items-end">
              <Button onClick={load} disabled={!symbol.trim()} className="w-full">
                Load analytics
              </Button>
            </div>
          </div>
          {activeSymbol ? (
            <p className="mt-3 text-xs text-muted-foreground">
              Active underlying: <span className="font-medium text-foreground">{activeSymbol}</span>
              {expiry ? ` · expiry ${expiry}` : " · nearest expiry"}
            </p>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              Pick a symbol to load the chain. Analytics never fabricate values — if the
              provider does not publish open interest or IV the corresponding panel says so.
            </p>
          )}
          {anyError ? (
            <div className="mt-3">
              <ErrorNote err={anyError} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      {!enabled ? (
        <EmptyState>Select a symbol above to see open interest, IV, gamma and margin analytics.</EmptyState>
      ) : (
        <Tabs defaultValue="oi" className="space-y-4">
          <TabsList className="flex flex-wrap">
            <TabsTrigger value="oi">OI Profile</TabsTrigger>
            <TabsTrigger value="oichange">OI Change</TabsTrigger>
            <TabsTrigger value="iv">IV Smile</TabsTrigger>
            <TabsTrigger value="surface">Vol Surface</TabsTrigger>
            <TabsTrigger value="gex">GEX</TabsTrigger>
            <TabsTrigger value="straddle">Straddle</TabsTrigger>
            <TabsTrigger value="margin">Margin</TabsTrigger>
            <TabsTrigger value="synthetic">Synthetic Futures</TabsTrigger>
          </TabsList>

          {/* ---------------------------------------------------------- OI profile */}
          <TabsContent value="oi" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Layers className="h-5 w-5" /> Open interest by strike
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {oiProfile.isLoading ? (
                  <Loading />
                ) : oiProfile.error ? (
                  <ErrorNote err={oiProfile.error} />
                ) : oiProfile.data ? (
                  <>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="Total call OI" value={compact(oiProfile.data.total_call_oi)} />
                      <Stat label="Total put OI" value={compact(oiProfile.data.total_put_oi)} />
                      <Stat
                        label="PCR"
                        value={oiProfile.data.pcr == null ? "—" : oiProfile.data.pcr.toFixed(2)}
                        hint={oiProfile.data.has_oi ? undefined : "Provider publishes no open interest"}
                      />
                      <Stat label="Spot" value={num(oiProfile.data.spot)} />
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Stat
                        label="Resistance (max call OI)"
                        value={num(oiProfile.data.resistance)}
                        tone="negative"
                      />
                      <Stat
                        label="Support (max put OI)"
                        value={num(oiProfile.data.support)}
                        tone="positive"
                      />
                    </div>
                    {oiProfile.data.rows.length === 0 ? (
                      <EmptyState>No strikes returned for this chain.</EmptyState>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Strike</TableHead>
                            <TableHead className="text-right">Call OI</TableHead>
                            <TableHead className="text-right">Put OI</TableHead>
                            <TableHead className="text-right">Total OI</TableHead>
                            <TableHead className="text-right">PCR</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {oiProfile.data.rows.map((r) => (
                            <TableRow key={r.strike}>
                              <TableCell className="font-medium">{num(r.strike, 0)}</TableCell>
                              <TableCell className="text-right">{compact(r.call_oi)}</TableCell>
                              <TableCell className="text-right">{compact(r.put_oi)}</TableCell>
                              <TableCell className="text-right">{compact(r.total_oi)}</TableCell>
                              <TableCell className="text-right">
                                {r.pcr == null ? "—" : r.pcr.toFixed(2)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- OI change */}
          <TabsContent value="oichange" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" /> Intraday open-interest change
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {oiChange.isLoading ? (
                  <Loading />
                ) : oiChange.error ? (
                  <ErrorNote err={oiChange.error} />
                ) : oiChange.data ? (
                  oiChange.data.available ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Strike</TableHead>
                          <TableHead className="text-right">Call OI change</TableHead>
                          <TableHead className="text-right">Put OI change</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {oiChange.data.rows.map((r) => (
                          <TableRow key={r.strike}>
                            <TableCell className="font-medium">{num(r.strike, 0)}</TableCell>
                            <TableCell
                              className={cn(
                                "text-right",
                                r.call_oi_change > 0
                                  ? "text-positive"
                                  : r.call_oi_change < 0
                                    ? "text-negative"
                                    : "",
                              )}
                            >
                              {compact(r.call_oi_change)}
                            </TableCell>
                            <TableCell
                              className={cn(
                                "text-right",
                                r.put_oi_change > 0
                                  ? "text-positive"
                                  : r.put_oi_change < 0
                                    ? "text-negative"
                                    : "",
                              )}
                            >
                              {compact(r.put_oi_change)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <div className="rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-600 dark:text-amber-500">
                      {oiChange.data.note ?? "Open-interest change is not published by this provider."}
                    </div>
                  )
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- IV smile */}
          <TabsContent value="iv" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sigma className="h-5 w-5" /> Implied volatility smile
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {ivSmile.isLoading ? (
                  <Loading />
                ) : ivSmile.error ? (
                  <ErrorNote err={ivSmile.error} />
                ) : ivSmile.data ? (
                  <>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="ATM strike" value={num(ivSmile.data.atm_strike, 0)} />
                      <Stat label="ATM IV" value={pct(ivSmile.data.atm_iv_pct)} />
                      <Stat
                        label="25-delta skew"
                        value={
                          ivSmile.data.skew_25d == null ? "—" : `${ivSmile.data.skew_25d.toFixed(2)}%`
                        }
                        hint={
                          ivSmile.data.delta_source === "proxy"
                            ? "Delta proxy (no 25Δ points published)"
                            : ivSmile.data.delta_source === "unavailable"
                              ? "Not computable for this expiry"
                              : undefined
                        }
                      />
                      <Stat label="Spot" value={num(ivSmile.data.spot)} />
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Strike</TableHead>
                          <TableHead className="text-right">Call IV</TableHead>
                          <TableHead className="text-right">Put IV</TableHead>
                          <TableHead className="text-right">Avg IV</TableHead>
                          <TableHead className="text-right">Call Δ</TableHead>
                          <TableHead className="text-right">Put Δ</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {ivSmile.data.points.map((p) => (
                          <TableRow key={p.strike}>
                            <TableCell className="font-medium">{num(p.strike, 0)}</TableCell>
                            <TableCell className="text-right">{pct(p.call_iv)}</TableCell>
                            <TableCell className="text-right">{pct(p.put_iv)}</TableCell>
                            <TableCell className="text-right">{pct(p.iv)}</TableCell>
                            <TableCell className="text-right">
                              {p.call_delta == null ? "—" : p.call_delta.toFixed(3)}
                            </TableCell>
                            <TableCell className="text-right">
                              {p.put_delta == null ? "—" : p.put_delta.toFixed(3)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {ivSmile.data.note ? (
                      <div className="rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-600 dark:text-amber-500">
                        {ivSmile.data.note}
                      </div>
                    ) : null}
                  </>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- Vol surface */}
          <TabsContent value="surface" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Layers className="h-5 w-5" /> Volatility surface
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {volSurface.isLoading ? (
                  <Loading />
                ) : volSurface.error ? (
                  <ErrorNote err={volSurface.error} />
                ) : volSurface.data ? (
                  <>
                    {volSurface.data.atm_term_structure.length > 0 ? (
                      <div>
                        <h3 className="mb-2 text-sm font-medium">ATM term structure</h3>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Expiry</TableHead>
                              <TableHead className="text-right">ATM strike</TableHead>
                              <TableHead className="text-right">ATM IV</TableHead>
                              <TableHead className="text-right">25Δ skew</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {volSurface.data.atm_term_structure.map((t) => (
                              <TableRow key={t.expiry}>
                                <TableCell className="font-medium">{t.expiry}</TableCell>
                                <TableCell className="text-right">{num(t.atm_strike, 0)}</TableCell>
                                <TableCell className="text-right">{pct(t.atm_iv_pct)}</TableCell>
                                <TableCell className="text-right">
                                  {t.skew_25d == null ? "—" : `${t.skew_25d.toFixed(2)}%`}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    ) : null}

                    {volSurface.data.expiries.length === 0 ? (
                      <EmptyState>No expiries available for this underlying.</EmptyState>
                    ) : (
                      <div>
                        <h3 className="mb-2 text-sm font-medium">IV matrix (strike × expiry)</h3>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Strike</TableHead>
                              {volSurface.data.expiries.map((exp) => (
                                <TableHead key={exp} className="text-right">
                                  {exp}
                                </TableHead>
                              ))}
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {volSurface.data.strikes.map((strike, idx) => (
                              <TableRow key={strike}>
                                <TableCell className="font-medium">{num(strike, 0)}</TableCell>
                                {volSurface.data.expiries.map((exp, colIdx) => {
                                  const value =
                                    volSurface.data.iv_matrix[colIdx]?.[idx] ??
                                    volSurface.data.iv_matrix[idx]?.[colIdx] ??
                                    null
                                  return (
                                    <TableCell key={`${exp}-${strike}`} className="text-right">
                                      {pct(value)}
                                    </TableCell>
                                  )
                                })}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        <p className="mt-2 text-[11px] text-muted-foreground">
                          Matrix rows are expiries, columns are strikes.
                        </p>
                      </div>
                    )}
                  </>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- GEX */}
          <TabsContent value="gex" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-5 w-5" /> Gamma exposure
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {gex.isLoading ? (
                  <Loading />
                ) : gex.error ? (
                  <ErrorNote err={gex.error} />
                ) : gex.data ? (
                  <>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="Total GEX" value={compact(gex.data.total_gex)} />
                      <Stat label="Call GEX" value={compact(gex.data.call_gex)} />
                      <Stat label="Put GEX" value={compact(gex.data.put_gex)} />
                      <Stat label="Spot" value={num(gex.data.spot)} />
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Stat
                        label="Zero-gamma strike"
                        value={num(gex.data.zero_gamma_strike, 0)}
                        hint="Gamma flips sign around this level"
                      />
                      <Stat
                        label="Flip strike"
                        value={num(gex.data.flip_strike, 0)}
                        hint="Dealer hedging direction changes here"
                      />
                    </div>
                    {gex.data.rows.length === 0 ? (
                      <EmptyState>No strikes returned for this chain.</EmptyState>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Strike</TableHead>
                            <TableHead className="text-right">Call GEX</TableHead>
                            <TableHead className="text-right">Put GEX</TableHead>
                            <TableHead className="text-right">Total GEX</TableHead>
                            <TableHead className="text-right">Call OI</TableHead>
                            <TableHead className="text-right">Put OI</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {gex.data.rows.map((r) => (
                            <TableRow key={r.strike}>
                              <TableCell className="font-medium">{num(r.strike, 0)}</TableCell>
                              <TableCell className="text-right">{compact(r.call_gex)}</TableCell>
                              <TableCell className="text-right">{compact(r.put_gex)}</TableCell>
                              <TableCell
                                className={cn(
                                  "text-right font-medium",
                                  r.total_gex > 0
                                    ? "text-positive"
                                    : r.total_gex < 0
                                      ? "text-negative"
                                      : "",
                                )}
                              >
                                {compact(r.total_gex)}
                              </TableCell>
                              <TableCell className="text-right">{compact(r.call_oi)}</TableCell>
                              <TableCell className="text-right">{compact(r.put_oi)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                    <p className="text-[11px] text-muted-foreground">
                      Dealer convention: call gamma is treated as negative and put gamma as
                      positive, so the total flips sign at the flip strike.
                    </p>
                  </>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- Straddle */}
          <TabsContent value="straddle" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" /> Straddle payoff
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-2">
                  <Button
                    variant={straddlePosition === "long" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStraddlePosition("long")}
                  >
                    Long straddle
                  </Button>
                  <Button
                    variant={straddlePosition === "short" ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStraddlePosition("short")}
                  >
                    Short straddle
                  </Button>
                </div>
                {straddle.isLoading ? (
                  <Loading />
                ) : straddle.error ? (
                  <ErrorNote err={straddle.error} />
                ) : straddle.data ? (
                  <>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="Strike" value={num(straddle.data.strike, 0)} />
                      <Stat label="Entry premium" value={num(straddle.data.entry_premium)} />
                      <Stat
                        label="Lower breakeven"
                        value={num(straddle.data.lower_breakeven)}
                        tone="negative"
                      />
                      <Stat
                        label="Upper breakeven"
                        value={num(straddle.data.upper_breakeven)}
                        tone="negative"
                      />
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Stat
                        label="Max profit"
                        value={num(straddle.data.max_profit)}
                        tone="positive"
                      />
                      <Stat label="Max loss" value={num(straddle.data.max_loss)} tone="negative" />
                    </div>
                    {straddle.data.curve.length === 0 ? (
                      <EmptyState>No payoff points returned.</EmptyState>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Underlying price</TableHead>
                            <TableHead className="text-right">Intrinsic</TableHead>
                            <TableHead className="text-right">P&amp;L</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {straddle.data.curve.map((c) => (
                            <TableRow key={c.price}>
                              <TableCell className="font-medium">{num(c.price)}</TableCell>
                              <TableCell className="text-right">{num(c.intrinsic)}</TableCell>
                              <TableCell
                                className={cn(
                                  "text-right",
                                  c.pnl > 0 ? "text-positive" : c.pnl < 0 ? "text-negative" : "",
                                )}
                              >
                                {num(c.pnl)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                    {straddle.data.note ? (
                      <p className="text-[11px] text-muted-foreground">{straddle.data.note}</p>
                    ) : null}
                  </>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- Margin */}
          <TabsContent value="margin" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Calculator className="h-5 w-5" /> Margin calculator
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Symbol</Label>
                    <Input
                      value={marginForm.symbol}
                      onChange={(e) =>
                        setMarginForm((f) => ({ ...f, symbol: e.target.value.toUpperCase() }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Side</Label>
                    <select
                      className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                      value={marginForm.side}
                      onChange={(e) => setMarginForm((f) => ({ ...f, side: e.target.value }))}
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Quantity</Label>
                    <Input
                      type="number"
                      min="1"
                      value={marginForm.quantity}
                      onChange={(e) =>
                        setMarginForm((f) => ({ ...f, quantity: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Price</Label>
                    <Input
                      type="number"
                      step="any"
                      min="0"
                      value={marginForm.price}
                      onChange={(e) => setMarginForm((f) => ({ ...f, price: e.target.value }))}
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Segment</Label>
                    <select
                      className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                      value={marginForm.segment}
                      onChange={(e) =>
                        setMarginForm((f) => ({ ...f, segment: e.target.value }))
                      }
                    >
                      <option value="equity">equity</option>
                      <option value="futures">futures</option>
                      <option value="options">options</option>
                      <option value="currency">currency</option>
                    </select>
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Product</Label>
                    <select
                      className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                      value={marginForm.product}
                      onChange={(e) =>
                        setMarginForm((f) => ({ ...f, product: e.target.value }))
                      }
                    >
                      <option value="MIS">MIS</option>
                      <option value="CNC">CNC</option>
                      <option value="NRML">NRML</option>
                    </select>
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Lot size</Label>
                    <Input
                      type="number"
                      min="1"
                      value={marginForm.lot_size}
                      onChange={(e) =>
                        setMarginForm((f) => ({ ...f, lot_size: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">
                      Available margin (optional)
                    </Label>
                    <Input
                      type="number"
                      step="any"
                      min="0"
                      value={marginForm.available_margin}
                      onChange={(e) =>
                        setMarginForm((f) => ({ ...f, available_margin: e.target.value }))
                      }
                    />
                  </div>
                </div>
                <Button
                  onClick={() =>
                    marginCalc.mutate({
                      symbol: marginForm.symbol,
                      side: marginForm.side,
                      quantity: Number(marginForm.quantity),
                      price: Number(marginForm.price),
                      segment: marginForm.segment,
                      product: marginForm.product,
                      lot_size: Number(marginForm.lot_size),
                      available_margin: marginForm.available_margin
                        ? Number(marginForm.available_margin)
                        : null,
                    })
                  }
                  disabled={marginCalc.isPending || !marginForm.symbol}
                >
                  {marginCalc.isPending ? "Calculating…" : "Calculate margin"}
                </Button>

                {marginCalc.error ? <ErrorNote err={marginCalc.error} /> : null}
                {marginCalc.data ? (
                  <div className="space-y-3">
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="Turnover" value={num(marginCalc.data.turnover)} />
                      <Stat label="Span margin" value={num(marginCalc.data.span_margin)} />
                      <Stat label="Exposure margin" value={num(marginCalc.data.exposure_margin)} />
                      <Stat
                        label="Total margin"
                        value={num(marginCalc.data.total_margin)}
                        tone="warning"
                      />
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="Margin %" value={pct(marginCalc.data.margin_pct)} />
                      <Stat label="Leverage" value={`${marginCalc.data.leverage}x`} />
                      <Stat label="Blocked margin" value={num(marginCalc.data.blocked_margin)} />
                      <Stat
                        label="Remaining after trade"
                        value={num(marginCalc.data.remaining_after_trade)}
                      />
                    </div>
                    {marginCalc.data.notes?.length ? (
                      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                        {marginCalc.data.notes.map((n, i) => (
                          <li key={i}>{n}</li>
                        ))}
                      </ul>
                    ) : null}
                    <div className="flex items-center gap-2 rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-500">
                      <AlertTriangle className="h-4 w-4 shrink-0" />
                      Estimate only — broker SPAN/exposure values differ. Use this for planning,
                      not for live order sizing.
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- Synthetic futures */}
          <TabsContent value="synthetic" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sigma className="h-5 w-5" /> Synthetic futures
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Symbol</Label>
                    <Input
                      value={syntheticForm.symbol}
                      onChange={(e) =>
                        setSyntheticForm((f) => ({ ...f, symbol: e.target.value.toUpperCase() }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Direction</Label>
                    <select
                      className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                      value={syntheticForm.direction}
                      onChange={(e) =>
                        setSyntheticForm((f) => ({ ...f, direction: e.target.value }))
                      }
                    >
                      <option value="long">long</option>
                      <option value="short">short</option>
                    </select>
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">
                      Strike (blank = ATM)
                    </Label>
                    <Input
                      type="number"
                      step="any"
                      min="0"
                      value={syntheticForm.strike}
                      onChange={(e) =>
                        setSyntheticForm((f) => ({ ...f, strike: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Quantity (lots)</Label>
                    <Input
                      type="number"
                      min="1"
                      value={syntheticForm.quantity}
                      onChange={(e) =>
                        setSyntheticForm((f) => ({ ...f, quantity: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Lot size</Label>
                    <Input
                      type="number"
                      min="1"
                      value={syntheticForm.lot_size}
                      onChange={(e) =>
                        setSyntheticForm((f) => ({ ...f, lot_size: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Expiry (optional)</Label>
                    <Input
                      type="date"
                      value={syntheticForm.expiry}
                      onChange={(e) =>
                        setSyntheticForm((f) => ({ ...f, expiry: e.target.value }))
                      }
                    />
                  </div>
                </div>
                <Button
                  onClick={() =>
                    synthetic.mutate({
                      symbol: syntheticForm.symbol,
                      direction: syntheticForm.direction,
                      strike: syntheticForm.strike ? Number(syntheticForm.strike) : null,
                      quantity: Number(syntheticForm.quantity),
                      lot_size: Number(syntheticForm.lot_size),
                      expiry: syntheticForm.expiry || null,
                    })
                  }
                  disabled={synthetic.isPending || !syntheticForm.symbol}
                >
                  {synthetic.isPending ? "Building…" : "Build synthetic"}
                </Button>

                {synthetic.error ? <ErrorNote err={synthetic.error} /> : null}
                {synthetic.data ? (
                  <div className="space-y-3">
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Stat label="Cost" value={num(synthetic.data.cost)} />
                      <Stat label="Effective price" value={num(synthetic.data.effective_price)} />
                      <Stat label="Breakeven" value={num(synthetic.data.breakeven)} />
                      <Stat
                        label="Total margin"
                        value={num(synthetic.data.total_margin)}
                        tone="warning"
                      />
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Leg</TableHead>
                          <TableHead>Side</TableHead>
                          <TableHead className="text-right">Strike</TableHead>
                          <TableHead className="text-right">Premium</TableHead>
                          <TableHead className="text-right">Qty</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {synthetic.data.legs.map((leg, i) => (
                          <TableRow key={`${leg.option_type}-${i}`}>
                            <TableCell className="font-medium">{leg.option_type}</TableCell>
                            <TableCell>{leg.side}</TableCell>
                            <TableCell className="text-right">{num(leg.strike, 0)}</TableCell>
                            <TableCell className="text-right">{num(leg.premium)}</TableCell>
                            <TableCell className="text-right">{leg.quantity}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {synthetic.data.notes?.length ? (
                      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                        {synthetic.data.notes.map((n, i) => (
                          <li key={i}>{n}</li>
                        ))}
                      </ul>
                    ) : null}
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">estimate</Badge>
                      <span className="text-xs text-muted-foreground">
                        Margin is an estimate based on the configured leverage table.
                      </span>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
