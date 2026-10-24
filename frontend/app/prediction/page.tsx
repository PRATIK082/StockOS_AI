"use client"

import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Markdown from "@/components/ui/Markdown"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SymbolSearch } from "@/components/stock/symbol-search"
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel"
import { TrendingUp, TrendingDown, AlertCircle, Target, BadgeDollarSign, Activity, History, Trash2 } from "lucide-react"
import { api as http } from "@/lib/api-client"
import { api, getAuthToken, type OptionPosition } from "@/lib/api"

interface PredictionResult {
  symbol: string
  timeframe: string
  current_price: number
  predicted_price: number
  confidence: number
  expected_return: number
  bear_case: number
  base_case: number
  bull_case: number
  reasoning: string
  factors: Record<string, number>
  action: string
  horizon: string
  trading_stats: Record<string, any>
}

interface PredictionHistoryItem {
  id: string
  symbol: string
  timeframe: string
  payload: PredictionResult
  created_at: string | null
}

const ACTION_STYLES: Record<string, string> = {
  BUY: "bg-positive/15 text-positive border border-positive/30",
  SELL: "bg-negative/15 text-negative border border-negative/30",
  HOLD: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30",
}

function actionStyle(action: string): string {
  return ACTION_STYLES[action] || ACTION_STYLES.HOLD
}

function errDetail(err: any, fallback: string): string {
  if (err?.response?.data?.detail) return String(err.response.data.detail)
  if (err?.message && err.message !== "Request failed with status code 404") return err.message
  return fallback
}

function currencySymbol(symbol: string): string {
  const ex = (symbol || "").split(":")[0]
  return ["NSE", "BSE", "BOM", "NSEFO", "BSEFO"].includes(ex) ? "₹" : "$"
}

interface OptionSnapshot {
  bias: string
  strategy: string
  recommendation?: string | null
  max_pain?: number | null
  iv_skew?: number | null
  atm_iv?: number | null
  avg_iv?: number | null
  premium_put_call?: number | null
  spot_price?: number | null
  expiry?: string | null
}

const OPTION_BIAS_STYLES: Record<string, string> = {
  CALL: "bg-positive/15 text-positive border border-positive/30",
  PUT: "bg-negative/15 text-negative border border-negative/30",
  NEUTRAL: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30",
}

function biasStyle(bias: string): string {
  return OPTION_BIAS_STYLES[bias] || OPTION_BIAS_STYLES.NEUTRAL
}

export default function PredictionPage() {
  const [symbol, setSymbol] = useState("")
  const [timeframe, setTimeframe] = useState("1W")
  const [optionType, setOptionType] = useState("")
  const [strike, setStrike] = useState("")
  const [expiry, setExpiry] = useState("")
  const [loading, setLoading] = useState(false)
  const [prediction, setPrediction] = useState<PredictionResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [authenticated, setAuthenticated] = useState(false)

  useEffect(() => {
    setAuthenticated(Boolean(getAuthToken()))
  }, [])
  const qc = useQueryClient()
  const { data: positions } = useQuery({
    queryKey: ["option-positions"],
    queryFn: () => api.get<OptionPosition[]>("/options/positions"),
    retry: false,
    enabled: authenticated,
  })

  const { data: history } = useQuery({
    queryKey: ["prediction-history"],
    queryFn: () => api.get<PredictionHistoryItem[]>("/predictions"),
    retry: false,
    enabled: authenticated,
  })

  const deleteHistory = useMutation({
    mutationFn: (id: string) => api.del(`/predictions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prediction-history"] }),
  })

  // Load the real chain so Strike/Expiry become populated dropdowns — as soon
  // as a symbol with a chain is picked, every available strike and expiry is
  // selectable (honest, driven by the provider's chain, never fabricated).
  const chainQuery = useQuery({
    queryKey: ["option-chain-prediction", symbol],
    queryFn: () =>
      api
        .get<{ expiries: string[]; calls: { strike: number }[]; puts: { strike: number }[] }>(
          `/analysis/options/chain/${encodeURIComponent(symbol)}`
        )
        .catch(() => null),
    enabled: Boolean(symbol),
    staleTime: 2 * 60 * 1000,
    retry: 1,
  })
  const chainStrikes = Array.from(
    new Set([
      ...(chainQuery.data?.calls.map((c) => c.strike) ?? []),
      ...(chainQuery.data?.puts.map((p) => p.strike) ?? []),
    ])
  ).sort((a, b) => a - b)
  const chainExpiries = chainQuery.data?.expiries ?? []

  const handlePredict = async (sym?: string, optType?: string, stk?: string, exp?: string) => {
    const target = sym ?? symbol
    if (!target) return

    setLoading(true)
    setError(null)
    setPrediction(null)
    try {
      const params = new URLSearchParams({ timeframe })
      const t = optType ?? optionType
      const s = stk ?? strike
      const e = exp ?? expiry
      if (t) params.set("option_type", t)
      if (s && !Number.isNaN(Number(s))) params.set("strike", String(Number(s)))
      if (e) params.set("expiry", e)
      const response = await http.post(`/api/analysis/predict/${target}?${params.toString()}`)
      setPrediction(response.data)
      qc.invalidateQueries({ queryKey: ["prediction-history"] })
    } catch (err: any) {
      console.error("Prediction failed:", err)
      setError(
        errDetail(
          err,
          "Could not generate a prediction for this symbol. Try a stock with price history, e.g. NSE:RELIANCE."
        )
      )
    } finally {
      setLoading(false)
    }
  }

  // Deep link support: /prediction?symbol=NSE:NIFTY&option_type=CE&strike=18650&expiry=2026-08-11
  // prefills the form and predicts the contract (used by the tracked F&O widget).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const s = params.get("symbol")
    if (!s) return
    const t = params.get("option_type")?.toUpperCase()
    const k = params.get("strike")
    const e = params.get("expiry")
    setSymbol(s)
    if (t === "CE" || t === "PE") setOptionType(t)
    if (k && !Number.isNaN(Number(k))) setStrike(String(Number(k)))
    if (e) setExpiry(e.slice(0, 10))
    handlePredict(s, t === "PE" ? "PE" : "CE", k ?? undefined, e?.slice(0, 10))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const getReturnColor = (value: number) => {
    if (value > 5) return "text-positive"
    if (value > 0) return "text-positive"
    if (value > -5) return "text-yellow-500"
    return "text-negative"
  }

  const getConfidenceColor = (value: number) => {
    if (value > 0.8) return "bg-positive"
    if (value > 0.6) return "bg-yellow-500"
    return "bg-negative"
  }

  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">AI Price Prediction</h1>

      <AgenticTradingPanel symbol={symbol} />

      {/* Input Section */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Select Stock and Timeframe</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4">
            <div className="flex-1">
              <SymbolSearch onSelect={setSymbol} />
            </div>
            <Select value={timeframe} onValueChange={setTimeframe}>
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1D">Tomorrow</SelectItem>
                <SelectItem value="1W">1 Week</SelectItem>
                <SelectItem value="1M">1 Month</SelectItem>
                <SelectItem value="3M">3 Months</SelectItem>
                <SelectItem value="6M">6 Months</SelectItem>
                <SelectItem value="1Y">1 Year</SelectItem>
                <SelectItem value="3Y">3 Years</SelectItem>
                <SelectItem value="5Y">5 Years</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={() => handlePredict()} disabled={!symbol || loading}>
              {loading ? "Predicting..." : "Predict"}
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Type (optional)</label>
              <Select value={optionType} onValueChange={setOptionType}>
                <SelectTrigger className="w-32">
                  <SelectValue placeholder="CE / PE" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="CE">CALL (CE)</SelectItem>
                  <SelectItem value="PE">PUT (PE)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Strike (optional)</label>
              <Select
                value={strike}
                onValueChange={setStrike}
                disabled={chainStrikes.length === 0}
              >
                <SelectTrigger className="w-36">
                  <SelectValue placeholder="Pick strike" />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {chainStrikes.length === 0 && (
                    <SelectItem value="__none__" disabled>
                      {chainQuery.isLoading ? "Loading chain…" : "No chain for this symbol"}
                    </SelectItem>
                  )}
                  {chainStrikes.map((s) => (
                    <SelectItem key={s} value={String(s)}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Expiry (optional)</label>
              <Select
                value={expiry}
                onValueChange={setExpiry}
                disabled={chainExpiries.length === 0}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Pick expiry" />
                </SelectTrigger>
                <SelectContent>
                  {chainExpiries.length === 0 && (
                    <SelectItem value="__none__" disabled>
                      {chainQuery.isLoading ? "Loading chain…" : "No chain for this symbol"}
                    </SelectItem>
                  )}
                  {chainExpiries.map((d) => (
                    <SelectItem key={d} value={d.slice(0, 10)}>
                      {d.slice(0, 10)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="flex-1 text-xs text-muted-foreground">
              When a strike + type are set, the engine predicts the{" "}
              <span className="font-medium">option premium</span> (CE/PE) together with the{" "}
              <span className="font-medium">underlying index</span> — both views are shown.
            </p>
          </div>
        </CardContent>
      </Card>

      {positions && positions.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-sm">Predict from your tracked options</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {positions.map((p) => (
                <Button
                  key={p.id}
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSymbol(p.symbol)
                    setOptionType(p.option_type === "PUT" ? "PE" : "CE")
                    setStrike(String(p.strike))
                    setExpiry(p.expiry?.slice(0, 10) ?? "")
                    handlePredict(
                      p.symbol,
                      p.option_type === "PUT" ? "PE" : "CE",
                      String(p.strike),
                      p.expiry?.slice(0, 10)
                    )
                  }}
                >
                  <span
                    className={`mr-1 inline-flex rounded px-1 py-0 text-[11px] font-medium ${
                      p.option_type === "CALL" ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative"
                    }`}
                  >
                    {p.option_type === "CALL" ? "CE" : "PE"}
                  </span>
                  {p.symbol} @ {p.strike}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {error && (
        <div className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          <p className="font-medium">Unable to generate prediction</p>
          <p className="mt-1">{error}</p>
        </div>
      )}

      {authenticated && history && history.length > 0 && (
        <Card className="mb-6">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <History className="h-4 w-4" /> Prediction History
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y rounded-md border">
              {history.slice(0, 30).map((h) => {
                const p = h.payload
                return (
                  <li key={h.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      {p.action && (
                        <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-bold ${actionStyle(p.action)}`}>
                          {p.action}
                        </span>
                      )}
                      <span className="font-medium">{h.symbol}</span>
                      <span className="text-muted-foreground">
                        {h.timeframe} · {currencySymbol(h.symbol)}
                        {typeof p.predicted_price === "number" ? p.predicted_price.toFixed(2) : "—"} ·{" "}
                        {h.created_at?.slice(0, 16).replace("T", " ")}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7"
                        onClick={() => {
                          setPrediction(p)
                          setError(null)
                          window.scrollTo({ top: 0, behavior: "smooth" })
                        }}
                      >
                        View
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => deleteHistory.mutate(h.id)}
                        aria-label={`Delete prediction for ${h.symbol}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Predictions are saved to your account automatically and stay available here until you delete them.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Prediction Results */}
      {prediction && (
        <>
          {/* Main Prediction Card */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="h-5 w-5" />
                  Price Target
                  {prediction.action && (
                    <span className={`ml-2 inline-flex items-center rounded px-2 py-0.5 text-xs font-bold ${actionStyle(prediction.action)}`}>
                      {prediction.action} · {prediction.horizon}
                    </span>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div>
                    <p className="text-sm text-muted-foreground">Current Price</p>
                    <p className="text-2xl font-bold">{currencySymbol(prediction.symbol)}{prediction.current_price.toFixed(2)}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Predicted Price</p>
                    <p className={`text-2xl font-bold ${getReturnColor(prediction.expected_return)}`}>
                      {currencySymbol(prediction.symbol)}{prediction.predicted_price.toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Expected Return</p>
                    <p className={`text-lg font-semibold ${getReturnColor(prediction.expected_return)}`}>
                      {prediction.expected_return > 0 ? "+" : ""}{(prediction.expected_return * 100).toFixed(2)}%
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Scenarios</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="flex items-center gap-2">
                      <TrendingUp className="h-4 w-4 text-positive" />
                      Bull Case
                    </span>
                    <span className="font-semibold">{currencySymbol(prediction.symbol)}{prediction.bull_case.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Base Case</span>
                    <span className="font-semibold">{currencySymbol(prediction.symbol)}{prediction.base_case.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="flex items-center gap-2">
                      <TrendingDown className="h-4 w-4 text-negative" />
                      Bear Case
                    </span>
                    <span className="font-semibold">{currencySymbol(prediction.symbol)}{prediction.bear_case.toFixed(2)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5" />
                  Confidence Level
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <div className="flex justify-between mb-2">
                      <span>Model Confidence</span>
                      <span>{(prediction.confidence * 100).toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-muted rounded-full h-2">
                      <div 
                        className={`h-2 rounded-full ${getConfidenceColor(prediction.confidence)}`}
                        style={{ width: `${prediction.confidence * 100}%` }}
                      />
                    </div>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Based on technical, fundamental, and sentiment analysis
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Trading Statistics */}
          {prediction.trading_stats && Object.keys(prediction.trading_stats).length > 0 && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle>Real Trading Data</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {(() => {
                    const s = prediction.trading_stats
                    const cells: Array<{ label: string; value: string; tone?: "pos" | "neg" | "warn" }> = []
                    cells.push({
                      label: "Trading Days",
                      value: s.trading_days != null ? String(s.trading_days) : "—",
                    })
                    if (s.up_days != null && s.down_days != null) {
                      const upWins = (s.up_days ?? 0) >= (s.down_days ?? 0)
                      cells.push({
                        label: "Up / Down Days",
                        value: `${s.up_days} / ${s.down_days}`,
                        tone: upWins ? "pos" : "neg",
                      })
                    }
                    if (s.up_ratio != null)
                      cells.push({
                        label: "Up-Day Ratio",
                        value: `${(s.up_ratio * 100).toFixed(0)}%`,
                        tone: s.up_ratio > 0.55 ? "pos" : s.up_ratio < 0.45 ? "neg" : "warn",
                      })
                    if (s.avg_volume)
                      cells.push({ label: "Avg Volume", value: Number(s.avg_volume).toLocaleString() })
                    if (s.volume_trend != null)
                      cells.push({
                        label: "Volume Trend (5d)",
                        value: `${(s.volume_trend * 100).toFixed(0)}%`,
                        tone: s.volume_trend > 1.15 ? "pos" : s.volume_trend < 0.85 ? "warn" : undefined,
                      })
                    if (s.atr)
                      cells.push({ label: "ATR", value: Number(s.atr).toFixed(2) })
                    if (s.range_52w_position != null)
                      cells.push({
                        label: "52W Range Position",
                        value: `${(s.range_52w_position * 100).toFixed(0)}%`,
                        tone: s.range_52w_position > 0.7 ? "pos" : s.range_52w_position < 0.3 ? "neg" : undefined,
                      })
                    if (s.low_52w != null && s.high_52w != null)
                      cells.push({
                        label: "52W Low / High",
                        value: `${currencySymbol(prediction.symbol)}${Number(s.low_52w).toFixed(0)} / ${currencySymbol(prediction.symbol)}${Number(s.high_52w).toFixed(0)}`,
                      })
                    if (s.volatility != null)
                      cells.push({ label: "Volatility", value: `${(s.volatility * 100).toFixed(1)}%` })
                    if (s.cap_class && s.cap_class !== "n/a")
                      cells.push({ label: "Cap Class", value: s.cap_class })
                    if (s.price_band) cells.push({ label: "Price Band", value: s.price_band })
                    if (s.sector) cells.push({ label: "Sector", value: String(s.sector) })
                    if (s.industry) cells.push({ label: "Industry", value: String(s.industry) })
                    if (s.last_expiry) cells.push({ label: "Nearest Expiry", value: String(s.last_expiry) })
                    return cells.map((c) => (
                      <div key={c.label} className="rounded-md bg-muted/40 p-3">
                        <p className="text-xs text-muted-foreground">{c.label}</p>
                        <p
                          className={`text-sm font-semibold ${
                            c.tone === "pos" ? "text-positive" : c.tone === "neg" ? "text-negative" : c.tone === "warn" ? "text-yellow-500" : "text-foreground"
                          }`}
                        >
                          {c.value}
                        </p>
                      </div>
                    ))
                  })()}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Option contract (CE/PE at a strike) view */}
          {prediction.trading_stats?.option_leg && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BadgeDollarSign className="h-5 w-5" />
                  {prediction.trading_stats.option_leg.option_type} Contract Analysis @{" "}
                  {prediction.trading_stats.option_leg.strike}
                  {prediction.trading_stats.option_leg.expiry
                    ? ` · ${String(prediction.trading_stats.option_leg.expiry).slice(0, 10)}`
                    : ""}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {(() => {
                  const leg = prediction.trading_stats.option_leg
                  const cells: Array<{ label: string; value: string; tone?: string }> = [
                    { label: "Current Premium", value: `${currencySymbol(prediction.symbol)}${Number(leg.current_premium).toFixed(2)}` },
                    { label: "Predicted Premium", value: `${currencySymbol(prediction.symbol)}${Number(leg.predicted_premium).toFixed(2)}`, tone: Number(leg.predicted_premium) > Number(leg.current_premium) ? "text-positive" : "text-negative" },
                    { label: "Underlying Spot", value: `${currencySymbol(prediction.symbol)}${Number(leg.spot_price).toFixed(2)}` },
                    { label: "Moneyness", value: leg.moneyness != null ? `${(Number(leg.moneyness) * 100).toFixed(1)}%` : "—" },
                    { label: "IV", value: leg.iv != null ? `${(Number(leg.iv) * 100).toFixed(1)}%` : "—" },
                    { label: "Delta", value: leg.delta != null ? Number(leg.delta).toFixed(2) : "—" },
                    { label: "Gamma", value: leg.gamma != null ? Number(leg.gamma).toFixed(2) : "—" },
                    { label: "Theta", value: leg.theta != null ? Number(leg.theta).toFixed(2) : "—" },
                    { label: "Vega", value: leg.vega != null ? Number(leg.vega).toFixed(2) : "—" },
                    { label: "Expected Return", value: `${(Number(leg.expected_return) * 100).toFixed(1)}%`, tone: Number(leg.expected_return) > 0 ? "text-positive" : "text-negative" },
                  ]
                  const under = prediction.trading_stats.underlying
                  return (
                    <>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                        {cells.map((c) => (
                          <div key={c.label} className="rounded-md bg-muted/40 p-3">
                            <p className="text-xs text-muted-foreground">{c.label}</p>
                            <p className={`text-sm font-semibold ${c.tone || "text-foreground"}`}>{c.value}</p>
                          </div>
                        ))}
                      </div>
                      {under && (
                        <div className="mb-4 rounded-md border border-border bg-muted/40 p-3 text-sm">
                          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Underlying Index</p>
                          <p className="mt-1 font-medium">
                            {under.symbol} · spot {currencySymbol(prediction.symbol)}
                            {Number(under.current_price).toFixed(2)} → target med{" "}
                            {prediction.predicted_price != null ? Number(under.predicted_price).toFixed(2) : "—"}
                          </p>
                        </div>
                      )}
                      <div className="rounded-md border border-border bg-accent/10 p-3 text-sm">
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-1">Option vs Index</p>
                        <p className="text-muted-foreground">
                          The engine analyses the <span className="font-medium text-foreground">underlying index</span>{" "}
                          {prediction.symbol} (spot {under ? Number(under.current_price).toFixed(2) : "—"}) and prices
                          this {leg.option_type} at strike {leg.strike} through its delta. Both views are shown:
                          the algorithm's quantitative note plus the LLM Stock Analysis agent appears under
                          "AI Analysis &amp; Reasoning" below.
                        </p>
                      </div>
                    </>
                  )
                })()}
              </CardContent>
            </Card>
          )}

          {/* Options Market (Call/Put) View */}
          {prediction.trading_stats?.options && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BadgeDollarSign className="h-5 w-5" />
                  Options Market View (Call/Put)
                </CardTitle>
              </CardHeader>
              <CardContent>
                {(() => {
                  const o: OptionSnapshot = prediction.trading_stats.options
                  const rows: Array<{ label: string; value: string; tone?: string }> = []
                  if (o.bias)
                    rows.push({ label: "Option Bias", value: o.bias })
                  if (o.expiry) rows.push({ label: "Expiry", value: String(o.expiry) })
                  if (o.spot_price != null)
                    rows.push({ label: "Underlying Spot", value: `${currencySymbol(prediction.symbol)}${Number(o.spot_price).toFixed(2)}` })
                  if (o.max_pain != null)
                    rows.push({ label: "Max Pain", value: `${currencySymbol(prediction.symbol)}${Number(o.max_pain).toFixed(0)}` })
                  if (o.atm_iv != null)
                    rows.push({ label: "ATM IV", value: o.atm_iv > 1 ? `${(Number(o.atm_iv) * 100).toFixed(0)}%` : `${(Number(o.atm_iv) * 100).toFixed(1)}%` })
                  if (o.iv_skew != null)
                    rows.push({
                      label: "IV Skew (OTM P − OTM C)",
                      value: `${o.iv_skew > 0 ? "+" : ""}${Number(o.iv_skew).toFixed(3)}`,
                      tone: Number(o.iv_skew) > 0.02 ? "text-negative" : Number(o.iv_skew) < -0.02 ? "text-positive" : undefined,
                    })
                  if (o.premium_put_call != null)
                    rows.push({
                      label: "Premium P/C Ratio",
                      value: Number(o.premium_put_call).toFixed(2),
                      tone: Number(o.premium_put_call) > 1.1 ? "text-negative" : Number(o.premium_put_call) < 0.9 ? "text-positive" : undefined,
                    })
                  if (o.strategy) rows.push({ label: "Strategy", value: String(o.strategy) })
                  return (
                    <>
                      {rows.length > 0 && (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                          {rows.map((r) => (
                            <div key={r.label} className="rounded-md bg-muted/40 p-3">
                              <p className="text-xs text-muted-foreground">{r.label}</p>
                              <p className={`text-sm font-semibold ${r.label === "Option Bias" ? biasStyle(r.value) + " inline-block rounded px-2 py-0.5 mt-1" : r.tone || "text-foreground"}`}>
                                {r.value}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                      {o.recommendation && (
                        <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
                          <p className="flex items-start gap-2">
                            <Activity className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                            <span>{o.recommendation}</span>
                          </p>
                        </div>
                      )}
                    </>
                  )
                })()}
              </CardContent>
            </Card>
          )}

          {/* Analysis Factors */}
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>Analysis Factors</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                {Object.entries(prediction.factors).map(([key, value]) => (
                  <div key={key} className="text-center">
                    <p className="text-sm text-muted-foreground capitalize">{key.replace(/_/g, ' ')}</p>
                    <p className={`text-lg font-semibold ${value > 0.6 ? 'text-positive' : value < 0.4 ? 'text-negative' : 'text-yellow-500'}`}>
                      {(value * 100).toFixed(1)}%
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* AI Reasoning */}
          <Card>
            <CardHeader>
              <CardTitle>AI Analysis & Reasoning</CardTitle>
            </CardHeader>
            <CardContent>
              <Markdown className="text-sm">{prediction.reasoning}</Markdown>
              <div className="mt-4 p-4 bg-yellow-500/10 border border-yellow-500/30 rounded">
                <p className="text-sm text-yellow-600 dark:text-yellow-400">
                  <strong>Disclaimer:</strong> This is an AI-generated analysis for research purposes only. 
                  Not investment advice. All predictions carry risk. Please do your own research before making investment decisions.
                </p>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}