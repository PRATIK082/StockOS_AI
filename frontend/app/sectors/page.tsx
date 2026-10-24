"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Layers, TrendingUp, TrendingDown, Loader2, AlertCircle } from "lucide-react"
import { api as http } from "@/lib/api-client"

interface StockRow {
  symbol: string
  name: string
  price: number
  change_pct: number | null
  sector: string | null
  industry: string | null
  market_cap: number | null
  cap_class: string
}

interface IndustryRow {
  name: string
  count: number
  avg_change_pct: number | null
  constituents: StockRow[]
}

interface SectorRow {
  name: string
  count: number
  avg_change_pct: number | null
  top: StockRow | null
  bottom: StockRow | null
  industries: IndustryRow[]
  constituents: StockRow[]
}

interface SectorData {
  market: string
  total_symbols: number
  analyzed: number
  sectors: SectorRow[]
  caps: Record<string, StockRow[]>
  top_gainers: StockRow[]
  top_losers: StockRow[]
}

function cur(market: string): string {
  return market === "india" ? "₹" : "$"
}

function fmtChange(v: number | null): string {
  if (v == null) return "—"
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
}

function changeTone(v: number | null): string {
  if (v == null) return "text-muted-foreground"
  if (v > 0.5) return "text-positive"
  if (v < -0.5) return "text-negative"
  return "text-muted-foreground"
}

function capTone(cls: string): string {
  switch (cls) {
    case "MEGA": return "bg-purple-500/15 text-purple-500"
    case "LARGE": return "bg-blue-500/15 text-blue-500"
    case "MID": return "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400"
    case "SMALL": return "bg-emerald-500/15 text-emerald-500"
    default: return "bg-muted text-muted-foreground"
  }
}

export default function SectorsPage() {
  const [market, setMarket] = useState("india")
  const [data, setData] = useState<SectorData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [capFilter, setCapFilter] = useState<string>("ALL")

  const load = async (mkt = market) => {
    setLoading(true)
    setError(null)
    try {
      const response = await http.get(`/api/analysis/sectors?market=${mkt}`)
      setData(response.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Could not load sector analysis.")
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const switchMarket = (mkt: string) => {
    setMarket(mkt)
    load(mkt)
  }

  const capRows = (data?.caps || {})
  const capOrder = ["MEGA", "LARGE", "MID", "SMALL"]

  return (
    <div className="container mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Sector & Cap Analysis</h1>
        <div className="flex items-center gap-2">
          <Button
            variant={market === "india" ? "default" : "outline"}
            size="sm"
            onClick={() => switchMarket("india")}
          >
            India
          </Button>
          <Button
            variant={market === "us" ? "default" : "outline"}
            size="sm"
            onClick={() => switchMarket("us")}
          >
            US
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-6">
        <span className="text-sm text-muted-foreground mr-1">Cap filter:</span>
        {["ALL", "MEGA", "LARGE", "MID", "SMALL"].map((cls) => (
          <Button
            key={cls}
            variant={capFilter === cls ? "default" : "outline"}
            size="sm"
            onClick={() => setCapFilter(cls)}
          >
            {cls === "ALL" ? "All caps" : `${cls} cap`}
          </Button>
        ))}
      </div>

      <p className="text-sm text-muted-foreground mb-6">
        Sector groupings and market-cap classification computed from live quotes — never fabricated.
      </p>

      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Fetching live quotes…</span>
        </div>
      )}

      {error && !loading && (
        <div className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          <p className="font-medium flex items-center gap-2">
            <AlertCircle className="h-4 w-4" /> Unable to load sector analysis
          </p>
          <p className="mt-1">{error}</p>
        </div>
      )}

      {data && !loading && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Universe Symbols</p>
                <p className="text-2xl font-bold">{data.total_symbols}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Analyzed (live quotes)</p>
                <p className="text-2xl font-bold">{data.analyzed}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Sectors</p>
                <p className="text-2xl font-bold">{data.sectors.length}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Top Gainer</p>
                <p className="text-lg font-bold truncate">{data.top_gainers[0]?.symbol ?? "—"}</p>
              </CardContent>
            </Card>
          </div>

          {/* Top gainers / losers */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <TrendingUp className="h-4 w-4 text-positive" /> Top Gainers
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-border">
                  {data.top_gainers.map((s) => (
                    <li key={s.symbol} className="flex items-center justify-between py-2">
                      <div>
                        <p className="text-sm font-medium">{s.symbol}</p>
                        <p className="text-xs text-muted-foreground">{s.name}</p>
                      </div>
                      <span className={changeTone(s.change_pct)}>{fmtChange(s.change_pct)}</span>
                    </li>
                  ))}
                  {data.top_gainers.length === 0 && <li className="py-2 text-sm text-muted-foreground">No data</li>}
                </ul>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <TrendingDown className="h-4 w-4 text-negative" /> Top Losers
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-border">
                  {data.top_losers.map((s) => (
                    <li key={s.symbol} className="flex items-center justify-between py-2">
                      <div>
                        <p className="text-sm font-medium">{s.symbol}</p>
                        <p className="text-xs text-muted-foreground">{s.name}</p>
                      </div>
                      <span className={changeTone(s.change_pct)}>{fmtChange(s.change_pct)}</span>
                    </li>
                  ))}
                  {data.top_losers.length === 0 && <li className="py-2 text-sm text-muted-foreground">No data</li>}
                </ul>
              </CardContent>
            </Card>
          </div>

          {/* Cap classification */}
          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Layers className="h-5 w-5" />
                Market Cap Classification
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {capOrder.map((cls) => {
                  const rows = capRows[cls] || []
                  if (rows.length === 0) return null
                  return (
                    <div key={cls} className="rounded-lg border border-border p-4">
                      <div className="flex items-center justify-between mb-2">
                        <span className={`inline-flex rounded px-2 py-0.5 text-xs font-bold ${capTone(cls)}`}>
                          {cls} CAP
                        </span>
                        <span className="text-sm text-muted-foreground">{rows.length} stocks</span>
                      </div>
                      <ul className="space-y-1">
                        {rows.slice(0, 5).map((s) => (
                          <li key={s.symbol} className="flex items-center justify-between text-sm">
                            <span className="truncate">{s.symbol}</span>
                            <span className={changeTone(s.change_pct)}>{fmtChange(s.change_pct)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Sectors */}
          <Card>
            <CardHeader>
              <CardTitle>Sector Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {data.sectors
                  .map((sec) => ({
                    ...sec,
                    constituents: capFilter === "ALL" ? sec.constituents : sec.constituents.filter((s) => s.cap_class === capFilter),
                  }))
                  .filter((sec) => sec.constituents.length > 0)
                  .map((sec) => (
                    <div key={sec.name} className="rounded-lg border border-border p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-semibold">{sec.name}</p>
                          <p className="text-xs text-muted-foreground">{sec.constituents.length} constituents</p>
                        </div>
                        <span className={`text-lg font-bold ${changeTone(sec.avg_change_pct)}`}>
                          {fmtChange(sec.avg_change_pct)}
                        </span>
                      </div>

                      {/* Industry groupings */}
                      {sec.industries && sec.industries.length > 0 && (
                        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                          {sec.industries.map((ind) => {
                            const rows =
                              capFilter === "ALL"
                                ? ind.constituents
                                : ind.constituents.filter((s) => s.cap_class === capFilter)
                            if (rows.length === 0) return null
                            return (
                              <div key={ind.name} className="rounded-md bg-muted/40 p-3">
                                <div className="flex items-center justify-between mb-2">
                                  <span className="text-sm font-medium">{ind.name}</span>
                                  <span className={`text-sm font-semibold ${changeTone(ind.avg_change_pct)}`}>
                                    {fmtChange(ind.avg_change_pct)}
                                  </span>
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                  {rows.map((s) => (
                                    <span
                                      key={s.symbol}
                                      className={`inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-xs ${
                                        s.change_pct != null && s.change_pct >= 0 ? "text-positive" : "text-negative"
                                      }`}
                                      title={`${s.name} · ${s.cap_class} cap`}
                                    >
                                      {s.symbol} {fmtChange(s.change_pct)}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}

                      <div className="mt-3 flex flex-wrap gap-2">
                        {sec.constituents.map((s) => (
                          <span
                            key={s.symbol}
                            className={`inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-xs ${
                              s.change_pct != null && s.change_pct >= 0 ? "text-positive" : "text-negative"
                            }`}
                            title={s.name}
                          >
                            {s.symbol} {fmtChange(s.change_pct)}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                {data.sectors.filter(
                  (sec) => sec.constituents.filter((s) => capFilter === "ALL" || s.cap_class === capFilter).length
                ).length === 0 && (
                  <p className="py-4 text-sm text-muted-foreground">No symbols match this cap filter.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
