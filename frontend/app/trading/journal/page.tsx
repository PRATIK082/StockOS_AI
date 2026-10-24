"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, NotebookPen, Plus, Trash2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  createJournalEntry,
  deleteJournalEntry,
  fetchJournal,
  fmt,
  pnlClass,
  pnlFmt,
  type JournalEntry,
} from "@/lib/trading"
import { cn } from "@/lib/utils"

const OUTCOMES = ["win", "loss", "breakeven", "open", "flat"] as const

export default function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [flash, setFlash] = useState("")

  const [symbol, setSymbol] = useState("")
  const [side, setSide] = useState("BUY")
  const [rationale, setRationale] = useState("")
  const [pnl, setPnl] = useState("")
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]>("open")
  const [tagInput, setTagInput] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const res = await fetchJournal()
      setEntries(res.entries)
    } catch (err) {
      setError((err as Error).message || "Failed to load journal")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate() {
    if (!symbol || !rationale.trim()) {
      setError("Symbol and rationale are required")
      return
    }
    setSaving(true)
    setError("")
    setFlash("")
    try {
      const tags = tagInput
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
      await createJournalEntry({
        symbol: symbol.toUpperCase(),
        side,
        rationale: rationale.trim(),
        pnl: Number(pnl) || 0,
        outcome,
        tags,
      })
      setSymbol("")
      setRationale("")
      setPnl("")
      setTagInput("")
      setOutcome("open")
      setFlash("Entry saved.")
      load()
    } catch (err) {
      setError((err as Error).message || "Failed to save entry")
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    await deleteJournalEntry(id)
    setEntries((es) => es.filter((e) => e.id !== id))
  }

  const wins = entries.filter((e) => e.outcome === "win").length
  const losses = entries.filter((e) => e.outcome === "loss").length
  const totalPnl = entries.reduce((s, e) => s + (Number(e.pnl) || 0), 0)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <NotebookPen className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Trade Journal</h1>
          <Badge variant="outline">{entries.length} entries</Badge>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 max-w-md">
        <div className="rounded-lg border bg-card p-3 text-sm">
          <div className="text-muted-foreground text-xs">Wins</div>
          <div className="font-semibold text-positive">{wins}</div>
        </div>
        <div className="rounded-lg border bg-card p-3 text-sm">
          <div className="text-muted-foreground text-xs">Losses</div>
          <div className="font-semibold text-negative">{losses}</div>
        </div>
        <div className="rounded-lg border bg-card p-3 text-sm">
          <div className="text-muted-foreground text-xs">Total P&L</div>
          <div className={cn("font-semibold", pnlClass(totalPnl))}>{pnlFmt(totalPnl)}</div>
        </div>
      </div>

      {flash && <p className="text-sm text-positive">{flash}</p>}
      {error && <p className="text-sm text-negative">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-medium">New entry</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="j-symbol">Symbol</Label>
              <Input id="j-symbol" placeholder="NSE:RELIANCE" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Side</Label>
                <select
                  value={side}
                  onChange={(e) => setSide(e.target.value)}
                  className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
                >
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                  <option value="HOLD">HOLD</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>P&L (₹)</Label>
                <Input type="number" step="any" value={pnl} onChange={(e) => setPnl(e.target.value)} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Outcome</Label>
              <div className="flex flex-wrap gap-1.5">
                {OUTCOMES.map((o) => (
                  <button
                    key={o}
                    type="button"
                    onClick={() => setOutcome(o)}
                    className={cn(
                      "rounded-md border px-2 py-1 text-xs font-medium capitalize",
                      outcome === o ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground hover:bg-accent"
                    )}
                  >
                    {o}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="j-rationale">Rationale</Label>
              <Textarea
                id="j-rationale"
                placeholder="Why did you take this trade? What was the plan?"
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                rows={4}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="j-tags">Tags (comma separated)</Label>
              <Input id="j-tags" placeholder="sma-cross, trend, intraday" value={tagInput} onChange={(e) => setTagInput(e.target.value)} />
            </div>
            <Button className="w-full" onClick={handleCreate} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Save entry
            </Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-medium">Recent entries</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="flex justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : entries.length === 0 ? (
              <p className="px-6 py-10 text-sm text-muted-foreground text-center">
                No journal entries yet. Log your first trade.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {entries.map((e) => (
                  <li key={e.id} className="px-6 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium">{e.symbol}</span>
                        <Badge variant="outline" className={e.side === "BUY" ? "text-positive" : e.side === "SELL" ? "text-negative" : ""}>
                          {e.side}
                        </Badge>
                        <Badge variant={e.outcome === "win" ? "positive" : e.outcome === "loss" ? "negative" : "muted"}>
                          {e.outcome}
                        </Badge>
                        {e.tags.map((t) => (
                          <span key={t} className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                            {t}
                          </span>
                        ))}
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className={cn("tabular-nums text-sm font-medium", pnlClass(e.pnl))}>{pnlFmt(e.pnl)}</span>
                        <button
                          onClick={() => handleDelete(e.id)}
                          className="text-muted-foreground hover:text-negative transition-colors"
                          aria-label="Delete entry"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1.5">{e.rationale}</p>
                    {e.created_at && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {new Date(e.created_at).toLocaleString()}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}