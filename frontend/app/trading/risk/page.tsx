"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, OctagonX, ShieldAlert, SquareX } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { StatCard } from "@/components/trading/StatCard"
import { RiskMeter } from "@/components/trading/RiskMeter"
import { api } from "@/lib/api-client"
import { fetchAnalytics, fetchPositions, fetchSettings, fmtCurrency, pnlFmt, type TerminalAnalytics } from "@/lib/trading"

export default function RiskPage() {
  const [analytics, setAnalytics] = useState<TerminalAnalytics | null>(null)
  const [openPositions, setOpenPositions] = useState(0)
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const [a, p, s] = await Promise.all([fetchAnalytics(), fetchPositions(), fetchSettings()])
      setAnalytics(a)
      setOpenPositions(p.summary.count)
      setSettings(s)
    } catch (err) {
      setError((err as Error).message || "Failed to load risk data")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function runAction(action: "kill-switch" | "square-off") {
    setBusy(action)
    setResult("")
    setError("")
    try {
      const { data } = await api.post(`/api/v1/orders/${action}`)
      const payload = Object.values(data)[0] as Record<string, unknown> | undefined
      const closed = (payload?.closed_order_ids as string[] | undefined)?.length ?? 0
      const pnl = (payload?.total_pnl as number | undefined) ?? 0
      setResult(
        `${action === "kill-switch" ? "Kill switch" : "Square off"} — ${closed} position(s) closed, realised P&L ${pnlFmt(pnl)}.`
      )
      load()
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Action failed")
    } finally {
      setBusy(null)
    }
  }

  const risk = analytics?.risk

  const lossRatio = risk && risk.max_daily_loss_rupees > 0 ? Math.abs(risk.daily_pnl_rupees) / risk.max_daily_loss_rupees : 0
  const lossPct = Math.min(100, (lossRatio * 100) || 0)

  if (loading && !analytics) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Risk</h1>
          <Badge variant="outline" className="text-positive">
            {risk?.execution_mode || "PAPER"}
          </Badge>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-3 text-sm text-negative">
          {error}
        </div>
      )}
      {result && (
        <div className="rounded-lg border border-positive/30 bg-positive/5 px-4 py-3 text-sm text-positive">
          {result}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Daily P&L today" value={pnlFmt(risk?.daily_pnl_rupees)} accent={risk && risk.daily_pnl_rupees > 0 ? "positive" : risk && risk.daily_pnl_rupees < 0 ? "negative" : "muted"} />
        <StatCard label="Open positions" value={openPositions} sub={`limit ${risk?.max_open_positions ?? "—"}`} />
        <StatCard label="Capital deployed" value={`${risk?.capital_deployed_pct?.toFixed(1) ?? "—"}%`} sub={`limit ${risk?.max_capital_deployed_percent ?? "—"}%`} />
        <StatCard label="Max order risk" value={fmtCurrency(risk?.max_order_risk_rupees)} />
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Limits vs usage</CardTitle>
        </CardHeader>
        <CardContent className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          <RiskMeter
            value={Math.abs(risk?.daily_pnl_rupees ?? 0)}
            max={risk?.max_daily_loss_rupees || 5000}
            label="Daily loss"
            dangerThreshold={0.6}
            sub={`${lossPct.toFixed(0)}% of stop used`}
          />
          <RiskMeter
            value={openPositions}
            max={risk?.max_open_positions || 20}
            label="Open positions"
            sub={`of ${risk?.max_open_positions ?? 20} max`}
          />
          <RiskMeter
            value={risk?.capital_deployed_pct ?? 0}
            max={risk?.max_capital_deployed_percent || 100}
            label="Capital deployed"
            sub={`of ${risk?.max_capital_deployed_percent ?? 100}% max`}
          />
        </CardContent>
      </Card>

      <Card className="border-negative/40">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-negative">Emergency controls</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button variant="destructive" disabled={!!busy} onClick={() => runAction("kill-switch")}>
              {busy === "kill-switch" ? <Loader2 className="h-4 w-4 animate-spin" /> : <OctagonX className="h-4 w-4" />}
              Kill switch — liquidate everything, block new orders
            </Button>
            <Button variant="outline" disabled={!!busy} onClick={() => runAction("square-off")}>
              {busy === "square-off" ? <Loader2 className="h-4 w-4 animate-spin" /> : <SquareX className="h-4 w-4" />}
              Square off all positions
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Paper simulation — closes all positions at the current market price and resets the daily P&L pot. No real
            orders are sent.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}