"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { Bot, Loader2, PlayCircle, Power } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  executeTradebotSignal,
  fetchTradebot,
  fmt,
  fmtPct,
  pnlFmt,
  toggleTradebot,
  type TradebotSignal,
} from "@/lib/trading"
import { cn } from "@/lib/utils"

export default function TradebotPage() {
  const [enabled, setEnabled] = useState(false)
  const [signals, setSignals] = useState<TradebotSignal[]>([])
  const [strategy, setStrategy] = useState("momentum")
  const [updatedAt, setUpdatedAt] = useState("")
  const [toggling, setToggling] = useState(false)
  const [executing, setExecuting] = useState<string | null>(null)
  const [notice, setNotice] = useState("")

  const load = useCallback(async () => {
    try {
      const t = await fetchTradebot()
      setEnabled(t.enabled)
      setSignals(t.signals)
      setStrategy(t.strategy)
      setUpdatedAt(t.updated_at)
    } catch {
      setNotice("Cannot reach tradebot service.")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleToggle() {
    setToggling(true)
    setNotice("")
    try {
      const r = await toggleTradebot(!enabled)
      setEnabled(r.enabled)
      setNotice(`TradeBot is now ${r.enabled ? "RUNNING" : "PAUSED"} (paper).`)
    } catch (err) {
      setNotice((err as Error).message || "Toggle failed")
    } finally {
      setToggling(false)
    }
  }

  async function execute(sig: TradebotSignal) {
    setExecuting(sig.symbol)
    setNotice("")
    try {
      const r = await executeTradebotSignal({ symbol: sig.symbol, side: "BUY", quantity: 1 })
      setNotice(`Executed BUY ${sig.symbol} qty 1 @ ${fmt(r.fill_price)} (paper).`)
      await load()
    } catch (err) {
      setNotice((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Execution failed")
    } finally {
      setExecuting(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Bot className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">TradeBot</h1>
        <Badge variant="outline" className="text-positive">
          PAPER
        </Badge>
      </div>

      <Card>
        <CardHeader className="py-4">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <span className={cn("h-2.5 w-2.5 rounded-full", enabled ? "bg-positive animate-pulse" : "bg-muted-foreground")} />
                {enabled ? "Running" : "Paused"}
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Paper auto-trader on top of real scanner signals · strategy: {strategy}
              </p>
            </div>
            <Button onClick={handleToggle} disabled={toggling} variant={enabled ? "secondary" : "default"}>
              {toggling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
              {enabled ? "Pause bot" : "Start bot"}
            </Button>
          </div>
        </CardHeader>
      </Card>

      {notice && (
        <div className="rounded-lg border bg-card px-4 py-3 text-sm">{notice}</div>
      )}

      <Card>
        <CardHeader className="py-3 flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Live signals (momentum scanner, India)</CardTitle>
          {updatedAt && <span className="text-xs text-muted-foreground">updated {new Date(updatedAt).toLocaleTimeString()}</span>}
        </CardHeader>
        <CardContent className="p-0">
          {signals.length === 0 ? (
            <p className="px-6 py-10 text-sm text-muted-foreground text-center">
              No signals right now — run the scanner or check back later.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {signals.map((sig) => (
                <li key={sig.symbol} className="flex items-center gap-3 px-6 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{sig.symbol}</span>
                      <span className="text-xs text-muted-foreground truncate hidden sm:inline">{sig.name}</span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {sig.criteria.slice(0, 3).map((c) => (
                        <span key={c} className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="tabular-nums font-medium">{fmt(sig.price)}</div>
                    <div className={cn("text-xs tabular-nums", sig.change_pct >= 0 ? "text-positive" : "text-negative")}>
                      {fmtPct(sig.change_pct)}
                    </div>
                  </div>
                  <div className="shrink-0 text-xs text-muted-foreground">
                    strength {(sig.signal_strength * 100).toFixed(0)}%
                  </div>
                  <Button size="sm" disabled={!!executing} onClick={() => execute(sig)}>
                    {executing === sig.symbol ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}
                    Buy qty 1
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="text-xs text-muted-foreground">
        <p className="font-medium mb-1">How it works</p>
        <ul className="list-disc pl-5 space-y-0.5">
          <li>Signals come from the real StockOS scanner (momentum over live quotes/history).</li>
          <li>Executions go through the paper broker with the same risk guards (daily loss, max positions, duplicate-order checks).</li>
          <li>
            Want a whole crew instead of one bot?{" "}
            <Link href="/trading/autopilot" className="text-primary underline underline-offset-4">
              Agent Autopilot
            </Link>{" "}
            runs sentinel, signal hunting, F&amp;O plays and a risk gate in a single mission.
          </li>
        </ul>
      </div>
    </div>
  )
}