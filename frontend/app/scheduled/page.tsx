"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api-client";
import SymbolPicker from "@/components/stock/SymbolPicker";
import ScheduledRunOutput from "@/components/stock/ScheduledRunOutput";
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel";
import { CalendarClock, Play, Trash2, Pencil, RefreshCw, Loader2, Plus, History } from "lucide-react";

interface SwarmPreset {
  id: string;
  name: string;
  description?: string;
}

interface Playbook {
  type: "technical_summary" | "backtest" | "factor_ic" | "swarm";
  symbol?: string;
  symbols?: string[];
  strategy?: string;
  interval?: string;
  period?: string;
  factors?: string[];
  preset?: string;
  forward_days?: number;
  [key: string]: unknown;
}

interface Schedule {
  id: string;
  name: string;
  playbook: Playbook;
  cron_expr: string;
  timezone: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string | null;
}

interface RunRecord {
  id: string;
  status: string;
  output: unknown;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
}

const PLAYBOOK_TYPES: { value: Playbook["type"]; label: string }[] = [
  { value: "technical_summary", label: "Technical summary" },
  { value: "backtest", label: "Backtest" },
  { value: "factor_ic", label: "Factor IC" },
  { value: "swarm", label: "Swarm DAG" },
];

export default function ScheduledPage() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [presets, setPresets] = useState<SwarmPreset[]>([]);
  const [backtestStrategies, setBacktestStrategies] = useState<string[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [cronExpr, setCronExpr] = useState("0 9 * * 1-5");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [pbType, setPbType] = useState<Playbook["type"]>("technical_summary");
  const [symbols, setSymbols] = useState<string[]>(["NSE:RELIANCE", "NSE:TCS"]);
  const [backtestSymbol, setBacktestSymbol] = useState("NSE:RELIANCE");
  const [backtestStrategy, setBacktestStrategy] = useState("moving_average_crossover");
  const [backtestInterval, setBacktestInterval] = useState("1d");
  const [swarmPreset, setSwarmPreset] = useState("quant-sweep");
  const [factorNames, setFactorNames] = useState("alpha101_001");
  const [forwardDays, setForwardDays] = useState("1");
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const [runsOpen, setRunsOpen] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadingList(true);
    try {
      const res = await api.get<Schedule[]>("/api/scheduled");
      setSchedules(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not load schedules.");
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    load();
    api.get<{ presets: SwarmPreset[] }>("/api/scheduled/presets").then((res) => setPresets(res.data.presets)).catch(() => setPresets([]));
    api
      .get<{ strategies: { name: string }[] }>("/api/analysis/backtest/strategies")
      .then((res) => setBacktestStrategies(res.data.strategies.map((s) => s.name)))
      .catch(() => setBacktestStrategies([]));
  }, [load]);

  const buildPlaybook = (): Playbook => {
    const base = { type: pbType };
    if (pbType === "backtest") return { ...base, symbol: backtestSymbol, strategy: backtestStrategy, interval: backtestInterval, period: "3y" };
    if (pbType === "swarm") return { ...base, preset: swarmPreset, symbols };
    if (pbType === "factor_ic") return { ...base, symbols, factors: splitList(factorNames), forward_days: Number(forwardDays) || 1 };
    return { ...base, symbols };
  };

  const splitList = (text: string) =>
    text
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean);

  const save = async () => {
    setSaving(true);
    setError(null);
    const body = { name, cron_expr: cronExpr, timezone, playbook: buildPlaybook() };
    try {
      if (editingId) {
        await api.patch(`/api/scheduled/${editingId}`, body);
      } else {
        await api.post("/api/scheduled", body);
      }
      resetForm();
      await load();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not save the schedule.");
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setEditingId(null);
    setName("");
    setCronExpr("0 9 * * 1-5");
    setTimezone("Asia/Kolkata");
    setPbType("technical_summary");
  };

  const toggleEnabled = async (s: Schedule) => {
    try {
      await api.patch(`/api/scheduled/${s.id}`, { enabled: !s.enabled });
      await load();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not toggle the schedule.");
    }
  };

  const remove = async (id: string) => {
    try {
      await api.delete(`/api/scheduled/${id}`);
      if (runsOpen === id) setRunsOpen(null);
      await load();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not delete the schedule.");
    }
  };

  const startEdit = (s: Schedule) => {
    setEditingId(s.id);
    setName(s.name);
    setCronExpr(s.cron_expr);
    setTimezone(s.timezone);
    setPbType(s.playbook.type);
    setSymbols(s.playbook.symbols || []);
    setBacktestSymbol(s.playbook.symbol || "");
    setBacktestStrategy((s.playbook.strategy as string) || "moving_average_crossover");
    setSwarmPreset((s.playbook.preset as string) || "quant-sweep");
    setFactorNames((s.playbook.factors || ["alpha101_001"]).join(", "));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const runNow = async (id: string) => {
    setRunningId(id);
    setError(null);
    try {
      const res = await api.post<Record<string, unknown>>(`/api/scheduled/${id}/run`);
      setRunOutput(id, res.data);
      await load();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not run the schedule now.");
    } finally {
      setRunningId(null);
    }
  };

  const setRunOutput = async (id: string, output: unknown) => {
    setRunsOpen(id);
    setRuns((prev) => [{ id: "now", status: "done", output, started_at: null, finished_at: null, created_at: null }, ...prev]);
    await openRuns(id);
  };

  const openRuns = async (id: string) => {
    if (runsOpen === id) {
      setRunsOpen(null);
      return;
    }
    setRunsOpen(id);
    setRunsLoading(true);
    try {
      const res = await api.get<RunRecord[]>(`/api/scheduled/${id}/runs?limit=10`);
      setRuns(res.data);
    } catch {
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  };

  const fmtTs = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Scheduled Research</h1>
          <p className="text-sm text-muted-foreground">
            Cron playbooks (technical summary, backtest, factor IC, swarm DAGs) on real data — IANA-timezone aware.
          </p>
        </div>
        <Button variant="outline" onClick={load} disabled={loadingList}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loadingList ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <AgenticTradingPanel symbol={symbols[0]} />

      {error && (
        <Card className="mb-6 border-destructive/50">
          <CardContent className="pt-6 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {editingId ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {editingId ? `Edit schedule` : "New schedule"}
          </CardTitle>
          <CardDescription>Cron fields: minute hour day-of-month month day-of-week (dow 0=Sunday).</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Daily morning review" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Cron</label>
              <Input value={cronExpr} onChange={(e) => setCronExpr(e.target.value)} placeholder="0 9 * * 1-5" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Timezone</label>
              <Input value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Asia/Kolkata" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Playbook type</label>
              <Select value={pbType} onValueChange={(v) => setPbType(v as Playbook["type"])}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PLAYBOOK_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {pbType === "backtest" ? (
              <>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Symbol</label>
                  <SymbolPicker single values={backtestSymbol ? [backtestSymbol] : []} onChange={(v) => setBacktestSymbol(v[0] ?? "")} placeholder="Search or type NSE:RELIANCE…" />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Strategy</label>
                  <Select value={backtestStrategy} onValueChange={setBacktestStrategy}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {backtestStrategies.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Interval</label>
                  <Select value={backtestInterval} onValueChange={setBacktestInterval}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {["1d", "1h", "15m", "5m"].map((i) => (
                        <SelectItem key={i} value={i}>
                          {i}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            ) : pbType === "swarm" ? (
              <>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Preset DAG</label>
                  <Select value={swarmPreset} onValueChange={setSwarmPreset}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {presets.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5 md:col-span-2">
                  <label className="text-xs text-muted-foreground">Symbols</label>
                  <SymbolPicker values={symbols} onChange={setSymbols} placeholder="Search and pick symbols…" />
                </div>
              </>
            ) : pbType === "factor_ic" ? (
              <>
                <div className="space-y-1.5 md:col-span-2">
                  <label className="text-xs text-muted-foreground">Symbols</label>
                  <SymbolPicker values={symbols} onChange={setSymbols} placeholder="Search and pick symbols…" />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Factors</label>
                  <Input value={factorNames} onChange={(e) => setFactorNames(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Forward days</label>
                  <Input type="number" value={forwardDays} onChange={(e) => setForwardDays(e.target.value)} />
                </div>
              </>
            ) : (
              <div className="space-y-1.5 md:col-span-3">
                <label className="text-xs text-muted-foreground">Symbols</label>
                <SymbolPicker values={symbols} onChange={setSymbols} placeholder="Search and pick symbols…" />
              </div>
            )}
          </div>

          <div className="mt-4 flex gap-2">
            <Button onClick={save} disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {editingId ? "Save changes" : "Create schedule"}
            </Button>
            {editingId && (
              <Button variant="outline" onClick={resetForm}>
                Cancel
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        {schedules.length === 0 && !loadingList && (
          <Card>
            <CardContent className="py-12 text-center text-sm text-muted-foreground">No schedules yet — create one above.</CardContent>
          </Card>
        )}
        {schedules.map((s) => (
          <Card key={s.id}>
            <CardContent className="pt-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{s.name}</span>
                    <Badge variant={s.enabled ? "default" : "outline"}>{s.enabled ? "enabled" : "paused"}</Badge>
                    <Badge variant="secondary">{s.playbook.type}</Badge>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <CalendarClock className="h-3.5 w-3.5" />
                      <span className="font-mono">{s.cron_expr}</span> · {s.timezone}
                    </span>
                    <span>next {fmtTs(s.next_run_at)}</span>
                    <span>last {fmtTs(s.last_run_at)}</span>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {s.playbook.symbols?.join(", ") || s.playbook.symbol || ""}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => runNow(s.id)} disabled={runningId === s.id}>
                    {runningId === s.id ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
                    Run now
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => openRuns(s.id)}>
                    <History className="mr-1.5 h-3.5 w-3.5" /> Runs
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => startEdit(s)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => toggleEnabled(s)}>
                    {s.enabled ? "Pause" : "Enable"}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => remove(s.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

              {runsOpen === s.id && (
                <div className="mt-4 rounded-md border p-3">
                  <h4 className="mb-2 text-xs font-medium text-muted-foreground">Recent runs</h4>
                  {runsLoading ? (
                    <p className="text-sm text-muted-foreground">Loading…</p>
                  ) : runs.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No runs recorded.</p>
                  ) : (
                    <div className="space-y-2">
                      {runs.map((r) => (
                        <details key={r.id} className="rounded-md border bg-muted/30 p-2">
                          <summary className="cursor-pointer text-xs">
                            <Badge variant={r.status === "done" ? "secondary" : "negative"} className="mr-2">
                              {r.status}
                            </Badge>
                            {fmtTs(r.created_at)} · {fmtTs(r.started_at)}
                          </summary>
                          <div className="mt-2 rounded bg-background p-3">
                            <ScheduledRunOutput output={r.output} />
                          </div>
                        </details>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
