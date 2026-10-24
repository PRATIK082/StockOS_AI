"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import EquityChart from "@/components/stock/EquityChart";
import { fmt } from "@/lib/api";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Minus, Network, Sigma } from "lucide-react";

interface Verdict {
  rating?: string;
  conviction?: number;
  votes?: Record<string, number>;
}

function verdictBadge(v?: Verdict) {
  if (!v?.rating) return null;
  const tone =
    v.rating === "BUY" || v.rating === "bullish"
      ? "positive"
      : v.rating === "SELL" || v.rating === "bearish"
        ? "negative"
        : "secondary";
  return (
    <Badge variant={tone as "positive" | "negative" | "secondary"}>
      {v.rating}
      {typeof v.conviction === "number" && ` · ${fmt(v.conviction * 100, 0)}%`}
    </Badge>
  );
}

const STAT_ROWS: [string, string][] = [
  ["last_close", "Last close"],
  ["change_30d_pct", "30d change %"],
  ["rsi", "RSI"],
  ["sma20", "SMA 20"],
  ["sma50", "SMA 50"],
  ["sma_cross", "SMA cross"],
  ["vol_annualized", "Ann. vol %"],
  ["max_drawdown_30d", "Max DD 30d %"],
  ["trend_score", "Trend score"],
];

function StatsTable({ stats }: { stats: Record<string, Record<string, unknown>> }) {
  const symbols = Object.keys(stats);
  if (!symbols.length) return <p className="text-sm text-muted-foreground">No stats.</p>;
  return (
    <div className="overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            {STAT_ROWS.map(([k]) => (
              <TableHead key={k} className="text-right font-normal text-muted-foreground">
                {k}
              </TableHead>
            ))}
            <TableHead className="text-right">View</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {symbols.map((sym) => {
            const s = stats[sym] ?? {};
            const cross = String(s.sma_cross ?? "");
            return (
              <TableRow key={sym}>
                <TableCell className="font-mono text-xs">{sym}</TableCell>
                {STAT_ROWS.map(([k]) => (
                  <TableCell key={k} className="text-right text-xs">
                    {typeof s[k] === "number" ? fmt(s[k] as number, 2) : s[k] != null ? String(s[k]) : "—"}
                  </TableCell>
                ))}
                <TableCell className="text-right">
                  {cross === "bullish" ? (
                    <span className="inline-flex items-center gap-1 text-xs text-positive">
                      <ArrowUpRight className="h-3.5 w-3.5" /> bullish
                    </span>
                  ) : cross === "bearish" ? (
                    <span className="inline-flex items-center gap-1 text-xs text-negative">
                      <ArrowDownRight className="h-3.5 w-3.5" /> bearish
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <Minus className="h-3.5 w-3.5" /> {cross || "—"}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function TechnicalSummary({ out }: { out: Record<string, any> }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Verdict</span>
        {verdictBadge(out.verdict)}
        {out.failures?.length > 0 && (
          <span className="text-xs text-negative">failed: {out.failures.join(", ")}</span>
        )}
      </div>
      <StatsTable stats={out.stats ?? {}} />
    </div>
  );
}

function BacktestRun({ out }: { out: Record<string, any> }) {
  const result = out.result;
  const metrics = result?.metrics;
  const dates = result?.dates;
  const equity = result?.equity;
  const rows: [string, string][] = [];
  if (metrics) {
    const pct = (k: string) => (metrics[k] != null ? `${fmt(metrics[k] * 100, 2)}%` : "—");
    rows.push(
      ["Total return", pct("total_return")],
      ["Annualized", pct("annualized_return")],
      ["Sharpe", metrics.sharpe_ratio != null ? fmt(metrics.sharpe_ratio, 2) : "—"],
      ["Sortino", metrics.sortino_ratio != null ? fmt(metrics.sortino_ratio, 2) : "—"],
      ["Max drawdown", pct("max_drawdown")],
      ["Ann. vol", pct("annualized_vol")],
      ["Win rate", metrics.trades?.win_rate != null ? pct("trades.win_rate") : "—"],
      ["Trades", metrics.trades?.total_trades != null ? String(metrics.trades.total_trades) : "—"],
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">{out.symbol}</Badge>
        {result?.strategy && <Badge variant="outline">{result.strategy}</Badge>}
        {metrics?.final_equity != null && <Badge variant="outline">Final {fmt(metrics.final_equity, 0)}</Badge>}
      </div>
      {dates?.length && equity?.length ? (
        <EquityChart
          height={220}
          series={[{ label: `${out.symbol} equity`, data: dates.map((d: string, i: number) => ({ time: d, value: equity[i] })) }]}
        />
      ) : null}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-md border p-2">
            <div className="text-[11px] text-muted-foreground">{label}</div>
            <div className="text-sm font-semibold">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FactorIc({ out }: { out: Record<string, any> }) {
  const factors = out.ic?.factors ?? {};
  const names = Object.keys(factors);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Sigma className="h-3.5 w-3.5" /> Rank IC over {out.ic?.forward_days ?? 1}d forward
        {out.failures?.length > 0 && <span className="text-negative"> · failed: {out.failures.join(", ")}</span>}
      </div>
      {names.length ? (
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Factor</TableHead>
                <TableHead className="text-right">IC</TableHead>
                <TableHead className="text-right">ICIR</TableHead>
                <TableHead className="text-right">Days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {names.map((n) => {
                const e = factors[n] ?? {};
                return (
                  <TableRow key={n}>
                    <TableCell className="font-mono text-xs">{n}</TableCell>
                    <TableCell className={`text-right text-xs ${(e.ic_mean ?? 0) >= 0 ? "text-positive" : "text-negative"}`}>
                      {fmt(e.ic_mean ?? 0, 3)}
                    </TableCell>
                    <TableCell className="text-right text-xs">{fmt(e.ic_ir ?? 0, 2)}</TableCell>
                    <TableCell className="text-right text-xs">{e.n_days ?? 0}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No factor IC computed.</p>
      )}
    </div>
  );
}

function SwarmRun({ out }: { out: Record<string, any> }) {
  const nodes: Record<string, any> = out.nodes ?? {};
  const roles = Object.keys(nodes);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Network className="h-3.5 w-3.5" /> DAG {out.preset} · {roles.length} nodes
        {out.failures?.length > 0 && <span className="text-negative"> · failed: {out.failures.join(", ")}</span>}
      </div>
      {roles.map((role, i) => {
        const node = nodes[role] ?? {};
        const next = roles[i + 1];
        return (
          <div key={role}>
            <Card>
              <CardHeader className="pb-2 pt-3">
                <CardTitle className="flex flex-wrap items-center gap-2 text-xs font-medium text-muted-foreground">
                  <span className="font-mono uppercase">{role}</span>
                  {verdictBadge(node.verdict)}
                  {node.error && (
                    <span className="inline-flex items-center gap-1 text-negative">
                      <AlertTriangle className="h-3 w-3" /> {node.error}
                    </span>
                  )}
                  {Array.isArray(node.inputs) && node.inputs.length > 0 && (
                    <span className="text-[11px]">← {node.inputs.join(", ")}</span>
                  )}
                </CardTitle>
              </CardHeader>
              {node.quotes && (
                <CardContent className="pb-2 pt-0">
                  <div className="flex flex-wrap gap-2 text-xs">
                    {Object.entries(node.quotes).map(([sym, q]) => (
                      <Badge key={sym} variant="outline">
                        {sym} {fmt((q as any).last_close ?? 0, 2)}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              )}
              {node.top_symbols && (
                <CardContent className="pb-2 pt-0">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <span className="text-muted-foreground">Screen:</span>
                    {node.top_symbols.map((s: string) => (
                      <Badge key={s} variant="secondary">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              )}
              {node.gate && (
                <CardContent className="pb-2 pt-0 text-xs">
                  <span className="text-muted-foreground">Grounding:</span>{" "}
                  {node.gate.passed ? (
                    <span className="text-positive">passed</span>
                  ) : (
                    <span className="text-negative">unverified</span>
                  )}
                </CardContent>
              )}
              {node.stats && (
                <CardContent className="pb-3 pt-0">
                  <StatsTable stats={node.stats} />
                </CardContent>
              )}
            </Card>
            {next && <div className="py-1 text-center text-xs text-muted-foreground">↓</div>}
          </div>
        );
      })}
    </div>
  );
}

export default function ScheduledRunOutput({ output }: { output: unknown }) {
  const out = (output ?? {}) as Record<string, any>;
  if (typeof out !== "object" || out === null) {
    return <pre className="overflow-auto text-xs text-muted-foreground">{String(output)}</pre>;
  }
  if (out.error) {
    return (
      <p className="inline-flex items-center gap-2 text-sm text-negative">
        <AlertTriangle className="h-4 w-4" /> {out.error}
      </p>
    );
  }
  switch (out.type) {
    case "technical_summary":
      return <TechnicalSummary out={out} />;
    case "backtest":
      return <BacktestRun out={out} />;
    case "factor_ic":
      return <FactorIc out={out} />;
    case "swarm":
      return <SwarmRun out={out} />;
    default:
      return <pre className="max-h-64 overflow-auto rounded bg-background p-2 text-[11px] text-muted-foreground">{JSON.stringify(out, null, 2)}</pre>;
  }
}
