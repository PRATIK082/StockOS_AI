"use client"

import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SymbolSearch } from "@/components/stock/symbol-search"
import MarketChart from "@/components/stock/MarketChart"
import OptionPremiumChart from "@/components/stock/OptionPremiumChart"
import OptionPositionsWidget from "@/components/stock/OptionPositionsWidget"
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel"
import { TrendingUp, TrendingDown, Plus, LineChart, SlidersHorizontal, Activity } from "lucide-react"
import { api as http } from "@/lib/api-client"
import { api, getAuthToken, type OptionPosition, type OptionPositionInput } from "@/lib/api"

interface OptionChain {
  symbol: string
  expiry: string
  expiries: string[]
  spot_price: number
  calls: OptionRow[]
  puts: OptionRow[]
  max_pain: number | null
  pcr: number | null
  iv_rank: number
}

interface OptionRow {
  strike: number
  bid: number | null
  ask: number | null
  last: number
  volume: number
  oi: number
  iv: number
}

interface Strategy {
  name: string
  max_profit: number
  max_loss: number
  breakeven: number[]
  probability_profit: number
  expected_return: number
  greeks: {
    delta: number
    gamma: number
    theta: number
    vega: number
    rho: number
  }
}

interface OptionSignals {
  symbol: string
  expiry: string | null
  spot_price: number | null
  max_pain: number | null
  premium_put_call: number | null
  iv_skew: number | null
  atm_iv: number | null
  avg_iv: number | null
  bias: "CALL" | "PUT" | "NEUTRAL"
  strategy: string
  recommendation: string
}

interface ProviderStatusItem {
  display_name: string
  exchanges: string[]
  capabilities: string[]
  notes?: string
  reachable: boolean
  default_for: string[]
}

function num(v: number | undefined): string {
  return v == null || Number.isNaN(v) ? "—" : String(v)
}

// The free TradingView scanner does not publish open interest / volume for
// options. A `0` from that feed means "not provided", so we render "—" and
// explain via tooltip instead of pretending it is zero.
function pub(v: number | undefined): string {
  return v == null || Number.isNaN(v) || v <= 0 ? "—" : String(v)
}

function Pub({ v }: { v: number | undefined }) {
  return (
    <span title="Not published by the free options scanner">{(v ?? 0) > 0 ? v : "—"}</span>
  )
}

function num2(v: number | null | undefined): string {
  return v == null || Number.isNaN(v) ? "—" : v.toFixed(2)
}

function errDetail(err: any, fallback: string): string {
  if (err?.response?.data?.detail) return String(err.response.data.detail)
  if (err?.message && err.message !== "Request failed with status code 404") return err.message
  return fallback
}

function mid(row?: OptionRow): number {
  if (!row) return 0
  if (row.bid != null && row.ask != null && (row.bid || row.ask))
    return Number(((row.bid + row.ask) / 2).toFixed(2))
  return Number(row.last || 0)
}

function ChainRow({
  call,
  put,
  spot,
  onAdd,
  active,
  onSelect,
}: {
  call?: OptionRow
  put?: OptionRow
  spot: number
  onAdd: (kind: "CALL" | "PUT", row: OptionRow) => void
  active?: boolean
  onSelect: (strike: number) => void
}) {
  const isCallITM = !!call && call.strike < spot
  const isPutITM = !!put && put.strike > spot
  const callCls = isCallITM ? "bg-positive/10" : ""
  const putCls = isPutITM ? "bg-negative/10" : ""
  return (
    <tr
      className={`border-b hover:bg-muted/40 ${active ? "bg-accent/30" : ""}`}
      onClick={() => onSelect(call?.strike ?? put?.strike!)}
    >
      <td className={`p-1 ${callCls}`}><Pub v={call?.oi} /></td>
      <td className={`p-1 ${callCls}`}><Pub v={call?.volume} /></td>
      <td className={`p-1 ${callCls}`}>{call ? (call.iv * 100).toFixed(1) : "—"}</td>
      <td className={`p-1 ${callCls}`}>{call ? num2(call.bid) : "—"}</td>
      <td className={`p-1 ${callCls}`}>{call ? num2(call.ask) : "—"}</td>
      <td className={`p-1 ${callCls}`}>{call ? num(call.last) : "—"}</td>
      <td className="p-1 font-bold bg-muted/40">{call?.strike ?? put?.strike}</td>
      <td className={`p-1 ${putCls}`}>{put ? num(put.last) : "—"}</td>
      <td className={`p-1 ${putCls}`}>{put ? num2(put.bid) : "—"}</td>
      <td className={`p-1 ${putCls}`}>{put ? num2(put.ask) : "—"}</td>
      <td className={`p-1 ${putCls}`}>{put ? (put.iv * 100).toFixed(1) : "—"}</td>
      <td className={`p-1 ${putCls}`}><Pub v={put?.volume} /></td>
      <td className={`p-1 ${putCls}`}><Pub v={put?.oi} /></td>
      <td className="p-1 whitespace-nowrap text-right">
        <div className="flex justify-end gap-1">
          <Button
            variant="outline"
            size="sm"
            className="h-6 px-1.5 text-[11px] text-positive hover:text-positive"
            disabled={!call}
            onClick={() => call && onAdd("CALL", call)}
          >
            +CE
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-6 px-1.5 text-[11px] text-negative hover:text-negative"
            disabled={!put}
            onClick={() => put && onAdd("PUT", put)}
          >
            +PE
          </Button>
        </div>
      </td>
    </tr>
  )
}

function allRows(chain: OptionChain): { strike: number; call?: OptionRow; put?: OptionRow }[] {
  const callMap = new Map(chain.calls.map((c) => [c.strike, c]))
  const putMap = new Map(chain.puts.map((p) => [p.strike, p]))
  const strikes = Array.from(new Set([...callMap.keys(), ...putMap.keys()])).sort((a, b) => a - b)
  return strikes.map((strike) => ({
    strike,
    call: callMap.get(strike),
    put: putMap.get(strike),
  }))
}

export default function OptionsPage() {
  const qc = useQueryClient()
  const [symbol, setSymbol] = useState("")
  const [loading, setLoading] = useState(false)
  const [chain, setChain] = useState<OptionChain | null>(null)
  const [selectedExpiry, setSelectedExpiry] = useState<string>("")
  const [error, setError] = useState<string | null>(null)
  const [signals, setSignals] = useState<OptionSignals | null>(null)
  const [signalsError, setSignalsError] = useState<string | null>(null)
  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [selectedStrategy, setSelectedStrategy] = useState("iron_condor")
  const [liveRefresh, setLiveRefresh] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [activeStrike, setActiveStrike] = useState<number | null>(null)
  const [activeOptionType, setActiveOptionType] = useState<"CE" | "PE">("CE")

  // Deep link support: /options?symbol=NSE:BANKNIFTY&strike=44200&expiry=2026-08-25&type=CE
  // preloads the chain and opens the F&O premium chart for that contract (used by
  // the dashboard's tracked-option "Chart" action).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const s = params.get("symbol")
    if (!s) return
    setSymbol(s)
    setActiveOptionType(params.get("type")?.toUpperCase() === "PE" ? "PE" : "CE")
    const e = params.get("expiry")
    const k = params.get("strike")
    // One-shot: load the chain then select the requested contract.
    let mounted = true
    ;(async () => {
      await fetchOptionChain(e || undefined, s)
      if (!mounted) return
      if (k && !Number.isNaN(Number(k))) setActiveStrike(Number(k))
    })()
    return () => {
      mounted = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [form, setForm] = useState<OptionPositionInput>({
    symbol: "",
    option_type: "CALL",
    strike: 0,
    expiry: "",
    quantity: 1,
    premium: 0,
  })
  const [positionMsg, setPositionMsg] = useState<string | null>(null)

  const [authenticated, setAuthenticated] = useState(false)

  useEffect(() => {
    setAuthenticated(Boolean(getAuthToken()))
  }, [])

  const { data: providerStatus } = useQuery({
    queryKey: ["market-provider-status"],
    queryFn: () => api.get<Record<string, ProviderStatusItem>>("/market/status"),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const addPosition = useMutation({
    mutationFn: (input: OptionPositionInput) => api.post<OptionPosition>("/options/positions", input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["option-positions"] })
      setPositionMsg("Position added.")
    },
    onError: (err: unknown) => setPositionMsg(errDetail(err, "Could not add position.")),
  })

  const fetchOptionChain = async (expiryOverride?: string, symOverride?: string) => {
    const target = symOverride ?? symbol
    if (!target) return

    setLoading(true)
    setError(null)
    setStrategy(null)
    setSignals(null)
    setSignalsError(null)
    try {
      const query = expiryOverride ? `?expiry=${encodeURIComponent(expiryOverride)}` : ""
      const response = await http.get(`/api/analysis/options/chain/${target}${query}`)
      const data = response.data as OptionChain
      setChain(data)
      const exp = data.expiry?.slice(0, 10) || expiryOverride || ""
      setSelectedExpiry(exp)
      setLastUpdated(new Date())
      setForm((f) => ({
        ...f,
        symbol: data.symbol,
        strike: Math.round(data.spot_price),
        expiry: exp,
      }))

      // Market signals are best-effort — never block the chain on them.
      try {
        const sigRes = await http.get(
          `/api/analysis/options/signals/${target}${query}`
        )
        setSignals(sigRes.data as OptionSignals)
      } catch (sigErr: any) {
        setSignalsError(errDetail(sigErr, "Signals unavailable for this expiry."))
      }
    } catch (err: any) {
      console.error("Failed to fetch option chain:", err)
      setChain(null)
      setError(
        errDetail(
          err,
          "No options data available for this symbol."
        )
      )
    } finally {
      setLoading(false)
    }
  }

  // Live refresh: refetch the chain + signals on a fixed cadence so price/IV
  // cells update while the page is open (underlying spot is live from Yahoo).
  useEffect(() => {
    if (!liveRefresh || !chain) return
    const id = setInterval(() => {
      fetchOptionChain(selectedExpiry).then(() =>
        setLastUpdated(new Date())
      ).catch(() => setRefreshError("Live refresh failed — pausing auto-update."))
    }, 30_000)
    return () => clearInterval(id)
  }, [liveRefresh, symbol, selectedExpiry, chain !== null])

  const analyzeStrategy = async () => {
    if (!symbol) return

    setLoading(true)
    setError(null)
    try {
      const response = await http.post(`/api/analysis/options/strategy`, null, {
        params: { symbol, strategy: selectedStrategy },
      })
      setStrategy(response.data)
    } catch (err: any) {
      console.error("Failed to analyze strategy:", err)
      setError(errDetail(err, "Could not analyze strategy for this symbol."))
    } finally {
      setLoading(false)
    }
  }

  const trackRow = (kind: "CALL" | "PUT", row: OptionRow) => {
    if (!authenticated) {
      setPositionMsg("Sign in to track option positions.")
      return
    }
    addPosition.mutate({
      symbol: chain!.symbol,
      option_type: kind,
      strike: row.strike,
      expiry: selectedExpiry || chain!.expiry?.slice(0, 10),
      quantity: 1,
      premium: mid(row),
    })
  }

  const submitForm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.symbol) return
    if (!authenticated) {
      setPositionMsg("Sign in to track option positions.")
      return
    }
    addPosition.mutate(form)
  }

  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">Options Analysis</h1>

      <AgenticTradingPanel symbol={symbol} />

      {/* Search Section */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Select Stock</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4">
            <div className="flex-1">
              <SymbolSearch onSelect={setSymbol} />
            </div>
            <Button onClick={() => fetchOptionChain()} disabled={!symbol || loading}>
              {loading ? "Loading..." : "Get Option Chain"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Chains for NSE/BSE symbols come from the TradingView options scanner — try{" "}
            <span className="font-medium">NSE:NIFTY</span>,{" "}
            <span className="font-medium">NSE:BANKNIFTY</span>,{" "}
            <span className="font-medium">NSE:SENSEX</span>, or{" "}
            <span className="font-medium">NSE:TCS</span>. US symbols (e.g.{" "}
            <span className="font-medium">NYSE:AAPL</span>) use Yahoo. Bid/ask and open interest
            are not published by the free scanner, so those cells show "—".
          </p>
        </CardContent>
      </Card>

      {/* Data provider status */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" /> Data providers
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
            {providerStatus &&
              Object.entries(providerStatus).map(([name, info]) => (
                <div key={name} className="rounded-md border border-border bg-muted/30 p-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        info.reachable ? "bg-positive" : "bg-negative"
                      }`}
                    />
                    <p className="font-medium">{info.display_name}</p>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {info.default_for.length > 0 ? "Default for " : ""}
                    <span className="text-foreground">{info.default_for.join(", ")}</span>
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {info.capabilities.includes("options_chain")
                      ? "Option chains + quotes/fundamentals"
                      : "Quotes · history · fundamentals"}
                  </p>
                  {info.notes && <p className="mt-1 text-xs text-muted-foreground">{info.notes}</p>}
                </div>
              ))}
            {!providerStatus && (
              <p className="col-span-3 text-xs text-muted-foreground">Loading provider status...</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Track Position Form */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-4 w-4" /> Track PUT / CALL Position
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!authenticated && (
            <p className="mb-3 text-sm text-muted-foreground">
              <Link href="/login" className="underline">Sign in</Link> to save option positions to your dashboard.
            </p>
          )}
          <form onSubmit={submitForm} className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <div className="col-span-2 md:col-span-1">
              <label className="mb-1 block text-xs text-muted-foreground">Symbol</label>
              <Input
                value={chain ? chain.symbol : symbol}
                readOnly
                placeholder="Load a chain first"
                onChange={() => {}}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Type</label>
              <Select
                value={form.option_type}
                onValueChange={(v) => setForm((f) => ({ ...f, option_type: v as "CALL" | "PUT" }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="CALL">CALL (CE)</SelectItem>
                  <SelectItem value="PUT">PUT (PE)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Strike</label>
              <Input
                type="number"
                step="any"
                value={form.strike || ""}
                onChange={(e) => setForm((f) => ({ ...f, strike: Number(e.target.value) }))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Expiry</label>
              <Input
                type="date"
                value={form.expiry}
                onChange={(e) => setForm((f) => ({ ...f, expiry: e.target.value }))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Qty</label>
              <Input
                type="number"
                step="any"
                value={form.quantity || ""}
                onChange={(e) => setForm((f) => ({ ...f, quantity: Number(e.target.value) }))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Premium</label>
              <Input
                type="number"
                step="any"
                value={form.premium || ""}
                onChange={(e) => setForm((f) => ({ ...f, premium: Number(e.target.value) }))}
              />
            </div>
            <div className="col-span-2 md:col-span-6">
              <Button type="submit" disabled={!chain || addPosition.isPending || !form.expiry}>
                {addPosition.isPending ? "Saving..." : "Add to My Positions"}
              </Button>
              {positionMsg && <span className="ml-3 text-sm text-muted-foreground">{positionMsg}</span>}
            </div>
          </form>
        </CardContent>
      </Card>

      <OptionPositionsWidget />


      {error && (
        <div className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          <p className="font-medium">No option chain available</p>
          <p className="mt-1">{error}</p>
        </div>
      )}

      {chain && chain.calls.length + chain.puts.length > 0 && (
        <>
          {/* Key Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Symbol</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xl font-bold">{chain.symbol}</p>
                <p className="text-xs text-muted-foreground">underlying (TradingView)</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Spot Price</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">₹{chain.spot_price.toFixed(2)}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Max Pain</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">₹{chain.max_pain?.toFixed(2) ?? "—"}</p>
                <p className="text-sm text-muted-foreground">
                  {chain.max_pain == null
                    ? "Needs open interest (not published)"
                    : chain.max_pain > chain.spot_price
                      ? "Above spot"
                      : "Below spot"}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Put-Call Ratio</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">{chain.pcr?.toFixed(2) ?? "—"}</p>
                <p className="text-sm text-muted-foreground">
                  {chain.pcr == null
                    ? "Needs open interest"
                    : chain.pcr > 1
                      ? "Bearish"
                      : "Bullish"} sentiment
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">IV Rank</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">{chain.iv_rank.toFixed(1)}%</p>
                <p className="text-sm text-muted-foreground">
                  {chain.iv_rank > 50 ? "High" : "Low"} volatility
                </p>
              </CardContent>
            </Card>
          </div>

{/* Underlying chart with selected-strike price line */}
          <Card className="mb-6">
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base">
                <LineChart className="h-4 w-4" /> Underlying Chart
              </CardTitle>
              {activeStrike != null && (
                <span className="rounded bg-muted/40 px-2 py-0.5 text-xs font-medium">
                  strike line {activeStrike}
                </span>
              )}
            </CardHeader>
            <CardContent>
              <MarketChart symbol={chain.symbol} priceLine={activeStrike} priceLineLabel="Strike" />
              <p className="mt-2 text-xs text-muted-foreground">
                Chart shows the <span className="font-medium">underlying</span> spot history (live from
                the market service) with the selected strike drawn as a reference line. Option
                <span className="font-medium"> bid/ask/OI are not published</span> by the free scanner,
                so tracked positions use the theoretical price (theo) as a proxy.
              </p>
            </CardContent>
          </Card>

          {/* Option premium chart for the selected contract */}
          {activeStrike != null && (
            <Card className="mb-6">
              <CardHeader className="pb-2 flex flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-base">
                  <LineChart className="h-4 w-4" /> Option Price — {chain.symbol}
                </CardTitle>
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-0.5 rounded-md border p-0.5">
                    {(["CE", "PE"] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setActiveOptionType(t)}
                        className={`h-7 rounded px-2.5 text-xs font-medium transition-colors ${
                          activeOptionType === t
                            ? t === "CE"
                              ? "bg-positive/15 text-positive"
                              : "bg-negative/15 text-negative"
                            : "text-muted-foreground hover:bg-muted/40"
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                  <span className="rounded bg-muted/40 px-2 py-0.5 text-xs">
                    {activeOptionType} {activeStrike}
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <OptionPremiumChart
                  symbol={chain.symbol}
                  strike={activeStrike}
                  expiry={selectedExpiry || chain.expiry}
                  optionType={activeOptionType}
                />
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <label className="text-xs text-muted-foreground">Strike:</label>
                  <Select value={String(activeStrike)} onValueChange={(v) => setActiveStrike(Number(v))}>
                    <SelectTrigger className="w-28 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="max-h-72">
                      {allRows(chain).map((r) => (
                        <SelectItem key={r.strike} value={String(r.strike)}>
                          {r.strike}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <label className="ml-2 text-xs text-muted-foreground">Expiry:</label>
                  <Select
                    value={selectedExpiry || chain.expiry?.slice(0, 10)}
                    onValueChange={(v) => fetchOptionChain(v)}
                  >
                    <SelectTrigger className="w-32 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {chain.expiries.map((d) => (
                        <SelectItem key={d} value={d.slice(0, 10)}>
                          {d.slice(0, 10)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Market signals */}
          <Card className="mb-6">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                Call / Put Market Signals
                {signals && (
                  <span className="text-xs font-normal text-muted-foreground">
                    · expiry {signals.expiry ?? "—"}
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {signalsError ? (
                <p className="text-sm text-muted-foreground">{signalsError}</p>
              ) : signals ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <div className="rounded-md bg-muted/40 p-3">
                      <p className="text-xs text-muted-foreground">Bias</p>
                      <p
                        className={`text-lg font-bold ${
                          signals.bias === "CALL"
                            ? "text-positive"
                            : signals.bias === "PUT"
                              ? "text-negative"
                              : "text-yellow-500"
                        }`}
                      >
                        {signals.bias === "CALL"
                          ? "Bullish (Calls)"
                          : signals.bias === "PUT"
                            ? "Bearish (Puts)"
                            : "Neutral"}
                      </p>
                    </div>
                    <div className="rounded-md bg-muted/40 p-3">
                      <p className="text-xs text-muted-foreground">Max Pain</p>
                      <p className="text-lg font-bold">
                        {signals.max_pain != null ? `₹${signals.max_pain.toFixed(0)}` : "—"}
                      </p>
                    </div>
                    <div className="rounded-md bg-muted/40 p-3">
                      <p className="text-xs text-muted-foreground">Premium P/C Ratio</p>
                      <p className="text-lg font-bold">
                        {signals.premium_put_call != null ? signals.premium_put_call.toFixed(2) : "—"}
                      </p>
                      <p className="text-xs text-muted-foreground">(OI not published)</p>
                    </div>
                    <div className="rounded-md bg-muted/40 p-3">
                      <p className="text-xs text-muted-foreground">IV Skew</p>
                      <p className="text-lg font-bold">
                        {signals.iv_skew != null ? (signals.iv_skew * 100).toFixed(1) + "%" : "—"}
                      </p>
                      <p className="text-xs text-muted-foreground">put IV − call IV</p>
                    </div>
                    <div className="rounded-md bg-muted/40 p-3">
                      <p className="text-xs text-muted-foreground">ATM IV</p>
                      <p className="text-lg font-bold">
                        {signals.atm_iv != null ? (signals.atm_iv * 100).toFixed(1) + "%" : "—"}
                      </p>
                    </div>
                  </div>
                  <div className="rounded-md border border-border bg-muted/40 p-4">
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {signals.strategy === "bullish"
                        ? "Bullish strategy"
                        : signals.strategy === "bearish"
                          ? "Bearish strategy"
                          : "Range-bound strategy"}
                    </p>
                    <p className="text-sm">{signals.recommendation}</p>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Loading signals…</p>
              )}
            </CardContent>
          </Card>

          {/* Expiry selector */}
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <label className="text-sm font-medium">Expiry:</label>
            {chain.expiries && chain.expiries.length > 0 ? (
              <Select value={selectedExpiry} onValueChange={(v) => fetchOptionChain(v)}>
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {chain.expiries.map((d) => (
                    <SelectItem key={d} value={d.slice(0, 10)}>
                      {d.slice(0, 10)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="text-sm text-muted-foreground">{selectedExpiry}</span>
            )}
            <span className="text-xs text-muted-foreground">
              {chain.calls.length} call strikes · {chain.puts.length} put strikes · range{" "}
              {Math.min(...chain.calls.map((c) => c.strike), ...chain.puts.map((p) => p.strike))} –{" "}
              {Math.max(...chain.calls.map((c) => c.strike), ...chain.puts.map((p) => p.strike))}
            </span>
            <span className="ml-auto flex items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={liveRefresh}
                  onChange={(e) => setLiveRefresh(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Live refresh (30s)
              </label>
              {lastUpdated && (
                <span className="text-xs text-muted-foreground">
                  updated {lastUpdated.toLocaleTimeString()}
                </span>
              )}
            </span>
            {refreshError && <p className="text-xs text-destructive">{refreshError}</p>}
          </div>

          {/* Options Chain Table */}
          <Tabs defaultValue="chain" className="mb-6">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="chain">Option Chain</TabsTrigger>
              <TabsTrigger value="strategies">Strategies</TabsTrigger>
            </TabsList>

            <TabsContent value="chain">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle>F&O — Option Chain (all strikes)</CardTitle>
                  <p className="text-xs text-muted-foreground">
                    CE (call) and PE (put) legs for every listed strike on {selectedExpiry || "the selected expiry"}.
                    The free scanner publishes option chains only — futures quotes are not listed, so this
                    covers the options side of F&O. Use +CE / +PE to track a position at the listed strike
                    and mid premium.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="max-h-[520px] overflow-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-card shadow-sm">
                        <tr className="border-b">
                          <th colSpan={6} className="text-center p-2 bg-positive/10">CALLS</th>
                          <th className="p-2 bg-muted/40">Strike</th>
                          <th colSpan={6} className="text-center p-2 bg-negative/10">PUTS</th>
                          <th className="p-2 bg-muted/40">Track</th>
                        </tr>
                        <tr className="border-b text-xs">
                          <th className="p-1">OI</th>
                          <th className="p-1">Vol</th>
                          <th className="p-1">IV</th>
                          <th className="p-1">Bid</th>
                          <th className="p-1">Ask</th>
                          <th className="p-1">Last</th>
                          <th className="p-1 bg-muted/40"></th>
                          <th className="p-1">Last</th>
                          <th className="p-1">Bid</th>
                          <th className="p-1">Ask</th>
                          <th className="p-1">IV</th>
                          <th className="p-1">Vol</th>
                          <th className="p-1">OI</th>
                          <th className="p-1 bg-muted/40"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {allRows(chain).map(({ strike, call, put }) => (
                          <ChainRow
                            key={strike}
                            call={call}
                            put={put}
                            spot={chain.spot_price}
                            onAdd={trackRow}
                            active={activeStrike === strike}
                            onSelect={setActiveStrike}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="strategies">
              <Card>
                <CardHeader>
                  <CardTitle>Option Strategies</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    <div className="flex gap-4">
                      <select
                        className="flex-1 p-2 border rounded bg-background border-border text-foreground"
                        value={selectedStrategy}
                        onChange={(e) => setSelectedStrategy(e.target.value)}
                      >
                        <option value="iron_condor">Iron Condor</option>
                        <option value="straddle">Straddle</option>
                        <option value="strangle">Strangle</option>
                        <option value="bull_call_spread">Bull Call Spread</option>
                        <option value="bear_put_spread">Bear Put Spread</option>
                        <option value="butterfly">Butterfly</option>
                        <option value="covered_call">Covered Call</option>
                      </select>
                      <Button onClick={analyzeStrategy}>
                        Analyze Strategy
                      </Button>
                    </div>

                    {strategy && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                        <Card>
                          <CardHeader>
                            <CardTitle className="text-lg">{strategy.name}</CardTitle>
                          </CardHeader>
                          <CardContent className="space-y-2">
                            <div className="flex justify-between">
                              <span>Max Profit</span>
                              <span className="font-bold text-positive">
                                ₹{strategy.max_profit.toFixed(2)}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span>Max Loss</span>
                              <span className="font-bold text-negative">
                                ₹{Math.abs(strategy.max_loss).toFixed(2)}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span>Breakeven</span>
                              <span className="font-bold">
                                {strategy.breakeven.map((b) => `₹${b.toFixed(2)}`).join(", ")}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span>Win Probability</span>
                              <span className="font-bold">
                                {(strategy.probability_profit * 100).toFixed(1)}%
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span>Expected Return</span>
                              <span className={`font-bold ${strategy.expected_return > 0 ? 'text-positive' : 'text-negative'}`}>
                                {(strategy.expected_return * 100).toFixed(1)}%
                              </span>
                            </div>
                          </CardContent>
                        </Card>

                        <Card>
                          <CardHeader>
                            <CardTitle className="text-lg">Greeks</CardTitle>
                          </CardHeader>
                          <CardContent className="space-y-2">
                            <div className="flex justify-between">
                              <span>Delta (Δ)</span>
                              <span className="font-mono">{strategy.greeks.delta.toFixed(4)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Gamma (Γ)</span>
                              <span className="font-mono">{strategy.greeks.gamma.toFixed(4)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Theta (Θ)</span>
                              <span className="font-mono">{strategy.greeks.theta.toFixed(4)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Vega (ν)</span>
                              <span className="font-mono">{strategy.greeks.vega.toFixed(4)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Rho (ρ)</span>
                              <span className="font-mono">{strategy.greeks.rho.toFixed(4)}</span>
                            </div>
                          </CardContent>
                        </Card>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  )
}
