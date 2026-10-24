"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api-client";
import { Sparkline } from "@/components/trading/Sparkline";
import DeepAnalysisPanel, { type DeepAnalysisSymbol } from "@/components/stock/DeepAnalysisPanel";
import { Activity, AlertCircle, CheckCircle2, Clock, Loader2, RefreshCw, Search, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface IntradayRow {
  symbol: string;
  name: string;
  market: string;
  currency?: string;
  index?: boolean;
  source?: string;
  error?: string | null;
  last?: number | null;
  prev_close?: number | null;
  day_open?: number | null;
  high?: number | null;
  low?: number | null;
  change?: number | null;
  change_pct?: number | null;
  day_volume?: number | null;
  sparkline?: number[];
  bars?: number;
}

interface IntradayBoard {
  market: string;
  interval: string;
  period: string;
  generated_at?: string | null;
  rows: IntradayRow[];
  total: number;
  errors: number;
}

interface CoverageInfo {
  available?: boolean;
  provider?: string;
  note?: string;
  expiries?: string[];
  strikes?: number;
  error?: string;
}

const INTERVALS = ["1m", "5m", "15m", "1h", "1d"] as const;
const PERIODS = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"] as const;

const INTERVAL_PERIOD_LIMIT: Record<string, string> = { "1m": "5d", "5m": "1mo", "15m": "1mo", "1h": "1y" };
const PERIOD_ORDER = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"];

function clampPeriod(interval: string, period: string): string {
  const cap = INTERVAL_PERIOD_LIMIT[interval];
  if (!cap) return period;
  return PERIOD_ORDER.indexOf(period) > PERIOD_ORDER.indexOf(cap) ? cap : period;
}

function fmt(n: number | null | undefined, currency?: string, digits = 2): string {
  if (n == null) return "—";
  const sym = currency === "INR" ? "₹" : "$";
  return `${sym}${n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
}

function fmtCompact(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return `${n}`;
}

function Pct({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="text-muted-foreground">—</span>;
  const up = v > 0;
  return (
    <span className={cn("font-mono text-xs font-semibold tabular-nums", up ? "text-emerald-500" : v < 0 ? "text-red-500" : "text-muted-foreground")}>
      {up ? "+" : ""}
      {v.toFixed(2)}%
    </span>
  );
}

export default function IntradayPage() {
  const [market, setMarket] = useState<"india" | "us">("india");
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>("1m");
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("5d");
  const [board, setBoard] = useState<IntradayBoard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [coverage, setCoverage] = useState<Record<string, CoverageInfo> | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [askOpen, setAskOpen] = useState(false);

  const fetchBoard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<IntradayBoard>("/api/analysis/intraday", {
        params: { market, interval, period: clampPeriod(interval, period), limit: 120 },
      });
      setBoard(res.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? "Failed to load intraday board");
    } finally {
      setLoading(false);
    }
  }, [market, interval, period]);

  useEffect(() => {
    void fetchBoard();
  }, [fetchBoard]);

  const fetchCoverage = useCallback(async () => {
    setCoverageLoading(true);
    try {
      const res = await api.get<{ market: string; checked: number; available: number; items: Record<string, CoverageInfo> }>(
        "/api/analysis/options/coverage",
        { params: { market, limit: 120 }, timeout: 120000 },
      );
      setCoverage(res.data.items ?? {});
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? "Failed to load options coverage");
    } finally {
      setCoverageLoading(false);
    }
  }, [market]);

  const rows = board?.rows ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));
  }, [rows, query]);

  const indices = filtered.filter((r) => r.index && r.last != null);
  const stocks = filtered.filter((r) => !r.index);

  const panelSymbols = useMemo<DeepAnalysisSymbol[]>(
    () =>
      rows
        .filter((r) => r.last != null)
        .map((r) => ({ symbol: r.symbol, name: r.name, index: !!r.index })),
    [rows],
  );

  const toggleSelect = (symbol: string) => {
    setSelected((s) => (s.includes(symbol) ? s.filter((x) => x !== symbol) : [...s, symbol]));
  };

  const checkedCount = selected.length;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-wrap items-center justify-between gap-3 text-base">
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" /> Intraday Market — {market === "india" ? "India (NSE/BSE)" : "US (NYSE/NASDAQ)"}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex rounded-lg border p-0.5">
                {(["india", "us"] as const).map((m) => (
                  <button
                    key={m}
                    className={cn(
                      "rounded-md px-3 py-1 text-xs font-medium",
                      market === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
                    )}
                    onClick={() => {
                      setMarket(m);
                      setCoverage(null);
                      setSelected([]);
                    }}
                  >
                    {m === "india" ? "India" : "US"}
                  </button>
                ))}
              </div>
              <Button size="sm" variant="outline" onClick={() => void fetchBoard()} disabled={loading}>
                {loading ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-2 h-3.5 w-3.5" />}
                Refresh
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg border p-0.5">
              {INTERVALS.map((iv) => (
                <button
                  key={iv}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium",
                    interval === iv ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
                  )}
                  onClick={() => setInterval(iv)}
                >
                  {iv}
                </button>
              ))}
            </div>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value as (typeof PERIODS)[number])}
              className="rounded-md border bg-background px-2 py-1 text-xs"
              aria-label="Period"
            >
              {PERIODS.map((p) => (
                <option key={p} value={p} disabled={INTERVAL_PERIOD_LIMIT[interval] ? PERIOD_ORDER.indexOf(p) > PERIOD_ORDER.indexOf(INTERVAL_PERIOD_LIMIT[interval]) : false}>
                  {p}
                </option>
              ))}
            </select>
            {INTERVAL_PERIOD_LIMIT[interval] && (
              <span className="text-[10px] text-muted-foreground">intraday capped at {INTERVAL_PERIOD_LIMIT[interval]}</span>
            )}
            <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
              {board?.generated_at && (
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" /> {new Date(board.generated_at).toLocaleTimeString()}
                </span>
              )}
              <span>
                {board?.errors ? `${board.total - board.errors} of ${board.total} live` : `${board?.total ?? 0} live`}
              </span>
              <Button size="sm" variant="ghost" className="h-6 gap-1 text-xs" onClick={() => void fetchCoverage()} disabled={coverageLoading}>
                {coverageLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                F&O chains
              </Button>
            </div>
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter symbols…" className="pl-9" />
          </div>

          {error && (
            <p className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" /> {error}
            </p>
          )}

          {loading && !board && <p className="py-8 text-center text-sm text-muted-foreground">Loading live intraday board…</p>}

          {!loading && indices.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {indices.map((r) => (
                <IndexCard key={r.symbol} row={r} coverage={coverage?.[r.symbol]} onToggle={() => toggleSelect(r.symbol)} selected={selected.includes(r.symbol)} />
              ))}
            </div>
          )}

          {!loading && stocks.length > 0 && (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-2 py-2" />
                    <th className="px-2 py-2">Symbol</th>
                    <th className="px-2 py-2 text-right">Last</th>
                    <th className="px-2 py-2 text-right">Chg%</th>
                    <th className="px-2 py-2 text-right">Day range</th>
                    <th className="px-2 py-2 text-right">Volume</th>
                    <th className="px-2 py-2">Intraday</th>
                    <th className="px-2 py-2 text-right">F&O</th>
                    <th className="px-2 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {stocks.map((r) => {
                    const cov = coverage?.[r.symbol];
                    const hasFo = cov?.available === true;
                    const checked = selected.includes(r.symbol);
                    return (
                      <tr key={r.symbol} className={cn("border-t", checked && "bg-primary/5")}>
                        <td className="px-2 py-1.5">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleSelect(r.symbol)}
                            aria-label={`Add ${r.symbol} to analysis`}
                            className="accent-primary"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="font-medium">{r.symbol}</div>
                          <div className="max-w-[220px] truncate text-[10px] text-muted-foreground">{r.name}</div>
                          {r.error && <div className="text-[9px] text-red-500/80">{r.error.slice(0, 60)}</div>}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                          {fmt(r.last, r.currency)}
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <Pct v={r.change_pct} />
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                          {fmt(r.low, r.currency, 1)} – {fmt(r.high, r.currency, 1)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                          {fmtCompact(r.day_volume)}
                        </td>
                        <td className="px-2 py-1.5">
                          {r.sparkline && r.sparkline.length > 1 ? (
                            <Sparkline data={r.sparkline} width={110} height={30} positive={null} />
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          {cov ? (
                            hasFo ? (
                              <Badge variant="secondary" className="text-[9px]" title={cov.provider || "chain"}>
                                ✓ {cov.strikes ?? "·"}×{(cov.expiries ?? []).length ?? "·"} exp
                              </Badge>
                            ) : (
                              <span className="text-[10px] text-muted-foreground" title={cov.note ?? "no chain"}>
                                —
                              </span>
                            )
                          ) : (
                            <span className="text-[10px] text-muted-foreground">{coverageLoading ? "…" : "·"}</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center justify-end gap-1">
                            <Link
                              href={`/prediction?symbol=${encodeURIComponent(r.symbol)}`}
                              className="rounded px-1.5 py-0.5 text-[10px] text-primary hover:bg-accent"
                            >
                              Predict
                            </Link>
                            {hasFo && (
                              <Link
                                href={`/options?symbol=${encodeURIComponent(r.symbol)}`}
                                className="rounded px-1.5 py-0.5 text-[10px] text-primary hover:bg-accent"
                              >
                                Options
                              </Link>
                            )}
                            <Link
                              href={`/stock/${encodeURIComponent(r.symbol)}`}
                              className="rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-accent"
                            >
                              Detail
                            </Link>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {!loading && !board && !error && <p className="py-6 text-center text-xs text-muted-foreground">No rows yet.</p>}

          {checkedCount > 0 && !askOpen && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 p-2 text-xs">
              <span className="font-medium">{checkedCount} symbol{checkedCount === 1 ? "" : "s"} selected for AI analysis</span>
              {selected.map((s) => (
                <Badge key={s} variant="secondary" className="font-mono text-[10px]">
                  {s}
                </Badge>
              ))}
              <div className="ml-auto flex gap-2">
                <Button size="sm" onClick={() => setAskOpen(true)}>
                  <Sparkles className="mr-1.5 h-3.5 w-3.5" /> Ask AI
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
                  Clear
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {(askOpen || selected.length > 0) && (
        <DeepAnalysisPanel availableSymbols={panelSymbols} symbols={selected} onSymbolsChange={setSelected} />
      )}
    </div>
  );
}

function IndexCard({
  row,
  coverage,
  selected,
  onToggle,
}: {
  row: IntradayRow;
  coverage?: CoverageInfo;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={cn("rounded-lg border p-3", selected && "border-primary/40 bg-primary/5")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">{row.symbol}</span>
            <Badge variant="outline" className="text-[9px]">
              INDEX
            </Badge>
            {coverage?.available === true && (
              <Badge variant="secondary" className="text-[9px]">
                F&O
              </Badge>
            )}
          </div>
          <div className="truncate text-[10px] text-muted-foreground">{row.name}</div>
        </div>
        <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${row.symbol}`} className="accent-primary" />
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <div>
          <div className="font-mono text-xl font-semibold tabular-nums">{fmt(row.last, row.currency)}</div>
          <Pct v={row.change_pct} />
        </div>
        {row.sparkline && row.sparkline.length > 1 && <Sparkline data={row.sparkline} width={130} height={40} />}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
        <span>O {fmt(row.day_open, row.currency, 1)}</span>
        <span>H {fmt(row.high, row.currency, 1)}</span>
        <span>L {fmt(row.low, row.currency, 1)}</span>
        <Link href={`/prediction?symbol=${encodeURIComponent(row.symbol)}`} className="ml-auto text-primary hover:underline">
          Predict →
        </Link>
      </div>
    </div>
  );
}