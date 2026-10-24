"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, Radar } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api-client"
import { fmt, fmtPct } from "@/lib/trading"
import { cn } from "@/lib/utils"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const SCANNER_TYPES = [
  { value: "breakout", label: "Breakout" },
  { value: "breakdown", label: "Breakdown" },
  { value: "momentum", label: "Momentum" },
  { value: "volume_spike", label: "Volume spike" },
  { value: "52_week_high", label: "52-week high" },
  { value: "52_week_low", label: "52-week low" },
  { value: "gap_up", label: "Gap up" },
  { value: "gap_down", label: "Gap down" },
  { value: "strong_fundamentals", label: "Strong fundamentals" },
  { value: "value_picks", label: "Value picks" },
  { value: "growth_stocks", label: "Growth" },
  { value: "quality_stocks", label: "Quality" },
  { value: "swing_candidates", label: "Swing" },
  { value: "intraday_candidates", label: "Intraday" },
  { value: "options_candidates", label: "Options" },
]

interface ScanRow {
  symbol: string
  name: string
  price: number
  change_pct: number
  volume: number
  signal_strength: number
  matched_criteria: string[]
}

export default function ScannerPage() {
  const [type, setType] = useState("momentum")
  const [market, setMarket] = useState("india")
  const [rows, setRows] = useState<ScanRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const run = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const { data } = await api.get<{ results: ScanRow[] }>(`/api/analysis/scan/${type}`, {
        params: { market, limit: 20 },
      })
      setRows(data.results || [])
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Scan failed")
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [type, market])

  useEffect(() => {
    run()
  }, [run])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radar className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Scanner</h1>
        </div>
        <div className="flex items-center gap-2">
          <Select value={market} onValueChange={setMarket}>
            <SelectTrigger className="w-28 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="india">India</SelectItem>
              <SelectItem value="us">US</SelectItem>
            </SelectContent>
          </Select>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="w-40 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SCANNER_TYPES.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" onClick={run} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />} Scan
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-3 text-sm text-negative">
          {error}
        </div>
      )}

      <Card>
        <CardHeader className="py-3 flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Results · {type.replace(/_/g, " ")}</CardTitle>
          <span className="text-xs text-muted-foreground">{rows.length} matches</span>
        </CardHeader>
        <CardContent className="p-0">
          {loading && !rows.length ? (
            <div className="flex justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <p className="px-6 py-10 text-sm text-muted-foreground text-center">No matches for this scan.</p>
          ) : (
            <ul className="divide-y divide-border">
              {rows.map((r) => (
                <li key={r.symbol} className="px-6 py-3 flex items-center gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{r.symbol}</span>
                      <span className="text-xs text-muted-foreground truncate hidden sm:block">{r.name}</span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {r.matched_criteria.slice(0, 3).map((c) => (
                        <span key={c} className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="tabular-nums font-medium">{fmt(r.price)}</div>
                    <div className={cn("text-xs tabular-nums", r.change_pct >= 0 ? "text-positive" : "text-negative")}>
                      {fmtPct(r.change_pct)}
                    </div>
                  </div>
                  <div className="shrink-0 text-right text-xs text-muted-foreground w-20">
                    vol {fmt(r.volume, 0)}
                  </div>
                  <div className="shrink-0 w-24">
                    <div className="flex items-center gap-1.5">
                      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full bg-primary"
                          style={{ width: `${Math.min(100, r.signal_strength * 100)}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-muted-foreground tabular-nums">
                        {(r.signal_strength * 100).toFixed(0)}
                      </span>
                    </div>
                    <Badge variant="outline" className="mt-1 h-5 px-1.5 text-[10px]">
                      strength
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Scans run on real quotes/history/fundamentals. Symbols with fewer than 30 candles are skipped.
      </p>
    </div>
  )
}