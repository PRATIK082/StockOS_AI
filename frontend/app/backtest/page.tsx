"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import EquityChart from "@/components/stock/EquityChart";
import SymbolPicker from "@/components/stock/SymbolPicker";
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel";
import { api } from "@/lib/api-client";
import { fmt, fmtCompact } from "@/lib/api";
import { Loader2, Play, ShieldCheck, Wrench, Repeat, BarChart3, Boxes } from "lucide-react";

interface StrategyMeta {
  name: string;
  display_name: string;
  description: string;
  default_params: Record<string, number>;
  param_schema: Record<string, { type: string; min?: number; max?: number; step?: number }>;
}

interface StrategiesResponse {
  strategies: StrategyMeta[];
  optimizers: { name: string; display_name?: string; description?: string }[];
  costs: Record<string, number | string>;
}

interface UnderwaterEpisode {
  start: number;
  end: number;
  depth: number;
  start_index: number;
  end_index: number;
}

interface RiskXray {
  exposure_time: number;
  turnover_per_bar: number;
  tail_risk_pct: number;
  max_consecutive_losses: number;
  worst_period_return: number;
  best_period_return: number;
  downside_deviation: number;
  underwater_episodes: UnderwaterEpisode[];
}

interface BacktestResult {
  symbol: string;
  interval: string;
  strategy: string;
  initial_capital: number;
  dates: string[];
  equity: number[];
  positions: number[];
  trades: Record<string, unknown>[];
  metrics: Record<string, number>;
  risk: RiskXray;
  cost_config: Record<string, number | string>;
  n_bars: number;
  benchmark?: { symbol: string; equity: number[]; total_return: number; metrics: Record<string, number> };
  monte_carlo?: Record<string, number>;
  bootstrap?: {
    n_iterations: number;
    sharpe?: { median: number; p5: number; p95: number };
    sortino?: { median: number; p5: number; p95: number };
    vol?: { median: number; p5: number; p95: number };
    cagr?: { median: number; p5: number; p95: number };
  };
  walk_forward?: { n_folds: number; avg_test_sharpe: number; avg_test_return: number; avg_test_max_drawdown: number; overfit_gap: number };
  option_contract?: {
    symbol: string;
    option_type: string;
    strike: number;
    expiry: string;
    iv: number;
    spot_price: number;
    available_strikes: number[];
    available_expiries: string[];
  };
}

const INTERVALS = ["1d", "1h", "15m", "5m", "1m", "1wk", "1mo"];
const PERIODS = ["6mo", "1y", "2y", "3y", "5y"];

function metricCell(label: string, value: number, pct = false) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${pct ? (value >= 0 ? "text-positive" : "text-negative") : ""}`}>
        {pct ? `${(value * 100).toFixed(2)}%` : fmt(value, 2)}
      </div>
    </div>
  );
}

export default function BacktestPage() {
  const [meta, setMeta] = useState<StrategiesResponse | null>(null);
  const [symbol, setSymbol] = useState("NSE:RELIANCE");
  const [benchmark, setBenchmark] = useState("NSE:NIFTY");
  const [interval, setInterval] = useState("1d");
  const [period, setPeriod] = useState("2y");
  const [strategy, setStrategy] = useState("moving_average_crossover");
  const [capital, setCapital] = useState("100000");
  const [intraday, setIntraday] = useState(false);
  const [runValidation, setRunValidation] = useState(false);
  const [customCode, setCustomCode] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});

  const [useOptionContract, setUseOptionContract] = useState(false);
  const [optionType, setOptionType] = useState<"CE" | "PE">("CE");
  const [optionStrike, setOptionStrike] = useState("");
  const [optionExpiry, setOptionExpiry] = useState("");

  const chainQuery = useQuery({
    queryKey: ["option-chain-backtest", symbol],
    queryFn: () =>
      api
        .get<{ expiries: string[]; calls: { strike: number }[]; puts: { strike: number }[] }>(
          `/api/analysis/options/chain/${encodeURIComponent(symbol)}`
        )
        .catch(() => null),
    enabled: useOptionContract && Boolean(symbol),
    staleTime: 2 * 60 * 1000,
    retry: 1,
  });
  const chainStrikes = Array.from(
    new Set([
      ...(chainQuery.data?.data.calls.map((c) => c.strike) ?? []),
      ...(chainQuery.data?.data.puts.map((p) => p.strike) ?? []),
    ])
  ).sort((a, b) => a - b);
  const chainExpiries = chainQuery.data?.data.expiries ?? [];

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);

  useEffect(() => {
    api.get<StrategiesResponse>("/api/analysis/backtest/strategies").then((res) => setMeta(res.data)).catch(() => setMeta(null));
  }, []);

  const activeStrategy = meta?.strategies.find((s) => s.name === strategy) ?? null;
  useEffect(() => {
    if (activeStrategy) {
      const next: Record<string, string> = {};
      for (const [k, v] of Object.entries(activeStrategy.default_params)) next[k] = String(v);
      // Reset to the new strategy's defaults; only carry over user edits for
      // params that still exist (never leak keys from a previous strategy).
      setParams((prev) => {
        const merged: Record<string, string> = { ...next };
        for (const [k, v] of Object.entries(prev)) if (k in next) merged[k] = v;
        return merged;
      });
    }
  }, [strategy]);

  const runBacktest = async () => {
    setLoading(true);
    setError(null);
    const parsed: Record<string, number> = {};
    for (const [k, v] of Object.entries(params)) {
      const n = Number(v);
      if (Number.isFinite(n)) parsed[k] = n;
    }
    try {
      const res = await api.post<BacktestResult>("/api/analysis/backtest", {
        symbol,
        interval,
        period,
        strategy,
        params: parsed,
        initial_capital: Number(capital) || 100000,
        benchmark_symbol: benchmark.trim() || null,
        run_validation: runValidation,
        custom_code: customCode.trim() || null,
        intraday,
        ...(useOptionContract && optionStrike && !Number.isNaN(Number(optionStrike))
          ? {
              option_type: optionType,
              option_strike: Number(optionStrike),
              option_expiry: optionExpiry || null,
            }
          : {}),
      });
      setResult(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(detail ? String(detail) : "Could not run the backtest. Check the backend connection.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const m = result?.metrics;
  const trades = result?.trades ?? [];
  const equitySeries = result
    ? [
        {
          label: `${result.symbol} · ${result.strategy}`,
          data: result.dates.map((d, i) => ({ time: d, value: result.equity[i] })),
        },
        ...(result.benchmark
          ? [
              {
                label: `Benchmark ${result.benchmark.symbol}`,
                data: result.dates.slice(0, result.benchmark.equity.length).map((d, i) => ({
                  time: d,
                  value: result.benchmark!.equity[i],
                })),
              },
            ]
          : []),
      ]
    : [];

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Backtest Engine</h1>
          <p className="text-sm text-muted-foreground">
            Bar-level fills at next open, India cost stack, no look-ahead. Runs on real market data.
          </p>
        </div>
        <Button onClick={runBacktest} disabled={loading}>
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
          Run backtest
        </Button>
      </div>

      <AgenticTradingPanel symbol={symbol} />

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Configuration</CardTitle>
          {meta && meta.costs && (
            <CardDescription>
              Costs: buy {String(meta.costs.buy_cost_pct)}% · sell {String(meta.costs.sell_cost_pct)}% · per-trade{" "}
              {String(meta.costs.flat_fee)} ({intraday ? "intraday" : "delivery"} stack)
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Symbol</label>
              <SymbolPicker single values={symbol ? [symbol] : []} onChange={(v) => setSymbol(v[0] ?? "")} placeholder="Search or type NSE:RELIANCE…" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Benchmark (optional)</label>
              <SymbolPicker single values={benchmark ? [benchmark] : []} onChange={(v) => setBenchmark(v[0] ?? "")} placeholder="Search or type NSE:NIFTY…" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Interval</label>
              <Select value={interval} onValueChange={setInterval}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INTERVALS.map((i) => (
                    <SelectItem key={i} value={i}>
                      {i}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Period</label>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERIODS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Strategy</label>
              <Select value={strategy} onValueChange={setStrategy}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {meta?.strategies.map((s) => (
                    <SelectItem key={s.name} value={s.name}>
                      {s.display_name || s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {activeStrategy && <p className="text-[11px] text-muted-foreground">{activeStrategy.description}</p>}
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Initial capital</label>
              <Input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} />
            </div>
            {activeStrategy && Object.keys(activeStrategy.param_schema).length > 0 && (
              <div className="col-span-2 grid grid-cols-2 gap-3 md:grid-cols-4">
                {Object.entries(activeStrategy.param_schema).map(([k, schema]) => (
                  <div key={k} className="space-y-1.5">
                    <label className="text-xs text-muted-foreground">{k}</label>
                    <Input
                      type="number"
                      step={schema.step ?? 1}
                      value={params[k] ?? ""}
                      onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
            )}
            <div className="col-span-2 flex items-end gap-6 md:col-span-2">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={intraday} onChange={(e) => setIntraday(e.target.checked)} className="rounded" />
                Intraday cost stack
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={runValidation}
                  onChange={(e) => setRunValidation(e.target.checked)}
                  className="rounded"
                />
                Robustness validation (MC / bootstrap / walk-forward)
              </label>
            </div>
            <div className="col-span-2 space-y-1.5">
              <label className="text-xs text-muted-foreground">Custom strategy code (Python, AST-sandboxed — optional)</label>
              <Input
                value={customCode}
                onChange={(e) => setCustomCode(e.target.value)}
                placeholder="def generate_signals(df, fast=10, slow=50): ..."
              />
            </div>
            <div className="col-span-2 space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={useOptionContract}
                  onChange={(e) => {
                    setUseOptionContract(e.target.checked);
                    if (!e.target.checked) {
                      setOptionStrike("");
                      setOptionExpiry("");
                    }
                  }}
                  className="rounded"
                />
                Backtest an option contract (CE/PE) — run the strategy on the{" "}
                <span className="font-medium">theoretical premium</span> instead of the underlying
              </label>
              {useOptionContract && (
                <div className="grid grid-cols-3 gap-3 rounded-md border p-3">
                  <div className="space-y-1.5">
                    <label className="text-xs text-muted-foreground">Type</label>
                    <Select value={optionType} onValueChange={(v) => setOptionType(v as "CE" | "PE")}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="CE">CALL (CE)</SelectItem>
                        <SelectItem value="PE">PUT (PE)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs text-muted-foreground">Strike</label>
                    <Select value={optionStrike} onValueChange={setOptionStrike} disabled={chainStrikes.length === 0}>
                      <SelectTrigger>
                        <SelectValue placeholder={chainStrikes.length === 0 ? "No chain" : "Pick strike"} />
                      </SelectTrigger>
                      <SelectContent className="max-h-72">
                        {chainStrikes.length === 0 && (
                          <SelectItem value="__none__" disabled>
                            {chainQuery.isLoading ? "Loading chain…" : "No chain for this symbol"}
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
                  <div className="space-y-1.5">
                    <label className="text-xs text-muted-foreground">Expiry</label>
                    <Select value={optionExpiry} onValueChange={setOptionExpiry} disabled={chainExpiries.length === 0}>
                      <SelectTrigger>
                        <SelectValue placeholder={chainExpiries.length === 0 ? "—" : "Pick expiry"} />
                      </SelectTrigger>
                      <SelectContent>
                        {chainExpiries.map((d) => (
                          <SelectItem key={d} value={d.slice(0, 10)}>
                            {d.slice(0, 10)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {chainStrikes.length === 0 && (
                    <p className="col-span-3 text-[11px] text-muted-foreground">
                      Pick a symbol with an F&O chain (e.g. NSE:NIFTY, NSE:BANKNIFTY, NSE:RELIANCE) to backtest a
                      contract.
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card className="mb-6 border-destructive/50">
          <CardContent className="pt-6 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {result && m && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <Badge>{result.symbol}</Badge>
            {result.option_contract && (
              <Badge variant="outline">
                <Boxes className="mr-1 h-3 w-3" />
                {result.option_contract.option_type} {result.option_contract.strike} @{" "}
                {result.option_contract.expiry.slice(0, 10)}
              </Badge>
            )}
            <Badge variant="secondary">
              {result.strategy} · {result.interval} · {result.n_bars} bars
            </Badge>
            <Badge variant="outline">Final ₹{fmt(m.final_equity, 0)}</Badge>
          </div>

          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BarChart3 className="h-4 w-4" /> Equity curve
              </CardTitle>
            </CardHeader>
            <CardContent>
              <EquityChart series={equitySeries} height={360} />
              {result.benchmark && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Strategy {fmt(m.total_return * 100, 2)}% vs benchmark {fmt(result.benchmark.total_return * 100, 2)}%
                </p>
              )}
            </CardContent>
          </Card>

          <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
            {metricCell("Total return", m.total_return, true)}
            {metricCell("Annualized return", m.annualized_return, true)}
            {metricCell("Sharpe", m.sharpe_ratio)}
            {metricCell("Sortino", m.sortino_ratio)}
            {metricCell("Max drawdown", m.max_drawdown, true)}
            {metricCell("Annualized vol", m.annualized_vol, true)}
            {metricCell("VaR 95", m.var_95, true)}
            {metricCell("CVaR 95", m.cvar_95, true)}
            {metricCell("Calmar", m.calmar_ratio)}
            {metricCell("Skewness", m.skewness)}
            {metricCell("Kurtosis", m.kurtosis)}
            {metricCell("Periods", m.n_periods)}
          </div>

          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Wrench className="h-4 w-4" /> Risk x-ray
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 text-sm">
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Exposure time</span>
                  <span>{fmt(result.risk.exposure_time * 100, 1)}%</span>
                </div>
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Turnover / bar</span>
                  <span>{fmt(result.risk.turnover_per_bar * 100, 2)}%</span>
                </div>
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Tail risk</span>
                  <span>{fmt(result.risk.tail_risk_pct, 1)}%</span>
                </div>
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Max consecutive losses</span>
                  <span>{result.risk.max_consecutive_losses}</span>
                </div>
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Worst period</span>
                  <span className="text-negative">{fmt(result.risk.worst_period_return * 100, 2)}%</span>
                </div>
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Best period</span>
                  <span className="text-positive">{fmt(result.risk.best_period_return * 100, 2)}%</span>
                </div>
                <div className="flex justify-between border-b py-1">
                  <span className="text-muted-foreground">Downside deviation</span>
                  <span>{fmt(result.risk.downside_deviation * 100, 2)}%</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-muted-foreground">Underwater episodes</span>
                  <span>{result.risk.underwater_episodes.length}</span>
                </div>
                {result.risk.underwater_episodes.length > 0 && (
                  <div className="col-span-2 mt-2">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>From</TableHead>
                          <TableHead>To</TableHead>
                          <TableHead>Depth</TableHead>
                          <TableHead>Peak value</TableHead>
                          <TableHead>End value</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.risk.underwater_episodes.map((ep, i) => (
                          <TableRow key={i}>
                            <TableCell>{result.dates[ep.start_index] ?? "—"}</TableCell>
                            <TableCell>{result.dates[ep.end_index] ?? "—"}</TableCell>
                            <TableCell className="text-negative">{fmt(ep.depth * 100, 2)}%</TableCell>
                            <TableCell>{fmt(ep.start, 0)}</TableCell>
                            <TableCell>{fmt(ep.end, 0)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Repeat className="h-4 w-4" /> Trades summary
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 text-sm">
                {(m.trades as any) ? (
                  <>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Total trades</span>
                      <span>{(m.trades as any).total_trades}</span>
                    </div>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Win rate</span>
                      <span>{fmt(((m.trades as any).win_rate ?? 0) * 100, 1)}%</span>
                    </div>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Profit factor</span>
                      <span>{fmt((m.trades as any).profit_factor, 2)}</span>
                    </div>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Avg holding</span>
                      <span>{fmt((m.trades as any).avg_holding_periods, 1)} bars</span>
                    </div>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Avg win</span>
                      <span className="text-positive">{fmt(((m.trades as any).avg_win ?? 0) * 100, 2)}%</span>
                    </div>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Avg loss</span>
                      <span className="text-negative">{fmt(((m.trades as any).avg_loss ?? 0) * 100, 2)}%</span>
                    </div>
                    <div className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">Best trade</span>
                      <span className="text-positive">{fmt(((m.trades as any).best_trade ?? 0) * 100, 2)}%</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span className="text-muted-foreground">Worst trade</span>
                      <span className="text-negative">{fmt(((m.trades as any).worst_trade ?? 0) * 100, 2)}%</span>
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">No trades.</p>
                )}
              </CardContent>
            </Card>
          </div>

          {runValidation && (result.monte_carlo || result.bootstrap || result.walk_forward) && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldCheck className="h-4 w-4" /> Robustness validation
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                {result.monte_carlo && (
                  <div>
                    <h4 className="mb-2 text-sm font-medium">Monte Carlo ({result.monte_carlo.n_simulations} paths)</h4>
                    <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-3">
                      <div>Terminal median: <span className="font-semibold">{fmt(result.monte_carlo.terminal_median, 2)}×</span></div>
                      <div>P5–P95: <span className="font-semibold">{fmt(result.monte_carlo.terminal_p5, 2)}–{fmt(result.monte_carlo.terminal_p95, 2)}×</span></div>
                      <div>Prob loss: <span className="font-semibold">{fmt(result.monte_carlo.terminal_prob_loss * 100, 1)}%</span></div>
                      <div>MDD median: <span className="font-semibold">{fmt(result.monte_carlo.max_drawdown_median * 100, 1)}%</span></div>
                      <div>MDD P95: <span className="font-semibold">{fmt(result.monte_carlo.max_drawdown_p95 * 100, 1)}%</span></div>
                      <div>MDD worst: <span className="font-semibold">{fmt(result.monte_carlo.max_drawdown_worst * 100, 1)}%</span></div>
                    </div>
                  </div>
                )}
                {result.bootstrap && (
                  <div>
                    <h4 className="mb-2 text-sm font-medium">Bootstrap metrics ({result.bootstrap.n_iterations} resamples)</h4>
                    <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                      {(["sharpe", "sortino", "vol", "cagr"] as const).map((k) => {
                        const v = result.bootstrap![k];
                        return v ? (
                          <div key={k} className="rounded-md border p-2">
                            <div className="text-xs text-muted-foreground">{k}</div>
                            <div className="font-semibold">{fmt(v.median, 2)}</div>
                            <div className="text-xs text-muted-foreground">P5 {fmt(v.p5, 2)} · P95 {fmt(v.p95, 2)}</div>
                          </div>
                        ) : null;
                      })}
                    </div>
                  </div>
                )}
                {result.walk_forward && (
                  <div>
                    <h4 className="mb-2 text-sm font-medium">Walk-forward ({result.walk_forward.n_folds} folds)</h4>
                    <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                      <div>Avg test Sharpe: <span className="font-semibold">{fmt(result.walk_forward.avg_test_sharpe, 2)}</span></div>
                      <div>Avg test return: <span className="font-semibold">{fmt(result.walk_forward.avg_test_return * 100, 2)}%</span></div>
                      <div>Avg test MDD: <span className="font-semibold">{fmt(result.walk_forward.avg_test_max_drawdown * 100, 1)}%</span></div>
                      <div>Overfit gap: <span className="font-semibold">{fmt(result.walk_forward.overfit_gap, 2)}</span></div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {trades.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Trades ({trades.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>#</TableHead>
                      <TableHead>Entry price</TableHead>
                      <TableHead>Exit price</TableHead>
                      <TableHead>Holding</TableHead>
                      <TableHead>P&L %</TableHead>
                      <TableHead>P&L ₹</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {trades.slice(0, 100).map((t, i) => (
                      <TableRow key={i}>
                        <TableCell>{i + 1}</TableCell>
                        <TableCell>{fmt(t.entry_price as number, 2)}</TableCell>
                        <TableCell>{fmt(t.exit_price as number, 2)}</TableCell>
                        <TableCell>{t.holding_periods as number}</TableCell>
                        <TableCell className={((t.pnl_pct as number) ?? 0) >= 0 ? "text-positive" : "text-negative"}>
                          {fmt((t.pnl_pct as number) * 100, 2)}%
                        </TableCell>
                        <TableCell>{fmt(t.pnl as number, 0)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  {fmtCompact(result.initial_capital)} initial capital. Values are indicative of fill-level accounting.
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {!result && !error && (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            Configure the run above and press <span className="font-medium text-foreground">Run backtest</span>. Results render here.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
