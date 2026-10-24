"use client"

import { useEffect, useRef, useState } from "react"
import Markdown from "@/components/ui/Markdown"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SymbolSearch } from "@/components/stock/symbol-search"
import TechnicalChart from "@/components/stock/TechnicalChart"
import { api } from "@/lib/api-client"
import { getAuthToken } from "@/lib/api"
import { Bot, KeyRound, Play, Trash2, TrendingUp, Loader2, CheckCircle2, XCircle, Save } from "lucide-react"

interface ProviderMeta {
  provider: string
  label: string
  is_local: boolean
  needs_key: boolean
  needs_base_url: boolean
  key_env: string | null
  default_deep: string
  default_quick: string
  hint: string
}

interface Credential {
  id: string
  provider: string
  is_default: boolean
  has_key: boolean
  base_url: string | null
  deep_model: string | null
  quick_model: string | null
}

interface RunRecord {
  id: string
  symbol: string
  trade_date: string
  provider: string
  models: { deep: string; quick: string }
  status: string
  error: string | null
  rating: string | null
final_decision: string | null
  reports: null | { [key: string]: string }
signal: null | {
    rating: string
    action: string
    direction: string
    conviction: number
    price_target: number | null
    time_horizon: string | null
    executive_summary: string
  }
node_trace: null | Array<{ node: string; label: string; repeat?: boolean }>
  options: null | {
    expiry: string | null
    spot_price: number | null
    max_pain: number | null
    iv_skew: number | null
    atm_iv: number | null
    premium_put_call: number | null
    bias: string | null
    strategy: string | null
    recommendation: string | null
    alignment: string
    suggestion: { leg: string | null; strike: number | null; otm_strike: number | null; note: string }
    note: string
    option_leg?: null | {
      underlying: string
      option_type: string
      strike: number
      expiry: string | null
      current_premium: number
      predicted_premium: number
      expected_return: number
      iv: number | null
      delta: number | null
      gamma: number | null
      theta: number | null
      vega: number | null
      spot_price: number | null
      moneyness: number | null
      driven_by: string | null
    }
  }
  simulated: boolean
  created_at: string | null
}

interface ProviderMeta_list {
  default_provider: string
  providers: ProviderMeta[]
}

const RATING_STYLES: Record<string, string> = {
  Buy: "bg-positive/15 text-positive border border-positive/30",
  Overweight: "bg-positive/10 text-positive border border-positive/20",
  Hold: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30",
  Underweight: "bg-negative/10 text-negative border border-negative/20",
  Sell: "bg-negative/15 text-negative border border-negative/30",
}

function ratingStyle(rating: string): string {
  return RATING_STYLES[rating] || RATING_STYLES.Hold
}

type TraceNode = { node: string; label: string; repeat?: boolean }
type NodeGroup = { title: string; items: TraceNode[] }

// Group the flat LangGraph node trace into readable phases so a run's
// "Analysis Flow" panel reads top-to-bottom like the pipeline it actually ran.
const NODE_PHASE: Array<[string, RegExp]> = [
  ["Data gathering", /^tools_/i],
  ["Markets & quotes", /marketc|clear market/i],
  ["Sentiment", /sentiment|social/i],
  ["News", /news/i],
  ["Fundamentals", /fundamental/i],
  ["Bull / Bear research", /bull|bear/i],
  ["Research review", /research manager|msg clear/i],
  ["Trading team", /trader|aggressive|conservative|neutral analyst/i],
  ["Final decision", /portfolio manager/i],
]

function groupedNodes(trace: TraceNode[] | null): NodeGroup[] {
  if (!trace || trace.length === 0) return []
  const groups: NodeGroup[] = []
  const used = new Set<string>()
  for (const [title, rx] of NODE_PHASE) {
    const items = trace.filter((n) => rx.test(n.node || n.label) && !used.has(n.node + n.label))
    if (items.length === 0) continue
    items.forEach((n) => used.add(n.node + n.label))
    groups.push({ title, items })
  }
  const leftovers = trace.filter((n) => !used.has(n.node + n.label))
  if (leftovers.length > 0) {
    groups.push({ title: "Steps", items: leftovers })
  }
  return groups
}

const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function errDetail(err: any, fallback: string): string {
  if (err?.response?.data?.detail) return String(err.response.data.detail)
  if (err?.message && err.message !== "Request failed with status code 404") return err.message
  return fallback
}

function consumeSse(
  url: string,
  onEvent: (ev: Record<string, unknown>) => void,
  onClose: () => void,
  onError: (err: string) => void
) {
  const controller = new AbortController()
  ;(async () => {
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${getAuthToken() ?? ""}` },
        signal: controller.signal,
      })
      if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let idx: number
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          for (const line of chunk.split("\n")) {
            if (line.startsWith("data: ")) {
              try {
                onEvent(JSON.parse(line.slice(6)))
              } catch {
                /* ignore malformed frames */
              }
            }
          }
        }
      }
      onClose()
    } catch (err: any) {
      if (err?.name === "AbortError") return
      onError(err?.message ?? "Stream error")
    }
  })()
  return () => controller.abort()
}

export default function TradingDeskPage() {
  const [providers, setProviders] = useState<ProviderMeta[]>([])
  const [provider, setProvider] = useState("ollama")
  const [symbol, setSymbol] = useState("")
  const [runKey, setRunKey] = useState("")
  const [runBaseUrl, setRunBaseUrl] = useState("")
  const [runDeep, setRunDeep] = useState("")
  const [running, setRunning] = useState(false)
const [runId, setRunId] = useState<string | null>(null)
  const [steps, setSteps] = useState<Array<{ node: string; label: string }>>([])
  const [liveStatus, setLiveStatus] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<RunRecord | null>(null)
  const [history, setHistory] = useState<RunRecord[]>([])
  const [credentials, setCredentials] = useState<Credential[]>([])
const [optionType, setOptionType] = useState("")
  const [strike, setStrike] = useState("")
  const [expiry, setExpiry] = useState("")
  const [chainStrikes, setChainStrikes] = useState<number[]>([])
  const [chainExpiries, setChainExpiries] = useState<string[]>([])
  const [chainQueryLoading, setChainQueryLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<(() => void) | null>(null)

  // Load the real F&O chain so Strike/Expiry become populated dropdowns — the
  // same chain-backed controls the Prediction page has. No chain => disabled
  // selects with an honest hint (not a fabricated strike list).
  useEffect(() => {
    if (!symbol) {
      setChainStrikes([])
      setChainExpiries([])
      return
    }
    let cancelled = false
    setChainQueryLoading(true)
    api
      .get<{ expiries: string[]; calls?: { strike: number }[]; puts?: { strike: number }[] }>(
        `/api/analysis/options/chain/${encodeURIComponent(symbol)}`,
      )
      .then((res) => {
        if (cancelled) return
        const data = res.data
        const strikes = [
          ...(data.calls?.map((c) => c.strike) ?? []),
          ...(data.puts?.map((p) => p.strike) ?? []),
        ]
        setChainStrikes(Array.from(new Set(strikes)).sort((a, b) => a - b))
        setChainExpiries(data.expiries ?? [])
      })
      .catch(() => {
        if (cancelled) return
        setChainStrikes([])
        setChainExpiries([])
      })
      .finally(() => {
        if (!cancelled) setChainQueryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [symbol, api])

  const loadAll = async () => {
    const [p, c, h] = await Promise.all([
      api.get<ProviderMeta_list>("/api/trading/providers"),
      api.get<Credential[]>("/api/trading/credentials"),
      api.get<RunRecord[]>("/api/trading/runs"),
    ])
    setProviders(p.data.providers)
    setProvider(p.data.default_provider || "ollama")
    setCredentials(c.data)
    setHistory(h.data)
  }

  useEffect(() => {
    loadAll().catch((err) => setError(errDetail(err, "Failed to load Trading Desk")))
    return () => abortRef.current?.()
  }, [])

  const startRun = async () => {
    if (!symbol || running) return
    setRunning(true)
    setError(null)
    setRunResult(null)
    setRunId(null)
    setSteps([])
    setLiveStatus(null)
const body: Record<string, unknown> = { symbol }
    if (provider) body.provider = provider
    if (runKey) body.api_key = runKey
    if (runBaseUrl) body.base_url = runBaseUrl
    if (runDeep) body.deep_model = runDeep
    if (optionType) body.option_type = optionType
    if (strike && !Number.isNaN(Number(strike))) body.option_strike = Number(strike)
    if (expiry) body.option_expiry = expiry

    try {
      const res = await api.post<{ run_id: string }>("/api/trading/analyze", body)
      const id = res.data.run_id
      setRunId(id)

      const url = `${API_ORIGIN}/api/trading/runs/${id}/events`
      abortRef.current = consumeSse(
        url,
        (ev) => {
          if (ev.node && ev.label) {
            setSteps((s) => [...s, { node: String(ev.node), label: String(ev.label) }])
          }
          if (ev.status) setLiveStatus(String(ev.status))
          if (ev.status === "completed") {
            setRunId(null)
            setLiveStatus("completed")
          }
          if (ev.status === "failed") {
            setLiveStatus("failed")
            setRunId(null)
            setError(String(ev.error || "Run failed"))
          }
        },
        () => {
          fetchRunDetail(id).finally(() => setRunning(false))
        },
        (err) => {
          setError(err)
          setRunning(false)
        }
      )
    } catch (err: any) {
      setError(errDetail(err, "Could not start the analysis"))
      setRunning(false)
    }
  }

  const fetchRunDetail = async (id: string) => {
    try {
      const res = await api.get<RunRecord>(`/api/trading/runs/${id}`)
      setRunResult(res.data)
      setSteps((res.data.node_trace || []).map((n) => ({ node: n.node, label: n.label })))
      const rr = await loadHistory()
      setHistory(rr)
      if (res.data.status === "failed") setError(res.data.error || "Run failed")
    } catch {
      /* ignore */
    }
  }

  const loadHistory = async () => {
    const res = await api.get<RunRecord[]>("/api/trading/runs")
    setHistory(res.data)
    return res.data
  }

  const saveCredential = async () => {
    try {
      await api.post("/api/trading/credentials", {
        provider,
        api_key: runKey,
        base_url: runBaseUrl || null,
        deep_model: runDeep || null,
      })
      const c = await api.get<Credential[]>("/api/trading/credentials")
      setCredentials(c.data)
      setRunKey("")
      setRunBaseUrl("")
      setRunDeep("")
    } catch (err: any) {
      setError(errDetail(err, "Could not save credential"))
    }
  }

const deleteCredential = async (id: string) => {
    try {
      await api.delete(`/api/trading/credentials/${id}`)
      setCredentials((cs) => cs.filter((c) => c.id !== id))
    } catch (err: any) {
      setError(errDetail(err, "Could not delete credential"))
    }
  }

  const deleteRun = async (id: string) => {
    try {
      await api.delete(`/api/trading/runs/${id}`)
      setHistory((hs) => hs.filter((r) => r.id !== id))
      if (runResult?.id === id) setRunResult(null)
    } catch (err: any) {
      setError(errDetail(err, "Could not delete run"))
    }
  }

  const simulate = async () => {
    if (!runResult) return
    try {
      await api.post(`/api/trading/runs/${runResult.id}/simulate`, { quantity: 1 })
      setRunResult({ ...runResult, simulated: true })
    } catch (err: any) {
      setError(errDetail(err, "Simulation failed"))
    }
  }

  const activeMeta = providers.find((p) => p.provider === provider)

  return (
    <div className="container mx-auto p-6">
      <div className="flex items-center gap-3 mb-6">
        <Bot className="h-7 w-7 text-blue-600" />
        <div>
          <h1 className="text-3xl font-bold">AI Trading Desk</h1>
          <p className="text-sm text-muted-foreground">
            Multi-agent research pipeline (TradingAgents) on real StockOS data. Defaults to local Ollama; pick any provider and key per run.
          </p>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          <p>{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Run form */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Play className="h-5 w-5" /> Start Analysis
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
<div>
              <label className="block text-sm font-medium text-foreground mb-1">Symbol</label>
              <SymbolSearch onSelect={setSymbol} />
            </div>
<div className="rounded-md border border-border bg-muted/30 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
                Option contract (optional)
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Type</label>
                  <Select value={optionType} onValueChange={setOptionType}>
                    <SelectTrigger>
                      <SelectValue placeholder="CE / PE" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="CE">CALL (CE)</SelectItem>
                      <SelectItem value="PE">PUT (PE)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Strike</label>
                  <Select value={strike} onValueChange={setStrike} disabled={chainStrikes.length === 0}>
                    <SelectTrigger>
                      <SelectValue placeholder="Pick strike" />
                    </SelectTrigger>
                    <SelectContent className="max-h-72">
                      {chainStrikes.length === 0 && (
                        <SelectItem value="__none__" disabled>
                          {chainQueryLoading
                            ? "Loading chain…"
                            : "No chain for this symbol (NSE/BSE with F&O)"}
                        </SelectItem>
                      )}
                      {chainStrikes.map((s) => (
                        <SelectItem key={s} value={String(s)}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Expiry (optional)</label>
                  <Select value={expiry} onValueChange={setExpiry} disabled={chainExpiries.length === 0}>
                    <SelectTrigger>
                      <SelectValue placeholder="Pick expiry" />
                    </SelectTrigger>
                    <SelectContent>
                      {chainExpiries.length === 0 && (
                        <SelectItem value="__none__" disabled>
                          {chainQueryLoading
                            ? "Loading chain…"
                            : "No chain for this symbol"}
                        </SelectItem>
                      )}
                      {chainExpiries.map((d) => (
                        <SelectItem key={d} value={d.slice(0, 10)}>
                          {d.slice(0, 10)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              {chainStrikes.length === 0 && !chainQueryLoading && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Strike/expiry drop from the real F&O chain — pick a symbol with a chain (e.g. NSE:NIFTY) to populate.
                </p>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Provider</label>
                <Select value={provider} onValueChange={setProvider}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {providers.map((p) => (
                      <SelectItem key={p.provider} value={p.provider}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {activeMeta?.hint && (
                  <p className="mt-1 text-xs text-muted-foreground">{activeMeta.hint}</p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Deep model (optional)</label>
                <Input value={runDeep} onChange={(e) => setRunDeep(e.target.value)} placeholder={activeMeta?.default_deep || "auto-detect"} />
                <p className="mt-1 text-xs text-muted-foreground">
                  Leave blank for provider default{activeMeta?.is_local ? " (your pulled Ollama models)" : ""}.
                </p>
              </div>
            </div>

            {!activeMeta?.is_local && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">API key (per-run; optional — uses saved credential)</label>
                  <Input type="password" value={runKey} onChange={(e) => setRunKey(e.target.value)} placeholder="sk-..." />
                </div>
                {activeMeta?.needs_base_url && (
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1">Base URL</label>
                    <Input value={runBaseUrl} onChange={(e) => setRunBaseUrl(e.target.value)} placeholder="https://..." />
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-2">
              <Button onClick={startRun} disabled={!symbol || running}>
                {running ? <Loader2 className="animate-spin h-4 w-4 mr-1" /> : <Play className="h-4 w-4 mr-1" />}
                {running ? "Running…" : "Run Trading Desk"}
              </Button>
              {!activeMeta?.is_local && (
                <Button variant="outline" onClick={saveCredential} disabled={!provider}>
                  <Save className="h-4 w-4 mr-1" /> Save credential
                </Button>
              )}
            </div>

            {runId && (
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <p className="text-sm text-muted-foreground mb-2">
                  {liveStatus ? `Status: ${liveStatus}` : "Listening for live node updates…"}
                </p>
                {steps.length > 0 && (
                  <ol className="space-y-1 max-h-56 overflow-auto font-mono text-xs">
                    {steps.map((s, i) => (
                      <li key={i} className="flex items-center gap-2">
                        <span className="text-blue-500">►</span>
                        <span className="capitalize">{s.label}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Credentials */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="h-5 w-5" /> Saved Providers
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {credentials.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No saved credentials. The desk uses the local Ollama runtime by default.
              </p>
            )}
            {credentials.map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded-md bg-muted/40 p-2 text-sm">
                <div>
                  <span className="font-medium">{c.provider}</span>
                  {c.is_default && <span className="ml-2 text-xs text-blue-500">default</span>}
                  {!c.has_key && <span className="ml-2 text-xs text-yellow-500">no key</span>}
                  <p className="text-xs text-muted-foreground">
                    {c.deep_model || "auto models"}
                    {c.base_url ? ` · ${c.base_url}` : ""}
                  </p>
                </div>
                <Button variant="ghost" size="icon" onClick={() => deleteCredential(c.id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Result */}
      {runResult && runResult.status === "completed" && (
        <div className="mt-6 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Verdict</CardTitle>
              </CardHeader>
<CardContent>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`inline-flex items-center rounded px-3 py-1 text-lg font-bold ${ratingStyle(runResult.signal?.rating || runResult.rating || "Hold")}`}>
                    {runResult.signal?.rating || runResult.rating || "—"}
                  </span>
                  {runResult.signal?.direction && runResult.signal.direction !== "hold" && (
                    <span
                      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-bold ${
                        runResult.signal.direction === "long"
                          ? "bg-positive/15 text-positive border border-positive/30"
                          : "bg-negative/15 text-negative border border-negative/30"
                      }`}
                    >
                      {runResult.signal.direction === "long" ? "LONG" : "SHORT"}
                    </span>
                  )}
                </div>
                <div className="mt-3 space-y-1 text-sm">
                  <p className="flex justify-between">
                    <span className="text-muted-foreground">Provider</span>
                    <span className="font-medium">{runResult.provider}</span>
                  </p>
                  <p className="flex justify-between">
                    <span className="text-muted-foreground">Conviction</span>
                    <span className="font-medium">{(runResult.signal?.conviction ?? 0).toFixed(0)}%</span>
                  </p>
                  {runResult.signal?.price_target != null && (
                    <p className="flex justify-between">
                      <span className="text-muted-foreground">Price Target</span>
                      <span className="font-medium">{(runResult.signal as any).price_target}</span>
                    </p>
                  )}
                  {runResult.signal?.time_horizon && (
                    <p className="flex justify-between">
                      <span className="text-muted-foreground">Horizon</span>
                      <span className="font-medium">{runResult.signal.time_horizon}</span>
                    </p>
                  )}
                </div>
                {runResult.signal?.executive_summary && (
                  <p className="mt-3 border-t border-border pt-3 text-sm text-muted-foreground">
                    {runResult.signal.executive_summary}
                  </p>
                )}
              </CardContent>
            </Card>

<Card className="md:col-span-2">
              <CardHeader>
                <CardTitle>Analysis Flow</CardTitle>
              </CardHeader>
              <CardContent>
                {groupedNodes(runResult.node_trace).map((group, gi) => (
                  <div key={gi} className="mb-4 last:mb-0">
                    <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.title}
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                      {group.items.map((n, i) => (
                        <div key={i} className="flex items-center gap-2 rounded-md bg-muted/40 p-2 text-sm">
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-positive" />
                          <span className="truncate capitalize">{n.label}</span>
                          {n.repeat && (
                            <span className="ml-auto text-xs text-muted-foreground">retry</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                {(!runResult.node_trace || runResult.node_trace.length === 0) && (
                  <p className="text-sm text-muted-foreground">No step trace recorded for this run.</p>
                )}
              </CardContent>
            </Card>
          </div>

<Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5" /> Final Decision
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <Markdown>{runResult.final_decision || "No decision text available."}</Markdown>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <Button onClick={simulate} disabled={runResult.simulated}>
                  {runResult.simulated ? "Simulated ✓" : "Simulate -> Portfolio"}
                </Button>
                <p className="text-xs text-muted-foreground">
                  Adds a paper holding on {runResult.symbol} at the current price.
                </p>
              </div>
              <div className="mt-4 p-4 bg-yellow-500/10 border border-yellow-500/30 rounded">
                <p className="text-sm text-yellow-600 dark:text-yellow-400">
                  <strong>Disclaimer:</strong> AI-generated research for educational purposes only. Not investment advice.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5" /> Technical Chart
              </CardTitle>
            </CardHeader>
            <CardContent>
              <TechnicalChart symbol={runResult.symbol} />
            </CardContent>
          </Card>

          {runResult.reports && (() => {
            const SECTIONS: Array<[string, string]> = [
              ["market_report", "Market / Technical View"],
              ["fundamentals_report", "Fundamentals"],
              ["news_report", "News & Sentiment"],
              ["sentiment_report", "Social Sentiment"],
              ["investment_plan", "Research Team Plan"],
              ["risk_report", "Risk Analysis"],
            ]
            const present = SECTIONS.filter(([k]) => runResult.reports?.[k])
            if (present.length === 0) return null
            return (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Bot className="h-5 w-5" /> AI Analysis Detail
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  {present.map(([key, title]) => (
                    <div key={key} className="rounded-lg border border-border bg-muted/20 p-4">
                      <h3 className="mb-2 text-sm font-semibold text-foreground">{title}</h3>
                      <Markdown>{runResult.reports?.[key] ?? ""}</Markdown>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )
          })()}

          {runResult.options && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5" /> Options View
                  <span
                    className={`ml-2 rounded px-2 py-0.5 text-xs font-bold ${
                      runResult.options.alignment === "aligned"
                        ? "bg-positive/15 text-positive border border-positive/30"
                        : runResult.options.alignment === "divergent"
                          ? "bg-negative/15 text-negative border border-negative/30"
                          : "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30"
                    }`}
                  >
                    {runResult.options.alignment}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {runResult.options.note && (
                  <div className="prose prose-sm dark:prose-invert max-w-none text-sm">
                    <Markdown>{runResult.options.note}</Markdown>
                  </div>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  {(Object.entries({
                    "Spot": runResult.options.spot_price,
                    "Max Pain": runResult.options.max_pain,
                    "IV Skew": runResult.options.iv_skew,
                    "ATM IV": runResult.options.atm_iv,
                    "P/C Premium": runResult.options.premium_put_call,
                    "Expiry": runResult.options.expiry,
                    "Bias": runResult.options.bias,
                  }) as Array<[string, number | string | null]>)
                    .filter(([, v]) => v !== null && v !== undefined)
                    .map(([k, v]) => (
                      <div key={k} className="rounded-md bg-muted/40 p-2">
                        <p className="text-xs text-muted-foreground">{k}</p>
                        <p className="font-medium">{typeof v === "number" ? v.toLocaleString() : v}</p>
                      </div>
                    ))}
                </div>
                {runResult.options.suggestion?.note && (
                  <p className="text-xs text-muted-foreground">{runResult.options.suggestion.note}</p>
                )}
                {runResult.options.option_leg && (
                  <div className="rounded-md border border-border bg-accent/10 p-3">
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Contract view · {runResult.options.option_leg.option_type} @{" "}
                      {runResult.options.option_leg.strike}
                      {runResult.options.option_leg.expiry
                        ? ` · ${String(runResult.options.option_leg.expiry).slice(0, 10)}`
                        : ""}
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                      {(Object.entries({
                        "Premium now": runResult.options.option_leg.current_premium,
                        "Premium target": runResult.options.option_leg.predicted_premium,
                        "Expected": runResult.options.option_leg.expected_return != null ? `${(runResult.options.option_leg.expected_return * 100).toFixed(1)}%` : null,
                        "Delta": runResult.options.option_leg.delta,
                        "IV": runResult.options.option_leg.iv != null ? `${(runResult.options.option_leg.iv * 100).toFixed(1)}%` : null,
                        "Spot": runResult.options.option_leg.spot_price,
                      }) as Array<[string, number | string | null]>)
                        .filter(([, v]) => v !== null && v !== undefined)
                        .map(([k, v]) => (
                          <div key={k} className="rounded-md bg-muted/40 p-2">
                            <p className="text-xs text-muted-foreground">{k}</p>
                            <p className="font-medium">{typeof v === "number" && k !== "Delta" ? v.toLocaleString() : v}</p>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Decision History</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-2 pr-4">Symbol</th>
                    <th className="py-2 pr-4">Date</th>
                    <th className="py-2 pr-4">Provider</th>
                    <th className="py-2 pr-4">Rating</th>
                    <th className="py-2 pr-4">Status</th>
<th className="py-2 pr-4">Simulated</th>
                    <th className="py-2 pr-4">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((r) => (
                    <tr
                      key={r.id}
                      className="border-b border-border/50 cursor-pointer hover:bg-muted/30"
                      onClick={() => fetchRunDetail(r.id)}
                    >
                      <td className="py-2 pr-4 font-medium">{r.symbol}</td>
                      <td className="py-2 pr-4">{r.trade_date}</td>
                      <td className="py-2 pr-4">{r.provider}</td>
                      <td className="py-2 pr-4">
                        {r.rating ? (
                          <span className={`rounded px-2 py-0.5 text-xs font-bold ${ratingStyle(r.rating)}`}>{r.rating}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        {r.status === "completed" ? (
                          <span className="flex items-center gap-1 text-positive"><CheckCircle2 className="h-3.5 w-3.5" /> completed</span>
                        ) : r.status === "failed" ? (
                          <span className="flex items-center gap-1 text-negative"><XCircle className="h-3.5 w-3.5" /> failed</span>
                        ) : (
                          r.status
                        )}
                      </td>
                      <td className="py-2 pr-4">{r.simulated ? "yes" : "no"}</td>
                      <td className="py-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Delete run"
                          onClick={(e) => {
                            e.stopPropagation()
                            deleteRun(r.id)
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-muted-foreground hover:text-negative" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
