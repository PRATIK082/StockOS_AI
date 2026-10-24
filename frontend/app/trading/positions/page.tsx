"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, Wallet } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PositionsTable } from "@/components/trading/PositionsTable"
import { StatCard } from "@/components/trading/StatCard"
import { OrderForm } from "@/components/trading/OrderForm"
import { fetchPositions, fmt, fmtCurrency, fmtPct, pnlFmt, type TerminalPosition } from "@/lib/trading"

export default function PositionsPage() {
  const [positions, setPositions] = useState<TerminalPosition[]>([])
  const [summary, setSummary] = useState({ invested: 0, value: 0, unrealised_pnl: 0, unrealised_pnl_pct: 0, count: 0 })
  const [selected, setSelected] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [refreshKey, setRefreshKey] = useState(0)
  const [flash, setFlash] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const res = await fetchPositions()
      setPositions(res.positions)
      setSummary(res.summary)
      setSelected((prev) => prev || res.positions[0]?.symbol || "")
    } catch (err) {
      setError((err as Error).message || "Failed to load positions")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Positions</h1>
        </div>
        <Button variant="outline" size="sm" onClick={() => setRefreshKey((k) => k + 1)}>
          Refresh
        </Button>
      </div>

      {flash && (
        <div className="rounded-lg border border-positive/30 bg-positive/5 px-4 py-2 text-sm text-positive">
          {flash}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-3 text-sm text-negative">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Invested" value={fmtCurrency(summary.invested)} />
        <StatCard label="Value" value={fmtCurrency(summary.value)} />
        <StatCard
          label="Unrealized P&L"
          value={pnlFmt(summary.unrealised_pnl)}
          sub={fmtPct(summary.unrealised_pnl_pct)}
          accent={summary.unrealised_pnl > 0 ? "positive" : summary.unrealised_pnl < 0 ? "negative" : "muted"}
        />
        <StatCard label="Count" value={summary.count} sub="open positions" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          {loading && !positions.length ? (
            <div className="flex justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <PositionsTable positions={positions} onSelect={setSelected} selectedSymbol={selected} />
          )}
        </div>
        <div>
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-sm font-medium">Quick Trade</CardTitle>
            </CardHeader>
            <CardContent>
              <OrderForm
                defaultSymbol={selected}
                onFilled={(msg) => {
                  setFlash(msg)
                  setRefreshKey((k) => k + 1)
                }}
              />
            </CardContent>
          </Card>
          {selected && (
            <Card className="mt-4">
              <CardHeader className="py-3">
                <CardTitle className="text-sm font-medium">{selected} details</CardTitle>
              </CardHeader>
              <CardContent>
                <DetailList position={positions.find((p) => p.symbol === selected)} />
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function DetailList({ position }: { position?: TerminalPosition }) {
  if (!position) {
    return <p className="text-sm text-muted-foreground">No live data for selection.</p>
  }
  const rows: Array<[string, string, string]> = [
    ["Quantity", String(position.quantity), ""],
    ["Avg price", fmt(position.average_price), ""],
    ["Last", fmt(position.last_price), ""],
    ["Market value", fmtCurrency(position.market_value), ""],
    ["Invested", fmtCurrency(position.invested), ""],
    ["Unrealized P&L", pnlFmt(position.unrealised_pnl), position.unrealised_pnl > 0 ? "text-positive" : position.unrealised_pnl < 0 ? "text-negative" : "text-muted-foreground"],
    ["P&L %", fmtPct(position.unrealised_pnl_pct), position.unrealised_pnl > 0 ? "text-positive" : position.unrealised_pnl < 0 ? "text-negative" : "text-muted-foreground"],
    ["Realized P&L", pnlFmt(position.realised_pnl), position.realised_pnl > 0 ? "text-positive" : position.realised_pnl < 0 ? "text-negative" : "text-muted-foreground"],
  ]
  return (
    <dl className="space-y-2 text-sm">
      {rows.map(([k, v, cls]) => (
        <div key={k} className="flex justify-between gap-2">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className={`tabular-nums font-medium ${cls}`}>{v}</dd>
        </div>
      ))}
      <div className="pt-2">
        <Badge variant="outline">{position.exchange}</Badge>
      </div>
    </dl>
  )
}