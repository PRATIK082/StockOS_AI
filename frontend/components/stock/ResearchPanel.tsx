"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import SymbolPicker from "@/components/stock/SymbolPicker";
import TechnicalChart from "@/components/stock/TechnicalChart";
import PredictionResultView, { type PredictionResult } from "@/components/stock/PredictionResultView";
import { api as http } from "@/lib/api-client";
import { Loader2, Play, LineChart } from "lucide-react";

export default function ResearchPanel({ initialSymbol = "NSE:RELIANCE" }: { initialSymbol?: string }) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PredictionResult | null>(null);

  const run = async () => {
    if (!symbol) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await http.post(`/api/analysis/predict/${encodeURIComponent(symbol)}`);
      setResult(res.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(detail ? String(detail) : "Could not generate research for this symbol.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Chart first — the Vibe-Trading "trading analysis" view, driven by the
          selected symbol. Reuses the same real-data path as the stock page. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LineChart className="h-4 w-4" /> Trading analysis — {symbol}
          </CardTitle>
          <CardDescription>
            Real candles with SMA/EMA/Bollinger overlays plus RSI, MACD, VWAP and ATR — no fabricated data.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TechnicalChart symbol={symbol} height={560} />
        </CardContent>
      </Card>

      {/* Symbol picker + research trigger */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Full research data</CardTitle>
          <CardDescription>
            Deterministic engine factors + real trading stats + options view + AI reasoning, all on the selected symbol.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-full max-w-md">
              <SymbolPicker
                single
                values={symbol ? [symbol] : []}
                onChange={(v) => setSymbol(v[0] ?? "")}
                placeholder="Pick a symbol…"
              />
            </div>
            <Button onClick={run} disabled={!symbol || loading}>
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              Run research
            </Button>
          </div>

          {error && (
            <p className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</p>
          )}

          {result && (
            <div className="mt-6">
              <PredictionResultView result={result} />
            </div>
          )}

          {!result && !error && (
            <p className="mt-4 text-xs text-muted-foreground">
              Press <span className="font-medium text-foreground">Run research</span> to compute the full research data for {symbol || "the picked symbol"}.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
