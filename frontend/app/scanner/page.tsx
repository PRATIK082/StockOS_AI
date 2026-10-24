"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { TrendingUp, TrendingDown, Activity, Zap, DollarSign, Gauge, Gem, Target, AlertTriangle } from "lucide-react"
import { api } from "@/lib/api-client"

interface ScanResult {
  symbol: string
  name: string
  price: number
  change_pct: number
  volume: number
  signal_strength: number
  matched_criteria: string[]
}

const SCANNER_TYPES = [
  { value: "breakout", label: "Breakout", icon: TrendingUp, desc: "Stocks breaking out above resistance with rising volume" },
  { value: "breakdown", label: "Breakdown", icon: TrendingDown, desc: "Stocks breaking down below support with rising volume" },
  { value: "momentum", label: "Momentum", icon: Activity, desc: "Stocks showing strong, sustained momentum" },
  { value: "volume_spike", label: "Volume Spike", icon: Zap, desc: "Stocks with unusually high trading volume" },
  { value: "52_week_high", label: "52 Week High", icon: TrendingUp, desc: "Stocks at or near their 52-week high" },
  { value: "52_week_low", label: "52 Week Low", icon: TrendingDown, desc: "Stocks at or near their 52-week low" },
  { value: "gap_up", label: "Gap Up", icon: TrendingUp, desc: "Stocks that gapped up at the open" },
  { value: "gap_down", label: "Gap Down", icon: TrendingDown, desc: "Stocks that gapped down at the open" },
  { value: "strong_fundamentals", label: "Strong Fundamentals", icon: Gauge, desc: "Stocks with broad fundamental strength (ROE, margins, growth)" },
  { value: "value_picks", label: "Value Picks", icon: DollarSign, desc: "Undervalued stocks based on valuation multiples" },
  { value: "growth_stocks", label: "Growth Stocks", icon: TrendingUp, desc: "High-growth companies with strong fundamentals" },
  { value: "quality_stocks", label: "Quality Stocks", icon: Gem, desc: "High-quality compounders: strong ROE, margins, low leverage" },
  { value: "swing_candidates", label: "Swing Trade", icon: Activity, desc: "Stocks suitable for swing trading (2-5 days)" },
  { value: "intraday_candidates", label: "Intraday", icon: Zap, desc: "High-volatility stocks for intraday trading" },
  { value: "options_candidates", label: "Options Candidates", icon: Target, desc: "Liquid, trending underlyings suitable for options" },
]

export default function ScannerPage() {
  const [scannerType, setScannerType] = useState("breakout")
  const [market, setMarket] = useState("india")
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<ScanResult[]>([])
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const runScan = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await api.get(`/api/analysis/scan/${scannerType}`, {
        params: { market, limit: 20 }
      })
      setResults(response.data.results || [])
    } catch (err: any) {
      console.error("Scan failed:", err)
      const detail = err?.response?.data?.detail
      setError(detail ? String(detail) : "Could not run the scan. Check the backend connection.")
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    runScan()
  }, [scannerType, market])

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(runScan, 30000)
      return () => clearInterval(interval)
    }
  }, [autoRefresh, scannerType, market])

  const getSignalColor = (strength: number) => {
    if (strength > 0.7) return "bg-positive"
    if (strength > 0.5) return "bg-yellow-500"
    return "bg-orange-500"
  }

  const currencySymbol = market === "india" ? "₹" : "$"

  return (
    <div className="container mx-auto p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Market Scanner</h1>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded"
            />
            <span>Auto-refresh</span>
          </label>
        </div>
      </div>

      {/* Controls */}
      <Card className="mb-6">
        <CardContent className="pt-6">
          <div className="flex flex-wrap gap-4">
            <Select value={scannerType} onValueChange={setScannerType}>
              <SelectTrigger className="w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SCANNER_TYPES.map(type => (
                  <SelectItem key={type.value} value={type.value}>
                    <div className="flex items-center gap-2">
                      <type.icon className="h-4 w-4" />
                      {type.label}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={market} onValueChange={setMarket}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="india">India</SelectItem>
                <SelectItem value="us">US</SelectItem>
              </SelectContent>
            </Select>

            <Button onClick={runScan} disabled={loading}>
              {loading ? "Scanning..." : "Run Scan"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Scanner Type Description */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-lg">
            {SCANNER_TYPES.find(t => t.value === scannerType)?.label} Scanner
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {SCANNER_TYPES.find(t => t.value === scannerType)?.desc}
          </p>
        </CardContent>
      </Card>

      {error && (
        <Card className="mb-6 border-destructive/50">
          <CardContent className="flex items-center gap-3 py-4 text-sm text-destructive">
            <AlertTriangle className="h-5 w-5" />
            <span>{error}</span>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {loading ? (
        <div className="text-center py-8">
          <div className="inline-flex items-center gap-2 text-muted-foreground">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-muted-foreground/30 border-t-foreground"></div>
            <span>Scanning market...</span>
          </div>
        </div>
      ) : results.length > 0 ? (
        <div className="grid gap-4">
          {results.map((result, idx) => (
            <Card key={result.symbol} className="hover:shadow-lg transition-shadow">
              <CardContent className="p-4">
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <div className="flex items-center gap-4">
                    <div className="text-center">
                      <div className="text-2xl font-bold text-muted-foreground/60">
                        #{idx + 1}
                      </div>
                    </div>

                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-semibold text-lg">{result.symbol}</h3>
                        <div className={`w-2 h-2 rounded-full ${getSignalColor(result.signal_strength)}`} />
                      </div>
                      <p className="text-sm text-muted-foreground">{result.name}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <p className="font-semibold">{currencySymbol}{result.price.toFixed(2)}</p>
                      <p className={`text-sm ${result.change_pct > 0 ? 'text-positive' : result.change_pct < 0 ? 'text-negative' : 'text-muted-foreground'}`}>
                        {result.change_pct > 0 ? '+' : ''}{result.change_pct.toFixed(2)}%
                      </p>
                    </div>

                    <div className="text-right">
                      <p className="text-sm text-muted-foreground">Volume</p>
                      <p className="font-semibold">{(result.volume / 1000000).toFixed(2)}M</p>
                    </div>

                    <div className="text-right">
                      <p className="text-sm text-muted-foreground">Signal</p>
                      <p className="font-semibold">{(result.signal_strength * 100).toFixed(0)}%</p>
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {result.matched_criteria.map((criteria, i) => (
                    <Badge key={i} variant="secondary" className="text-xs">
                      {criteria}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="text-center py-8">
            <p className="text-muted-foreground">No stocks found matching the criteria</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
