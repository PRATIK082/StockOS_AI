"use client"

import { useCallback, useEffect, useState } from "react"
import { Line, ResponsiveContainer, Tooltip, XAxis, YAxis, Area } from "recharts"
import { FlaskConical, Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api-client"
import { SymbolSearch } from "@/components/stock/symbol-search"
import { StatCard } from "@/components/trading/StatCard"
import { fmt, pnlFmt } from "@/lib/trading"

interface StrategyMeta {
  name: string
  description?: string
  params?: Record<string, { default?: number; min?: number; max?: number }>
}

interface BacktestResult {
  symbol: string
  strategy: string
  interval: string
  dates: string[]
  equity: number[]
  metrics: {
    total_return?: number
    cagr?: number
    sharpe?: number
    sortino?: number
    max_drawdown?: number
    win_rate?: number
    profit_factor?: number
    n_trades?: number
    volatility?: number
  }
  trades?: Array<Record<string, unknown>>
}

export default function BacktestPage() {
  const [symbol, setSymbol] = useState("NSE:NIFTY")
  const [strategies, setStrategies] = useState<StrategyMeta[]>([
    { name: "moving_average_crossover" },
  ])
  const [strategy, setStrategy] = useState("moving_average_crossover")
  const [period, setPeriod] = useState("2y")
  const [interval, setInterval] = useState("1d")
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    api
      .get<{ strategies: StrategyMeta[] }>("/api/analysis/backtest/strategies")
      .then(({ data }) => {
        const s = data.strategies || []
        if (s.length) {
          setStrategies(s)
          setStrategy(s[0].name)
        }
      })
      .catch(() => {})
  }, [])

  const run = useCallback(async () => {
    setLoading(true)
    setError("")
    setResult(null)
    try {
      const { data } = await api.post<BacktestResult>("/api/analysis/backtest", {
        symbol,
        interval,
        period,
        strategy,
        params: {},
        initial_capital: 100000,
        benchmark_symbol: null,
        run_validation: false,
        intraday: false,
      })
      setResult(data)
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Backtest failed")
    } finally {
      setLoading(false)
    }
  }, [symbol, interval, period, strategy])

  const chartData =
    result?.dates?.map((date, i) => ({ date, equity: result.equity?.[i] })) ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <FlaskConical className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Backtest</h1>
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Configure & run</CardTitle>
        </CardHeader>
        <CardContent className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <Label>Symbol</Label>
            <SymbolSearch onSelect={setSymbol} placeholder={symbol} />
          </div>
          <div className="space-y-1.5">
            <Label>Strategy</Label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
            >
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>Interval</Label>
            <select
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
            >
              {["1d", "1wk", "1mo", "1h", "15m", "5m"].map((i) => (
                <option key={i} value={i}>
                  {i}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>Period</Label>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
            >
              {["1mo", "3mo", "6mo", "1y", "2y", "5y"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="self-end">
            <Button onClick={run} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Run backtest
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-3 text-sm text-negative">
          {error}
        </div>
      )}

      {result && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="Total return"
              value={result.metrics.total_return != null ? `${fmt(result.metrics.total_return, 2)}%` : "—"}
              accent={(result.metrics.total_return ?? 0) > 0 ? "positive" : (result.metrics.total_return ?? 0) < 0 ? "negative" : "muted"}
            />
            <StatCard label="CAGR" value={result.metrics.cagr != null ? `${fmt(result.metrics.cagr, 2)}%` : "—"} />
            <StatCard label="Sharpe" value={result.metrics.sharpe != null ? fmt(result.metrics.sharpe) : "—"} />
            <StatCard label="Max drawdown" value={result.metrics.max_drawdown != null ? `${fmt(result.metrics.max_drawdown, 2)}%` : "—"} accent="negative" />
            <StatCard label="Win rate" value={result.metrics.win_rate != null ? `${fmt(result.metrics.win_rate, 2)}%` : "—"} />
            <StatCard label="Profit factor" value={result.metrics.profit_factor != null ? fmt(result.metrics.profit_factor) : "—"} />
            <StatCard label="Trades" value={result.metrics.n_trades ?? (result.trades?.length ?? 0)} />
            <StatCard label="Volatility" value={result.metrics.volatility != null ? `${fmt(result.metrics.volatility, 2)}%` : "—"} />
          </div>

          <Card>
            <CardHeader className="py-3 flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-medium">
                Equity · {result.symbol} · {result.strategy.replace(/_/g, " ")}
              </CardTitle>
              <Badge variant="outline">{result.interval}</Badge>
            </CardHeader>
            <CardContent>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <Area data={chartData} dataKey="equity">
                    <XAxis dataKey="date" hide />
                    <YAxis hide domain={["auto", "auto"]} />
                    <Tooltip
                      formatter={(v: number) => pnlFmt(v)}
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                    />
                    <Area type="monotone" dataKey="equity" stroke="var(--positive)" fill="var(--positive)" fillOpacity={0.15} />
                  </Area>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}