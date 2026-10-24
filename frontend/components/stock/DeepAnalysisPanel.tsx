"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, Play, Square, Sparkles, Trash2 } from "lucide-react";
import SymbolPicker from "@/components/stock/SymbolPicker";
import Markdown from "@/components/ui/Markdown";
import { useDeepAnalysis, stageMeasure } from "@/lib/deep";
import { cn } from "@/lib/utils";

const MEASURES = ["quote", "technical", "options", "prediction"] as const;
type Measure = (typeof MEASURES)[number];

const MEASURE_LABEL: Record<Measure, string> = {
  quote: "Quote",
  technical: "Technicals",
  options: "Options",
  prediction: "Prediction",
};

export interface DeepAnalysisSymbol {
  symbol: string;
  name?: string;
  index?: boolean;
}

const INITIAL_QUESTIONS = [
  "Compare momentum, strength and risk for these symbols and rank them.",
  "Which of these looks best positioned for an option trade right now?",
  "Summarise the technical setup and give a target range for each.",
  "Rank these by volume/IV action — where is the smart money moving?",
];

function desc(measure: Measure, data: any): string | null {
  if (!data) return null;
  if (measure === "quote") {
    if (data.price != null)
      return `${data.name ?? data.symbol ?? ""}: ${data.price?.toLocaleString(undefined, { maximumFractionDigits: 2 })}${
        data.change_pct != null ? ` (${data.change_pct > 0 ? "+" : ""}${data.change_pct.toFixed(2)}%)` : ""
      }`;
    return data.error ?? data.detail ?? "No quote data";
  }
  if (measure === "technical") {
    if (!data.series && data.error) return data.error;
    const bits: string[] = [];
    if (data.last_close != null) bits.push(`close ${data.last_close}`);
    if (data.rsi != null) bits.push(`RSI ${data.rsi.toFixed(1)}`);
    if (data.adx != null) bits.push(`ADX ${data.adx.toFixed(1)}`);
    if (data.supertrend?.trend) bits.push(`ST ${data.supertrend.trend}`);
    if (data.latest?.macd?.signal) bits.push(`MACD ${data.latest.macd.signal}`);
    return bits.length ? bits.join(" · ") : "Series computed";
  }
  if (measure === "options") {
    if (data.error) return data.error;
    if (!data.available) return "No F&O chain for this symbol";
    const bits: string[] = [];
    if (data.bias) bits.push(`bias ${data.bias}`);
    if (data.atm_iv != null) bits.push(`IV ${data.atm_iv}%`);
    if (data.value != null) bits.push(`premium ${data.value}`);
    if (data.expiry) bits.push(`exp ${data.expiry}`);
    return bits.length ? bits.join(" · ") : "Chain loaded";
  }
  if (measure === "prediction") {
    if (data.reason) return data.reason;
    if (data.error) return data.error;
    return null;
  }
  return null;
}

export default function DeepAnalysisPanel({
  availableSymbols = [],
  defaultOpen = true,
  symbols: controlledSymbols,
  onSymbolsChange,
}: {
  availableSymbols?: DeepAnalysisSymbol[];
  defaultOpen?: boolean;
  symbols?: string[];
  onSymbolsChange?: (values: string[]) => void;
}) {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [include, setInclude] = useState<Measure[]>(MEASURES as unknown as Measure[]);
  const { run, streaming, start, cancel, reset } = useDeepAnalysis();

  const effectiveSymbols = controlledSymbols ?? symbols;
  const updateSymbols = (v: string[]) => (onSymbolsChange ? onSymbolsChange(v) : setSymbols(v));

  useEffect(() => {
    if (availableSymbols.length && !effectiveSymbols.length) {
      updateSymbols(availableSymbols.slice(0, 2).map((s) => s.symbol));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableSymbols]);

  const toggleMeasure = (m: Measure) =>
    setInclude((inc) => (inc.includes(m) ? inc.filter((x) => x !== m) : [...inc, m]));

  const runAnalysis = () => {
    if (!effectiveSymbols.length || !question.trim()) return;
    void start(effectiveSymbols, question.trim(), { include });
  };

  const stageCount = Object.keys(run.stages).length;
  const doneCount = Object.values(run.stages).filter((s) => s.status === "done").length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" /> Ask AI — Deep Market Analysis
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Symbols (up to 5)</p>
            <SymbolPicker values={effectiveSymbols} onChange={updateSymbols}placeholder="Add symbols to compare…" />
            {availableSymbols.length > 0 && (
              <div className="flex flex-wrap items-center gap-1">
                <Button variant="ghost" size="sm" className="h-6 px-1.5 text-xs" onClick={() => updateSymbols(availableSymbols.slice(0, 3).map((s) => s.symbol))}>
                  Top movers
                </Button>
                <Button variant="ghost" size="sm" className="h-6 px-1.5 text-xs" onClick={() => updateSymbols(availableSymbols.filter((s) => s.index).slice(0, 3).map((s) => s.symbol))}>
                  Indices
                </Button>
                <Button variant="ghost" size="sm" className="h-6 px-1.5 text-xs" onClick={() => updateSymbols([])}>
                  Clear
                </Button>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-end gap-1.5">
            {MEASURES.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => toggleMeasure(m)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  include.includes(m)
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border text-muted-foreground hover:bg-accent",
                )}
              >
                {MEASURE_LABEL[m]}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <div className="relative">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runAnalysis();
              }}
              placeholder="Ask anything — e.g. 'Rank these by momentum and give a target range for each', 'Which is best for a CE trade right now?'"
              rows={2}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            <span className="absolute bottom-2 right-2 text-[10px] text-muted-foreground">{question.length}/2000</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {INITIAL_QUESTIONS.map((q) => (
              <button key={q} type="button" onClick={() => setQuestion(q)} className="rounded-full border border-dashed px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground">
                {q}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button onClick={runAnalysis} disabled={!effectiveSymbols.length || !question.trim() || streaming} size="sm">
            {streaming ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
            {streaming ? "Analyzing…" : "Run deep analysis"}
          </Button>
          {streaming && (
            <Button variant="outline" size="sm" onClick={cancel}>
              <Square className="mr-2 h-4 w-4" /> Stop
            </Button>
          )}
          {run.plan.length > 0 && !streaming && (
            <Button variant="ghost" size="sm" onClick={reset}>
              <Trash2 className="mr-2 h-4 w-4" /> Clear results
            </Button>
          )}
        </div>

        {run.plan.length === 0 && !run.error && (
          <p className="text-xs text-muted-foreground">
            The engine pulls real quotes, full technicals, options chains (when they exist) and predictions for each
            symbol, then asks the LLM to answer your question with the evidence — with a deterministic fallback when the
            model is unreachable.
          </p>
        )}

        {run.error && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{run.error}</p>
        )}

        {run.plan.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <div className="flex flex-wrap gap-1.5">
                {run.plan.map((p) => (
                  <Badge key={p.key} variant={stageCount > 0 ? "secondary" : "outline"}>
                    {p.label}
                  </Badge>
                ))}
              </div>
              {streaming && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> {doneCount}/{run.plan.length}
                </span>
              )}
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              {Object.entries(run.stages).map(([key, stage]) => (
                <div key={key} className={cn("rounded-lg border p-3", stage.status === "error" ? "border-destructive/40" : "border-border")}>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 font-mono text-xs font-medium">
                      {stage.symbol}
                      <span className="text-muted-foreground">{MEASURE_LABEL[stageMeasure(key) as Measure] ?? stageMeasure(key)}</span>
                    </span>
                    <Badge
                      variant={stage.status === "done" ? "default" : "muted"}
                      className={cn("text-[10px]", stage.status === "error" && "text-destructive", stage.status === "skipped" && "text-muted-foreground")}
                    >
                      {stage.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{desc(stageMeasure(key) as Measure, stage.data)}</p>
                  {stage.data?.symbol && (
                    <a className="mt-1 inline-block text-[11px] text-primary hover:underline" href={`/prediction?symbol=${encodeURIComponent(stage.data.symbol ?? stage.symbol)}`}>
                      Open prediction →
                    </a>
                  )}
                </div>
              ))}
            </div>

            {run.answer && (
              <div className="rounded-lg border p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">AI Answer</span>
                  {run.answer.confidence != null && <Badge variant="secondary">confidence {(run.answer.confidence * 100).toFixed(0)}%</Badge>}
                  {run.answer.symbol && <span className="font-mono">{run.answer.symbol}</span>}
                </div>
                <Markdown>{run.answer.answer}</Markdown>
                {run.answer.sources && run.answer.sources.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-1 border-t pt-2 text-[10px] text-muted-foreground">
                    <span className="font-medium">Evidence:</span>
                    {run.answer.sources.map((s, i) => (
                      <Badge key={i} variant="outline" className="font-mono text-[10px]">
                        {s}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}