"use client"

import { useCallback, useEffect, useState } from "react"
import { Area, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, ComposedChart } from "recharts"
import { ChartLine, Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatCard } from "@/components/trading/StatCard"
import { fetchAnalytics, fmt, fmtCurrency, fmtPct, pnlFmt, type TerminalAnalytics } from "@/lib/trading"

export default function AnalyticsPage() {
  const [data, setData] = useState<TerminalAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      setData(await fetchAnalytics())
    } catch (err) {
      setError((err as Error).message || "Failed to load analytics")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (loading && !data) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const summary = data?.summary
  const curve = data?.equity_curve ?? []
  const holdings = data?.portfolio?.holdings ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <ChartLine className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Analytics</h1>
      </div>

      {error && (
        <div className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-3 text-sm text-negative">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Equity" value={fmtCurrency(summary?.current_equity)} />
        <StatCard
          label="Returns"
          value={fmtPct(summary?.pnl_pct)}
          accent={summary && summary.pnl_pct > 0 ? "positive" : summary && summary.pnl_pct < 0 ? "negative" : "muted"}
        />
        <StatCard
          label="Max drawdown"
          value={`${fmt(summary?.max_drawdown_pct)}%`}
          accent="negative"
        />
        <StatCard label="Filled orders" value={summary?.n_filled_orders ?? 0} />
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Equity curve (reconstructed from order fills)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <Area data={curve} dataKey="equity">
                <XAxis dataKey="date" hide />
                <YAxis hide domain={["auto", "auto"]} />
                <Tooltip
                  formatter={(v: number) => fmtCurrency(v)}
                  labelFormatter={(l) => `Date: ${l}`}
                  contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                />
                <Area type="monotone" dataKey="equity" stroke="var(--positive)" fill="var(--positive)" fillOpacity={0.15} strokeWidth={2} />
              </Area>
            </ResponsiveContainer>
          </div>
          {curve.length <= 1 && (
            <p className="text-sm text-muted-foreground mt-3">
              No realised fills yet — the curve will grow as your paper trades settle.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-medium">Drawdown %</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={curve}>
                  <XAxis dataKey="date" hide />
                  <YAxis hide domain={["auto", 0]} />
                  <Tooltip
                    formatter={(v: number) => `${fmt(v)}%`}
                    contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="drawdown" stroke="var(--negative)" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-medium">Holdings allocation</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {holdings.length === 0 ? (
              <p className="px-6 py-6 text-sm text-muted-foreground">
                No holdings in your portfolio yet. Add via portfolio or paper trades.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {holdings.map((h) => {
                  const invested = (h.invested as number) || 0
                  const totalInv = data?.portfolio?.summary?.invested || 1
                  const pct = (invested / totalInv) * 100
                  const pnl = (h.pnl as number) || 0
                  return (
                    <li key={h.id as string} className="flex items-center gap-3 px-6 py-2.5 text-sm">
                      <div className="w-36 truncate font-medium">{h.symbol as string}</div>
                      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                        <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
                      </div>
                      <div className="w-16 text-right tabular-nums text-muted-foreground">{pct.toFixed(0)}%</div>
                      <div className={`w-24 text-right tabular-nums ${pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-muted-foreground"}`}>
                        {pnlFmt(pnl)}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}