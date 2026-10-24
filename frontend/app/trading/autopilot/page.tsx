"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import {
  Cpu,
  FlaskConical,
  Loader2,
  PlayCircle,
  Radar,
  Shield,
  ShieldAlert,
  ClipboardCheck,
  FileText,
  Eye,
  Power,
  Zap,
  CircleAlert,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import Markdown from "@/components/ui/Markdown"
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel"
import LearningMemoryCard from "@/components/stock/LearningMemoryCard"
import {
  fetchAutopilotRun,
  fetchAutopilotRuns,
  fetchAutopilotState,
  fmt,
  fmtPct,
  pnlClass,
  pnlFmt,
  runAutopilot,
  saveAutopilotConfig,
  toggleAutopilot,
  type AutopilotConfig,
  type AutopilotReview,
  type AutopilotRun,
  type AutopilotRunNode,
} from "@/lib/trading"
import { cn } from "@/lib/utils"

const PHASE_META: Record<string, { label: string; icon: typeof Shield; className: string }> = {
  sentinel: { label: "Sentinel", icon: Shield, className: "text-positive" },
  signal: { label: "Signal hunt", icon: Radar, className: "text-primary" },
  optionstrategy: { label: "Option strategy", icon: FlaskConical, className: "text-primary" },
  riskgate: { label: "Risk gate", icon: ShieldAlert, className: "text-primary" },
  execute: { label: "Execute", icon: Zap, className: "text-primary" },
  selfreview: { label: "Self review", icon: ClipboardCheck, className: "text-primary" },
  debrief: { label: "Debrief", icon: FileText, className: "text-primary" },
}

const INPUT_CLS =
  "h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="space-y-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  )
}

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
}

export default function AutopilotPage() {
  const [enabled, setEnabled] = useState(false)
  const [config, setConfig] = useState<AutopilotConfig | null>(null)
  const [halt, setHalt] = useState(false)
  const [review, setReview] = useState<AutopilotReview | null>(null)
  const [form, setForm] = useState<AutopilotConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [running, setRunning] = useState<"day" | "monitor" | null>(null)
  const [lastRun, setLastRun] = useState<AutopilotRun | null>(null)
  const [runs, setRuns] = useState<AutopilotRun[]>([])
  const [openRun, setOpenRun] = useState<AutopilotRun | null>(null)
  const [notice, setNotice] = useState("")

  const load = useCallback(async () => {
    try {
      const s = await fetchAutopilotState()
      setEnabled(s.enabled)
      setConfig(s.config)
      setForm(s.config)
      setHalt(s.halt_recommended)
      setReview(s.last_review)
      setLastRun(s.last_run)
      setRuns((await fetchAutopilotRuns()).runs)
    } catch {
      setNotice("Cannot reach the autopilot service.")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleToggle() {
    setToggling(true)
    setNotice("")
    try {
      const r = await toggleAutopilot(!enabled)
      const next = r.enabled
      setEnabled(next)
      if (form) setForm({ ...form, enabled: next })
      setNotice(`Agent Autopilot is now ${next ? "enabled" : "disabled"}. Amazon-scale autonomy on paper only.`)
    } catch (err) {
      setNotice((err as Error).message || "Toggle failed")
    } finally {
      setToggling(false)
    }
  }

  async function handleSave() {
    if (!form) return
    setSaving(true)
    setNotice("")
    try {
      const r = await saveAutopilotConfig(form)
      setConfig(r.config)
      setForm(r.config)
      setNotice("Mission tunables saved.")
    } catch (err) {
      setNotice((err as Error).message || "Save failed")
    } finally {
      setSaving(false)
    }
  }

  async function handleRun(mode: "day" | "monitor") {
    setRunning(mode)
    setNotice("")
    setOpenRun(null)
    try {
      const run = await runAutopilot(mode === "monitor")
      setLastRun(run)
      setRuns((await fetchAutopilotRuns()).runs)
      setNotice(
        `Mission ${run.mission} finished → ${run.status}. ${(run.summary as { n_fills?: number })?.n_fills ?? 0} fill(s), ${(run.summary as { n_option_tracks?: number })?.n_option_tracks ?? 0} option track(s).`
      )
      const detail = await fetchAutopilotRun(run.id)
      setOpenRun(detail)
      await load()
    } catch (err) {
      setNotice((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Mission run failed")
    } finally {
      setRunning(null)
    }
  }

  function openRunDetail(id: string) {
    setOpenRun(null)
    fetchAutopilotRun(id)
      .then(setOpenRun)
      .catch((err) => setNotice((err as Error).message))
  }

  if (!form) {
    return (
      <div className="space-y-5">
        <div className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">AI Agentic Trading View</h1>
        </div>
        <div className="rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">{notice || "Loading…"}</div>
      </div>
    )
  }

  const sentinelRows = (lastRun?.nodes?.find((n) => n.phase === "sentinel")?.evidence as
    | { monitored?: Array<Record<string, unknown>> }
    | undefined)?.monitored
  const gate = lastRun?.nodes?.find((n) => n.phase === "riskgate")?.evidence as
    | { approved?: unknown[]; rejected?: unknown[] }
    | undefined
  const fills = lastRun?.nodes?.find((n) => n.phase === "execute")?.evidence as
    | { fills?: Array<Record<string, unknown>>; option_tracks?: Array<Record<string, unknown>> }
    | undefined

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Cpu className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">AI Agentic Trading View</h1>
        <Badge variant="outline" className="text-positive">
          PAPER
        </Badge>
      </div>

      {notice && <div className="rounded-lg border bg-card px-4 py-3 text-sm">{notice}</div>}
      {halt && (
        <div className="flex items-start gap-2 rounded-lg border border-negative/30 bg-negative/10 px-4 py-3 text-sm">
          <CircleAlert className="h-4 w-4 text-negative mt-0.5 shrink-0" />
          <span>
            The last self-review recommended a <strong>halt</strong>. Fix the market conditions or risk limits before
            running the next day-cycle (the bot will refuse nothing, but you should review why).
          </span>
        </div>
      )}

      {/* Status + actions */}
      <Card>
        <CardHeader className="py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <span className={cn("h-2.5 w-2.5 rounded-full", enabled ? "bg-positive animate-pulse" : "bg-muted-foreground")} />
                {enabled ? "Autonomy engaged" : "Human in control"}
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                A 7-agent crew protects positions, hunts signals, prices F&amp;O, gates risk, executes on paper, reviews
                itself and writes the debrief — all on real StockOS data.
              </p>
            </div>
            <div className="flex gap-2">
              <Button onClick={handleToggle} disabled={toggling} variant={enabled ? "secondary" : "default"}>
                {toggling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
                {enabled ? "Disable" : "Enable"}
              </Button>
              <Button onClick={() => handleRun("day")} disabled={!!running}>
                {running === "day" ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
                Run day-cycle
              </Button>
              <Button onClick={() => handleRun("monitor")} disabled={!!running} variant="outline">
                {running === "monitor" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
                Monitor only
              </Button>
            </div>
          </div>
          {review && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
              <div className="rounded-md bg-muted/50 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">Last score</div>
                <div className="text-sm font-semibold tabular-nums">{(review.score * 100).toFixed(0)}%</div>
              </div>
              <div className="rounded-md bg-muted/50 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">Fills / rejects</div>
                <div className="text-sm font-semibold tabular-nums">
                  {review.n_fills} / {review.n_rejects}
                </div>
              </div>
              <div className="rounded-md bg-muted/50 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">F&amp;O tracked</div>
                <div className="text-sm font-semibold tabular-nums">{review.n_option_tracks}</div>
              </div>
              <div className="rounded-md bg-muted/50 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">Mission P&amp;L</div>
                <div className={cn("text-sm font-semibold tabular-nums", pnlClass(review.realised_pnl))}>
                  {pnlFmt(review.realised_pnl)}
                </div>
              </div>
            </div>
          )}
        </CardHeader>
      </Card>

      {/* AI agentic analysis + learning memory */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AgenticTradingPanel defaultOpen />
        <LearningMemoryCard />
      </div>

      {/* Tunables */}
      <Card>
        <CardHeader className="py-3 flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Mission tunables</CardTitle>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Field label="Market">
            <select className={INPUT_CLS} value={form.market} onChange={(e) => setForm({ ...form, market: e.target.value })}>
              <option value="india">India (NSE/BSE)</option>
              <option value="us">US (NYSE/NASDAQ)</option>
            </select>
          </Field>
          <Field label="Scanners" hint="comma separated">
            <input className={INPUT_CLS} value={form.scanners.join(", ")} onChange={(e) => setForm({ ...form, scanners: parseList(e.target.value) })} />
          </Field>
          <Field label="Watchlist" hint="comma separated EXCHANGE:TICKER">
            <input className={INPUT_CLS} value={form.watchlist.join(", ")} onChange={(e) => setForm({ ...form, watchlist: parseList(e.target.value) })} />
          </Field>
          <Field label="New entries / cycle">
            <input type="number" min={0} max={10} className={INPUT_CLS} value={config ? config.max_new_entries : form.max_new_entries} onChange={(e) => setForm({ ...form, max_new_entries: Number(e.target.value) })} />
          </Field>
          <Field label="Entry qty (shares)">
            <input type="number" min={1} className={INPUT_CLS} value={config ? config.entry_qty : form.entry_qty} onChange={(e) => setForm({ ...form, entry_qty: Number(e.target.value) })} />
          </Field>
          <Field label="Take-profit %">
            <input type="number" step={0.5} min={0} className={INPUT_CLS} value={config ? config.take_profit_pct : form.take_profit_pct} onChange={(e) => setForm({ ...form, take_profit_pct: Number(e.target.value) })} />
          </Field>
          <Field label="Stop-loss %" hint="negative number">
            <input type="number" step={0.5} max={0} className={INPUT_CLS} value={config ? config.stop_loss_pct : form.stop_loss_pct} onChange={(e) => setForm({ ...form, stop_loss_pct: Number(e.target.value) })} />
          </Field>
          <Field label="Trailing drop %">
            <input type="number" step={0.1} min={0.1} className={INPUT_CLS} value={config ? config.trail_drop_pct : form.trail_drop_pct} onChange={(e) => setForm({ ...form, trail_drop_pct: Number(e.target.value) })} />
          </Field>
          <label className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
            <span className="text-xs font-medium text-muted-foreground">Trail profit</span>
            <input type="checkbox" checked={form.trail_enabled} onChange={(e) => setForm({ ...form, trail_enabled: e.target.checked })} />
          </label>
          <label className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
            <span className="text-xs font-medium text-muted-foreground">F&amp;O plays</span>
            <input type="checkbox" checked={form.option_enabled} onChange={(e) => setForm({ ...form, option_enabled: e.target.checked })} />
          </label>
          <Field label="Max F&amp;O plays / cycle">
            <input type="number" min={0} max={10} className={INPUT_CLS} value={config ? config.option_max_plays : form.option_max_plays} onChange={(e) => setForm({ ...form, option_max_plays: Number(e.target.value) })} />
          </Field>
          <Field label="F&amp;O lots">
            <input type="number" min={1} className={INPUT_CLS} value={config ? config.option_lots : form.option_lots} onChange={(e) => setForm({ ...form, option_lots: Number(e.target.value) })} />
          </Field>
        </CardContent>
      </Card>

      {/* Last mission trace */}
      {lastRun && (
        <Card>
          <CardHeader className="py-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Last mission · {lastRun.mission}</CardTitle>
              <Badge
                variant="outline"
                className={cn(
                  lastRun.status === "completed" ? "text-positive" : lastRun.status === "halted" ? "text-negative" : "text-muted-foreground"
                )}
              >
                {lastRun.status}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Phase timeline */}
            {(lastRun.nodes ?? []).length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {(lastRun.nodes ?? []).map((node) => {
                  const meta = PHASE_META[node.phase] ?? { label: node.phase, icon: Shield, className: "text-muted-foreground" }
                  const Icon = meta.icon
                  return (
                    <span
                      key={node.id}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs",
                        node.status === "error" ? "border-negative/40 text-negative" : "text-muted-foreground"
                      )}
                      title={node.error || undefined}
                    >
                      <Icon className={cn("h-3.5 w-3.5", node.status === "done" ? meta.className : "text-muted-foreground")} />
                      {meta.label}
                      {node.status === "error" && <CircleAlert className="h-3 w-3 text-negative" />}
                    </span>
                  )
                })}
              </div>
            )}

            {/* Sentinel monitored positions */}
            {sentinelRows && sentinelRows.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-1.5 pr-3">Symbol</th>
                      <th className="py-1.5 pr-3">Qty</th>
                      <th className="py-1.5 pr-3">Avg</th>
                      <th className="py-1.5 pr-3">Last</th>
                      <th className="py-1.5 pr-3">PnL %</th>
                      <th className="py-1.5">Decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sentinelRows.map((row) => {
                      const pnl = Number((row.pnl_pct as number | undefined) ?? 0)
                      return (
                        <tr key={row.symbol as string} className="border-b">
                          <td className="py-2 pr-3 font-medium">{row.symbol as string}</td>
                          <td className="py-2 pr-3 tabular-nums">{row.quantity as number}</td>
                          <td className="py-2 pr-3 tabular-nums">{fmt(row.average_price as number)}</td>
                          <td className="py-2 pr-3 tabular-nums">{fmt(row.last_price as number)}</td>
                          <td className={cn("py-2 pr-3 tabular-nums", pnlClass(pnl))}>{fmtPct(pnl)}</td>
                          <td className="py-2">
                            <Badge variant="outline" className={cn(pnl >= 0 ? "text-positive" : "text-negative")}>
                              {(row.action as string) ?? "HOLD"} · {row.reason as string}
                            </Badge>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Executed fills */}
            {fills?.fills && fills.fills.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {fills.fills.map((f, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1 text-xs">
                    <Zap className="h-3.5 w-3.5 text-positive" />
                    {f.side as string} {f.symbol as string} qty {f.qty as number} @ {fmt(f.fill_price as number)} ({f.action as string})
                  </span>
                ))}
              </div>
            )}

            {/* Debrief report */}
            {lastRun.report && (
              <Markdown className="max-h-80 overflow-y-auto rounded-lg border bg-muted/30 px-4 py-3 text-sm">{lastRun.report}</Markdown>
            )}
          </CardContent>
        </Card>
      )}

      {/* Selected run detail */}
      {openRun && (
        <Card>
          <CardHeader className="py-3 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium">Run detail · {openRun.mission}</CardTitle>
            <div className="flex items-center gap-2">
              {gate && (
                <span className="text-xs text-muted-foreground">
                  approved {gate.approved?.length ?? 0} / rejected {gate.rejected?.length ?? 0}
                </span>
              )}
              <Badge variant="outline">{openRun.status}</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {(openRun.nodes ?? []).map((node) => (
              <div key={node.id} className="rounded-lg border px-4 py-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">
                    #{node.position} {PHASE_META[node.phase]?.label ?? node.phase}
                  </span>
                  <Badge variant="outline" className={node.status === "done" ? "text-positive" : "text-negative"}>
                    {node.status}
                  </Badge>
                </div>
                {node.error && <div className="mt-1 text-xs text-negative">{node.error}</div>}
                {node.evidence && (
                  <pre className="mt-2 max-h-48 overflow-y-auto rounded-md bg-muted/40 p-2 text-[11px] leading-relaxed text-muted-foreground">
                    {JSON.stringify(node.evidence, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* History */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Mission history</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {runs.length === 0 ? (
            <p className="px-6 py-8 text-sm text-muted-foreground text-center">
              No missions yet — hit “Run day-cycle” to let the crew go to work.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {runs.slice(0, 10).map((r) => (
                <li key={r.id} className="flex items-center gap-3 px-6 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{r.mission}</span>
                      <Badge variant="outline" className={cn(r.status === "completed" ? "text-positive" : r.status === "halted" ? "text-negative" : "text-muted-foreground")}>
                        {r.status}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                    </div>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => openRunDetail(r.id)}>
                    Inspect
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="text-xs text-muted-foreground">
        <p className="font-medium mb-1">How the crew works</p>
        <ul className="list-disc pl-5 space-y-0.5">
          <li>Sentinel protects open positions (take-profit / stop-loss / trailing) using real quotes.</li>
          <li>Signal fuses multiple scanners; Option strategy prices concrete CE/PE plays from real chains.</li>
          <li>Risk gate sizes every entry with the RiskEngine; executes on the paper broker with the usual guards.</li>
          <li>Self-review scores the mission and writes the trade journal; every mission is persisted with a full node trace.</li>
          <li>Run it as a scheduled playbook on /scheduled (“autopilot” type) to make it fully autonomous.</li>
        </ul>
        <p className="mt-2">
          Prefer one-trade-at-a-time? The single-signal <Link href="/trading/tradebot" className="text-primary underline underline-offset-4">TradeBot</Link> still runs
          on top of the same scanner.
        </p>
      </div>
    </div>
  )
}