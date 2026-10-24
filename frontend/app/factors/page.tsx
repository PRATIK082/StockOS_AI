"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import EquityChart from "@/components/stock/EquityChart";
import SymbolPicker from "@/components/stock/SymbolPicker";
import ResearchPanel from "@/components/stock/ResearchPanel";
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel";
import { api } from "@/lib/api-client";
import { fmt } from "@/lib/api";
import { Loader2, Sigma, Activity, Blend, Play, LineChart } from "lucide-react";

interface FactorMeta {
  name: string;
  family: string;
  category: string;
  description: string;
}

interface IcEntry {
  ic_mean: number;
  ic_ir: number;
  ic_std: number;
  n_days: number;
  series: { date: string; ic: number }[];
}

interface QuantileEntry {
  Q1?: { mean: number; n: number };
  Q2?: { mean: number; n: number };
  Q3?: { mean: number; n: number };
  Q4?: { mean: number; n: number };
  Q5?: { mean: number; n: number };
  spread?: number;
  [key: string]: unknown;
}

const DEFAULT_FACTORS = ["alpha101_001", "alpha101_002", "alpha101_003", "alpha101_004", "alpha101_012", "alpha101_101"];

export default function FactorsPage() {
  const [registry, setRegistry] = useState<FactorMeta[]>([]);
  const [tab, setTab] = useState("analysis");

  const [symbols, setSymbols] = useState<string[]>(["NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY", "NSE:SBIN", "NSE:AXISBANK"]);
  const [selectedFactors, setSelectedFactors] = useState<string[]>(DEFAULT_FACTORS);
  const [factorFilter, setFactorFilter] = useState("");
  const [forwardDays, setForwardDays] = useState("1");
  const [nQuantiles, setNQuantiles] = useState("5");

  const [benchFactor, setBenchFactor] = useState("alpha101_001");

  const [blendWeightsText, setBlendWeightsText] = useState(
    "alpha101_001: 0.4,\nalpha101_002: 0.3,\nalpha101_003: 0.3"
  );
  const [blendMethod, setBlendMethod] = useState("rank");
  const [blendLongOnly, setBlendLongOnly] = useState(true);

  const [loading, setLoading] = useState<null | "analysis" | "bench" | "blend">(null);
  const [error, setError] = useState<string | null>(null);

  const [icResult, setIcResult] = useState<Record<string, IcEntry> | null>(null);
  const [quantileResult, setQuantileResult] = useState<Record<string, QuantileEntry> | null>(null);
  const [benchResult, setBenchResult] = useState<any>(null);
  const [blendResult, setBlendResult] = useState<any>(null);
  const [runMeta, setRunMeta] = useState<{ symbols: string[]; failures: string[]; interval: string; forward_days: number; n_quantiles: number } | null>(null);

  useEffect(() => {
    api.get<{ factors: FactorMeta[] }>("/api/quant/factors").then((res) => setRegistry(res.data.factors)).catch(() => setRegistry([]));
  }, []);

  const filteredFactors = useMemo(() => {
    const q = factorFilter.toLowerCase();
    return registry.filter((f) => !q || f.name.toLowerCase().includes(q)).slice(0, 200);
  }, [registry, factorFilter]);

  const toggleFactor = (name: string) => {
    setSelectedFactors((prev) => (prev.includes(name) ? prev.filter((f) => f !== name) : [...prev, name]));
  };

  const runAnalysis = async () => {
    setLoading("analysis");
    setError(null);
    try {
      const res = await api.post("/api/quant/factors/analysis", {
        symbols,
        factors: selectedFactors,
        interval: "1d",
        period: "2y",
        forward_days: Number(forwardDays) || 1,
        n_quantiles: Number(nQuantiles) || 5,
      });
      setIcResult(res.data.ic);
      setQuantileResult(res.data.quantiles);
      setRunMeta({ symbols: res.data.symbols, failures: res.data.failures, interval: res.data.interval, forward_days: res.data.forward_days, n_quantiles: res.data.n_quantiles });
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Analysis failed. Check the backend connection.");
      setIcResult(null);
      setQuantileResult(null);
    } finally {
      setLoading(null);
    }
  };

  const runBench = async () => {
    setLoading("bench");
    setError(null);
    try {
      const res = await api.post("/api/quant/factors/bench", {
        symbols,
        factors: [benchFactor],
        interval: "1d",
        period: "2y",
        forward_days: Number(forwardDays) || 1,
        n_quantiles: Number(nQuantiles) || 5,
      });
      setBenchResult(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Bench failed. Check the backend connection.");
      setBenchResult(null);
    } finally {
      setLoading(null);
    }
  };

  const runBlend = async () => {
    setLoading("blend");
    setError(null);
    const weights: Record<string, number> = {};
    for (const line of blendWeightsText.split("\n")) {
      const m = line.match(/\s*([\w.]+)\s*:\s*([\d.]+)/);
      if (m) weights[m[1]] = Number(m[2]);
    }
    try {
      const res = await api.post("/api/quant/signals/blend", {
        symbols,
        weights,
        method: blendMethod,
        interval: "1d",
        period: "2y",
        n_quantiles: Number(nQuantiles) || 5,
        long_only: blendLongOnly,
      });
      setBlendResult(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Blend failed. Check the backend connection.");
      setBlendResult(null);
    } finally {
      setLoading(null);
    }
  };

  const sortedFactors = icResult ? Object.keys(icResult).sort((a, b) => (icResult[b].ic_mean || 0) - (icResult[a].ic_mean || 0)) : [];

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold">Factor Lab</h1>
        <p className="text-sm text-muted-foreground">
          {registry.length || "101"} factor zoo (alpha101) — rank IC, quantile returns, long-short benches and
          weighted signal blends, all on real cross-sectional data.
        </p>
      </div>

      <AgenticTradingPanel symbol={symbols[0]} />

      <Card className="mb-6">
        <CardContent className="pt-6">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-1.5 md:col-span-1">
              <label className="text-xs text-muted-foreground">Symbols</label>
              <SymbolPicker values={symbols} onChange={setSymbols} placeholder="Search and pick symbols…" />
              <p className="text-[11px] text-muted-foreground">Pick symbols from the autocomplete — they are kept as chips.</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Forward days</label>
              <Input type="number" value={forwardDays} onChange={(e) => setForwardDays(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Quantiles</label>
              <Input type="number" value={nQuantiles} onChange={(e) => setNQuantiles(e.target.value)} />
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="analysis" className="gap-1.5">
            <Sigma className="h-4 w-4" /> Factor analysis
          </TabsTrigger>
          <TabsTrigger value="bench" className="gap-1.5">
            <Activity className="h-4 w-4" /> Long-short bench
          </TabsTrigger>
          <TabsTrigger value="blend" className="gap-1.5">
            <Blend className="h-4 w-4" /> Signal blend
          </TabsTrigger>
          <TabsTrigger value="research" className="gap-1.5">
            <LineChart className="h-4 w-4" /> Symbol research
          </TabsTrigger>
        </TabsList>

        {error && (
          <Card className="mb-6 border-destructive/50">
            <CardContent className="pt-6 text-sm text-destructive">{error}</CardContent>
          </Card>
        )}

        <TabsContent value="analysis">
          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="text-base">Factors to test</CardTitle>
              <CardDescription>
                {selectedFactors.length} selected · {registry.length} available in the zoo
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Input
                value={factorFilter}
                onChange={(e) => setFactorFilter(e.target.value)}
                placeholder="Filter factors…"
                className="mb-3"
              />
              <div className="max-h-48 overflow-y-auto rounded-md border">
                {filteredFactors.map((f) => (
                  <label key={f.name} className="flex cursor-pointer items-center gap-2 border-b px-3 py-1.5 text-sm last:border-0 hover:bg-muted">
                    <input
                      type="checkbox"
                      checked={selectedFactors.includes(f.name)}
                      onChange={() => toggleFactor(f.name)}
                      className="rounded"
                    />
                    <span className="font-mono text-xs">{f.name}</span>
                    <span className="truncate text-xs text-muted-foreground">{f.description || f.category}</span>
                  </label>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={() => setSelectedFactors(DEFAULT_FACTORS)}>
                  Use defaults
                </Button>
                <Button size="sm" variant="outline" onClick={() => setSelectedFactors(registry.slice(0, 10).map((f) => f.name))}>
                  Top 10
                </Button>
                <Button size="sm" variant="outline" onClick={() => setSelectedFactors([])}>
                  Clear
                </Button>
                <Button size="sm" onClick={runAnalysis} disabled={loading === "analysis"} className="ml-auto">
                  {loading === "analysis" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                  Run analysis
                </Button>
              </div>
            </CardContent>
          </Card>

          {runMeta && (
            <p className="mb-4 text-xs text-muted-foreground">
              {runMeta.symbols.join(", ")}
              {runMeta.failures.length > 0 && <span className="text-negative"> · failed: {runMeta.failures.join(", ")}</span>}
            </p>
          )}

          {icResult && (
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Rank IC ({forwardDays}d forward)</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Factor</TableHead>
                        <TableHead>IC</TableHead>
                        <TableHead>ICIR</TableHead>
                        <TableHead>Days</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sortedFactors.map((name) => {
                        const e = icResult[name];
                        return (
                          <TableRow key={name}>
                            <TableCell className="font-mono text-xs">{name}</TableCell>
                            <TableCell className={e.ic_mean >= 0 ? "text-positive" : "text-negative"}>{fmt(e.ic_mean, 3)}</TableCell>
                            <TableCell>{fmt(e.ic_ir, 2)}</TableCell>
                            <TableCell>{e.n_days}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Quantile mean returns</CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  {quantileResult &&
                    sortedFactors.map((name) => {
                      const q = quantileResult[name];
                      const rows = Object.entries(q ?? {}).filter(([k]) => /^Q\d+$/.test(k)) as [string, { mean: number; n: number }][];
                      if (!rows.length) return null;
                      const maxAbs = Math.max(...rows.map(([, v]) => Math.abs(v.mean)), 1e-9);
                      return (
                        <div key={name}>
                          <div className="mb-1 flex items-center justify-between text-xs">
                            <span className="font-mono">{name}</span>
                            <span className="text-muted-foreground">
                              spread {fmt(((q as any)?.spread ?? 0) * 100, 2)}%
                            </span>
                          </div>
                          <div className="flex h-5 gap-1">
                            {rows.map(([label, v]) => (
                              <div key={label} className="relative flex-1 rounded bg-muted">
                                <div
                                  className={`absolute inset-y-0 left-0 rounded ${v.mean >= 0 ? "bg-positive/70" : "bg-negative/70"}`}
                                  style={{ width: `${Math.min(Math.abs(v.mean) / maxAbs, 1) * 100}%` }}
                                  title={`${label} ${fmt(v.mean * 100, 2)}% (n=${v.n})`}
                                />
                                <span className="absolute inset-0 flex items-center justify-center text-[10px] text-foreground">
                                  {fmt(v.mean * 100, 1)}%
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="bench">
          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="text-base">Long-short factor bench</CardTitle>
              <CardDescription>Top minus bottom quantile, equal-weight, daily-rebalanced on real forward returns.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap items-end gap-4">
              <div className="w-72 space-y-1.5">
                <label className="text-xs text-muted-foreground">Factor</label>
                <Select value={benchFactor} onValueChange={setBenchFactor}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="max-h-80">
                    {registry.map((f) => (
                      <SelectItem key={f.name} value={f.name}>
                        {f.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={runBench} disabled={loading === "bench"}>
                {loading === "bench" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                Run bench
              </Button>
            </CardContent>
          </Card>

          {benchResult && (
            <>
              <Card className="mb-6">
                <CardHeader>
                  <CardTitle className="text-base">Long-short equity ({benchFactor})</CardTitle>
                </CardHeader>
                <CardContent>
                  <EquityChart
                    height={320}
                    series={[
                      { label: `${benchFactor} LS`, data: benchResult.dates.map((d: string, i: number) => ({ time: d, value: benchResult.equity[i] })) },
                    ]}
                  />
                  <p className="mt-2 text-xs text-muted-foreground">
                    {benchResult.n_days} rebalance days · total {fmt(benchResult.total_return * 100, 2)}% · annualized{" "}
                    {fmt(benchResult.annualized_return * 100, 2)}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Per-quantile returns</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
                    {Object.entries(benchResult.quantiles ?? {}).map(([q, v]: [string, any]) => (
                      <div key={q} className="rounded-md border p-3">
                        <div className="text-xs text-muted-foreground">{q}</div>
                        <div className={`text-lg font-semibold ${(v.mean ?? 0) >= 0 ? "text-positive" : "text-negative"}`}>
                          {fmt((v.mean ?? 0) * 100, 2)}%
                        </div>
                        <div className="text-xs text-muted-foreground">n={v.n}</div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>

        <TabsContent value="blend">
          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="text-base">Composite signal portfolio backtest</CardTitle>
              <CardDescription>
                Weighted rank/zscore blend across the cross-section, rotated into the top quantile each day.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">Weights (factor: weight per line)</label>
                  <textarea
                    value={blendWeightsText}
                    onChange={(e) => setBlendWeightsText(e.target.value)}
                    className="min-h-24 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-sm"
                  />
                </div>
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-xs text-muted-foreground">Method</label>
                    <Select value={blendMethod} onValueChange={setBlendMethod}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="rank">Rank (cross-sectional)</SelectItem>
                        <SelectItem value="zscore">Z-score (cross-sectional)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={blendLongOnly} onChange={(e) => setBlendLongOnly(e.target.checked)} className="rounded" />
                    Long-only (off = long-short top minus bottom)
                  </label>
                  <Button onClick={runBlend} disabled={loading === "blend"}>
                    {loading === "blend" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                    Run blend backtest
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {blendResult && (
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Composite equity curve</CardTitle>
                </CardHeader>
                <CardContent>
                  <EquityChart
                    height={320}
                    series={[
                      { label: "Composite", data: blendResult.dates.map((d: string, i: number) => ({ time: d, value: blendResult.equity[i] })) },
                    ]}
                  />
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    {Object.entries(blendResult.weights ?? {}).map(([f, w]) => (
                      <Badge key={f} variant="outline">
                        {f} {Number(w).toFixed(2)}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Metrics</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-2 gap-3 text-sm">
                  {(
                    [
                      ["Total return", blendResult.metrics.total_return],
                      ["Annualized", blendResult.metrics.annualized_return],
                      ["Sharpe", blendResult.metrics.sharpe_ratio],
                      ["Sortino", blendResult.metrics.sortino_ratio],
                      ["Max drawdown", blendResult.metrics.max_drawdown],
                      ["Vol", blendResult.metrics.annualized_vol],
                      ["VaR 95", blendResult.metrics.var_95],
                      ["CVaR 95", blendResult.metrics.cvar_95],
                    ] as [string, number][]
                  ).map(([label, v]) => (
                    <div key={label} className="flex justify-between border-b py-1">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-medium">
                        {label.includes("return") || label.includes("drawdown") || label.includes("vol") || label.includes("VaR")
                          ? `${fmt(v * 100, 2)}%`
                          : fmt(v, 2)}
                      </span>
                    </div>
                  ))}
                  <div className="col-span-2 text-xs text-muted-foreground">
                    {blendResult.symbols?.join(", ")}
                    {blendResult.failures?.length > 0 && (
                      <span className="text-negative"> · failed: {blendResult.failures.join(", ")}</span>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="research">
          <ResearchPanel initialSymbol={symbols[0] || "NSE:RELIANCE"} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
