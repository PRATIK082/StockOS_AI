"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import SymbolPicker from "@/components/stock/SymbolPicker";
import VibeRunView from "@/components/stock/VibeRunView";
import { useVibeRun } from "@/lib/vibe";
import { ChevronDown, ChevronUp, Loader2, Play, Square, Sparkles } from "lucide-react";

/**
 * Agentic trading view — runs the streaming Vibe Trading pipeline (symbol →
 * quote → technical → options → prediction → LLM verdict) on a chosen symbol
 * and renders the live plan rail + widgets + verdict inline. Mounted across the
 * main pages so agentic research is available everywhere.
 */
export default function AgenticTradingPanel({
  symbol: initialSymbol = "",
  defaultOpen = false,
}: {
  symbol?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [symbol, setSymbol] = useState(initialSymbol);
  const { run, streaming, start, cancel } = useVibeRun();

  useEffect(() => {
    setSymbol(initialSymbol);
  }, [initialSymbol]);

  const runAnalysis = () => {
    if (!symbol.trim()) return;
    setOpen(true);
    void start(symbol.trim());
  };

  return (
    <Card className="mb-6">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" /> Agentic Trading
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-muted-foreground"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
          >
            {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            {open ? "Collapse" : "Expand"}
          </Button>
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-full max-w-md">
              <SymbolPicker
                single
                values={symbol ? [symbol] : []}
                onChange={(v) => setSymbol(v[0] ?? "")}
                placeholder="Pick a symbol…"
              />
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={runAnalysis} disabled={!symbol.trim() || streaming}>
                {streaming ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                {streaming ? "Running…" : "Run agentic analysis"}
              </Button>
              {streaming && (
                <Button variant="outline" size="icon" onClick={cancel} aria-label="Stop">
                  <Square className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          {!run.plan.length && !run.error && (
            <p className="text-xs text-muted-foreground">
              The pipeline streams real data — live quote, technicals, options view (when a chain exists) and a
              deterministic AI prediction — before the LLM verdict.
            </p>
          )}

          {run.error && (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {run.error}
            </p>
          )}

          {streaming && !run.answer && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> {run.active ? `Running: ${run.active}` : "Waiting for pipeline…"}
            </p>
          )}

          {(run.plan.length > 0 || run.answer) && <VibeRunView run={run} />}
        </CardContent>
      )}
    </Card>
  );
}
