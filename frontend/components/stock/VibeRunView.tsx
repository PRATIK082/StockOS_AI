"use client";

import Markdown from "@/components/ui/Markdown";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import TechnicalChart from "@/components/stock/TechnicalChart";
import PredictionResultView, { OptionsView, type PredictionResult } from "@/components/stock/PredictionResultView";
import { fmt, fmtCompact } from "@/lib/api";
import type { VibeRunState } from "@/lib/vibe";
import { CheckCircle2, CircleDashed, CircleX, Loader2, XCircle } from "lucide-react";

/**
 * Renders a streaming Vibe Trading run: the plan rail, live stage widgets
 * (quote card, technical chips + chart, options view, prediction result) and
 * the final markdown verdict. Shared by the /chat page and AgenticTradingPanel.
 */
export default function VibeRunView({ run }: { run: VibeRunState }) {
  const symbol = run.answer?.symbol || run.stages.quote?.data?.quote?.symbol || run.stages.prediction?.data?.symbol;

  return (
    <div className="space-y-4">
      {run.plan.length > 0 && <PlanRail run={run} />}

      {run.stages.quote && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Live quote</CardTitle>
          </CardHeader>
          <CardContent>
            <QuoteView quote={run.stages.quote.data.quote || {}} symbol={symbol || ""} />
          </CardContent>
        </Card>
      )}

      {run.stages.technical && run.stages.technical.status !== "error" && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Technical indicators</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <TechnicalView data={run.stages.technical.data} />
            {symbol && <TechnicalChart symbol={symbol} height={280} />}
          </CardContent>
        </Card>
      )}

      {run.stages.options && run.stages.options.status !== "skipped" && (
        <OptionsView symbol={symbol || ""} options={run.stages.options.data} />
      )}

      {run.stages.prediction && run.stages.prediction.status !== "error" && symbol && (
        <PredictionResultView result={run.stages.prediction.data as PredictionResult} />
      )}

      {run.answer && (
        <div>
          <article className="prose-invert prose-sm max-w-none">
            <Markdown>{run.answer.answer}</Markdown>
          </article>
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-2">
            <Badge variant="secondary">confidence {Math.round(run.answer.confidence * 100)}%</Badge>
            {run.answer.symbol && <span className="text-xs text-muted-foreground">symbol: {run.answer.symbol}</span>}
            {run.answer.sources?.map((s) => (
              <Badge key={s} variant="outline">
                {s}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PlanRail({ run }: { run: VibeRunState }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {run.plan.map((p) => {
        const st = run.stages[p.key];
        let cls = "border-border text-muted-foreground";
        let Icon = CircleDashed;
        if (p.key === "answer" && run.answer) {
          cls = "border-positive/40 bg-positive/10 text-positive";
          Icon = CheckCircle2;
        } else if (st?.status === "done") {
          cls = "border-positive/40 bg-positive/10 text-positive";
          Icon = CheckCircle2;
        } else if (st?.status === "skipped") {
          cls = "border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400";
          Icon = XCircle;
        } else if (st?.status === "error") {
          cls = "border-destructive/40 bg-destructive/10 text-destructive";
          Icon = CircleX;
        } else if (run.active === p.key) {
          cls = "border-primary/50 bg-primary/10 text-primary";
          Icon = Loader2;
        }
        return (
          <span
            key={p.key}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}
          >
            {Icon && <Icon className={`h-3.5 w-3.5 ${Icon === Loader2 ? "animate-spin" : ""}`} />}
            {p.label}
          </span>
        );
      })}
    </div>
  );
}

export function QuoteView({ quote, symbol }: { quote: Record<string, any>; symbol: string }) {
  if (!quote || quote.price == null) {
    return <p className="text-sm text-muted-foreground">Quote unavailable for {symbol || "this symbol"}.</p>;
  }
  const chg = quote.day_change_pct;
  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
      <div>
        <p className="text-xs text-muted-foreground">{quote.name || symbol}</p>
        <p className="text-xl font-semibold">
          {quote.price != null ? fmt(quote.price) : "—"}
          <span className="ml-1 text-sm text-muted-foreground">{quote.currency}</span>
        </p>
      </div>
      {chg != null && (
        <span className={`inline-flex items-center rounded px-2 py-0.5 text-sm font-semibold ${chg >= 0 ? "text-positive" : "text-negative"}`}>
          {chg >= 0 ? "+" : ""}{chg.toFixed(2)}%
        </span>
      )}
      <div className="flex flex-wrap gap-2">
        {quote.provider && <Badge variant="outline">{quote.provider}</Badge>}
        {quote.market_cap != null && <Badge variant="outline">MCap {fmtCompact(quote.market_cap)}</Badge>}
        {quote.sector && <Badge variant="outline">{quote.sector}</Badge>}
      </div>
    </div>
  );
}

export function TechnicalView({ data }: { data: Record<string, any> }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="text-sm text-muted-foreground">No technical readings.</p>;
  }
  const cells: Array<{ label: string; value: string; tone?: string }> = [];
  if (data.last_close != null) cells.push({ label: "Last close", value: fmt(data.last_close) });
  if (data.rsi != null) {
    cells.push({
      label: "RSI(14)",
      value: Number(data.rsi).toFixed(1),
      tone: data.rsi > 70 ? "text-negative" : data.rsi < 30 ? "text-positive" : undefined,
    });
  }
  if (data.macd != null && data.macd_hist != null) {
    cells.push({
      label: "MACD hist",
      value: Number(data.macd_hist).toFixed(3),
      tone: data.macd_hist >= 0 ? "text-positive" : "text-negative",
    });
  }
  if (data.atr != null) cells.push({ label: "ATR", value: Number(data.atr).toFixed(2) });
  if (data.vwap != null) cells.push({ label: "VWAP", value: fmt(data.vwap) });
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {cells.map((c) => (
        <div key={c.label} className="rounded-md bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">{c.label}</p>
          <p className={`text-sm font-semibold ${c.tone || "text-foreground"}`}>{c.value}</p>
        </div>
      ))}
    </div>
  );
}
