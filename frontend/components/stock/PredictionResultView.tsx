"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import Markdown from "@/components/ui/Markdown";
import { fmt } from "@/lib/api";
import { Activity, AlertCircle, BadgeDollarSign, Target, TrendingDown, TrendingUp } from "lucide-react";

export const ACTION_STYLES: Record<string, string> = {
  BUY: "bg-positive/15 text-positive border border-positive/30",
  SELL: "bg-negative/15 text-negative border border-negative/30",
  HOLD: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30",
};

export const BIAS_STYLES: Record<string, string> = {
  CALL: "bg-positive/15 text-positive border border-positive/30",
  PUT: "bg-negative/15 text-negative border border-negative/30",
  NEUTRAL: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30",
};

export function currencySymbol(symbol: string): string {
  const ex = (symbol || "").split(":")[0];
  return ["NSE", "BSE", "BOM", "NSEFO", "BSEFO"].includes(ex) ? "₹" : "$";
}

function returnColor(v: number): string {
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-muted-foreground";
}

export interface PredictionResult {
  symbol: string;
  timeframe: string;
  current_price: number;
  predicted_price: number;
  confidence: number;
  expected_return: number;
  bear_case: number;
  base_case: number;
  bull_case: number;
  reasoning: string;
  factors: Record<string, number>;
  action: string;
  horizon: string;
  trading_stats: Record<string, any>;
}

export default function PredictionResultView({ result }: { result: PredictionResult }) {
  return (
    <div className="space-y-6">
      {/* Price target + scenarios + confidence */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Target className="h-4 w-4" /> Price target
              {result.action && (
                <span className={`ml-auto inline-flex items-center rounded px-2 py-0.5 text-xs font-bold ${ACTION_STYLES[result.action] || ACTION_STYLES.HOLD}`}>
                  {result.action} · {result.horizon}
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Current</span>
                <span className="font-semibold">{currencySymbol(result.symbol)}{fmt(result.current_price)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Predicted</span>
                <span className={`font-semibold ${returnColor(result.expected_return)}`}>{currencySymbol(result.symbol)}{fmt(result.predicted_price)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Expected return</span>
                <span className={`font-semibold ${returnColor(result.expected_return)}`}>
                  {result.expected_return > 0 ? "+" : ""}{(result.expected_return * 100).toFixed(2)}%
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Scenarios ({result.timeframe})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <TrendingUp className="h-3.5 w-3.5 text-positive" /> Bull
              </span>
              <span className="font-semibold text-positive">{currencySymbol(result.symbol)}{fmt(result.bull_case)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Base</span>
              <span className="font-semibold">{currencySymbol(result.symbol)}{fmt(result.base_case)}</span>
            </div>
            <div className="flex justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <TrendingDown className="h-3.5 w-3.5 text-negative" /> Bear
              </span>
              <span className="font-semibold text-negative">{currencySymbol(result.symbol)}{fmt(result.bear_case)}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <AlertCircle className="h-4 w-4" /> Confidence
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-2 flex justify-between text-sm">
              <span className="text-muted-foreground">Model</span>
              <span className="font-semibold">{(result.confidence * 100).toFixed(1)}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-muted">
              <div
                className={`h-2 rounded-full ${result.confidence > 0.8 ? "bg-positive" : result.confidence > 0.6 ? "bg-yellow-500" : "bg-negative"}`}
                style={{ width: `${Math.min(result.confidence * 100, 100)}%` }}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Real trading data */}
      <TradingStatsGrid symbol={result.symbol} stats={result.trading_stats} />

      {/* Options market view */}
      {result.trading_stats?.options && <OptionsView symbol={result.symbol} options={result.trading_stats.options} />}

      {/* Factors */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Analysis factors</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(result.factors ?? {}).map(([key, value]) => (
              <div key={key} className="text-center">
                <p className="text-sm text-muted-foreground">{key.replace(/_/g, " ")}</p>
                <p className={`text-lg font-semibold ${value > 0.6 ? "text-positive" : value < 0.4 ? "text-negative" : "text-yellow-500"}`}>
                  {(value * 100).toFixed(1)}%
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* AI reasoning */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">AI analysis & reasoning</CardTitle>
        </CardHeader>
        <CardContent>
          <Markdown className="text-sm">{result.reasoning}</Markdown>
        </CardContent>
      </Card>
    </div>
  );
}

export function TradingStatsGrid({ symbol, stats }: { symbol: string; stats: Record<string, any> }) {
  if (!stats || Object.keys(stats).length === 0) return null;
  const cells: Array<{ label: string; value: string; tone?: string }> = [];
  if (stats.trading_days != null) cells.push({ label: "Trading days", value: String(stats.trading_days) });
  if (stats.up_days != null && stats.down_days != null) {
    cells.push({
      label: "Up / Down days",
      value: `${stats.up_days} / ${stats.down_days}`,
      tone: stats.up_days >= stats.down_days ? "text-positive" : "text-negative",
    });
  }
  if (stats.up_ratio != null)
    cells.push({
      label: "Up-day ratio",
      value: `${(stats.up_ratio * 100).toFixed(0)}%`,
      tone: stats.up_ratio > 0.55 ? "text-positive" : stats.up_ratio < 0.45 ? "text-negative" : undefined,
    });
  if (stats.avg_volume) cells.push({ label: "Avg volume", value: Number(stats.avg_volume).toLocaleString() });
  if (stats.volume_trend != null)
    cells.push({
      label: "Volume trend (5d)",
      value: `${(stats.volume_trend * 100).toFixed(0)}%`,
      tone: stats.volume_trend > 1.15 ? "text-positive" : stats.volume_trend < 0.85 ? "text-yellow-500" : undefined,
    });
  if (stats.atr) cells.push({ label: "ATR", value: Number(stats.atr).toFixed(2) });
  if (stats.range_52w_position != null)
    cells.push({
      label: "52W range position",
      value: `${(stats.range_52w_position * 100).toFixed(0)}%`,
      tone: stats.range_52w_position > 0.7 ? "text-positive" : stats.range_52w_position < 0.3 ? "text-negative" : undefined,
    });
  if (stats.low_52w != null && stats.high_52w != null)
    cells.push({
      label: "52W low / high",
      value: `${currencySymbol(symbol)}${Number(stats.low_52w).toFixed(0)} / ${currencySymbol(symbol)}${Number(stats.high_52w).toFixed(0)}`,
    });
  if (stats.volatility != null) cells.push({ label: "Volatility", value: `${(stats.volatility * 100).toFixed(1)}%` });
  if (stats.cap_class && stats.cap_class !== "n/a") cells.push({ label: "Cap class", value: stats.cap_class });
  if (stats.price_band) cells.push({ label: "Price band", value: stats.price_band });
  if (stats.sector) cells.push({ label: "Sector", value: String(stats.sector) });
  if (stats.industry) cells.push({ label: "Industry", value: String(stats.industry) });
  if (stats.last_expiry) cells.push({ label: "Nearest expiry", value: String(stats.last_expiry) });
  if (cells.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Activity className="h-4 w-4" /> Real trading data
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {cells.map((c) => (
            <div key={c.label} className="rounded-md bg-muted/40 p-3">
              <p className="text-xs text-muted-foreground">{c.label}</p>
              <p className={`text-sm font-semibold ${c.tone || "text-foreground"}`}>{c.value}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function OptionsView({ symbol, options }: { symbol: string; options: Record<string, any> }) {
  const rows: Array<{ label: string; value: string; tone?: string; badge?: boolean }> = [];
  if (options.bias) rows.push({ label: "Option bias", value: options.bias, badge: true });
  if (options.expiry) rows.push({ label: "Expiry", value: String(options.expiry) });
  if (options.spot_price != null)
    rows.push({ label: "Underlying spot", value: `${currencySymbol(symbol)}${Number(options.spot_price).toFixed(2)}` });
  if (options.max_pain != null)
    rows.push({ label: "Max pain", value: `${currencySymbol(symbol)}${Number(options.max_pain).toFixed(0)}` });
  if (options.atm_iv != null)
    rows.push({ label: "ATM IV", value: `${(Number(options.atm_iv) * 100).toFixed(1)}%` });
  if (options.iv_skew != null)
    rows.push({
      label: "IV skew (OTM P − OTM C)",
      value: `${options.iv_skew > 0 ? "+" : ""}${Number(options.iv_skew).toFixed(3)}`,
      tone: Number(options.iv_skew) > 0.02 ? "text-negative" : Number(options.iv_skew) < -0.02 ? "text-positive" : undefined,
    });
  if (options.premium_put_call != null)
    rows.push({
      label: "Premium P/C ratio",
      value: Number(options.premium_put_call).toFixed(2),
      tone: Number(options.premium_put_call) > 1.1 ? "text-negative" : Number(options.premium_put_call) < 0.9 ? "text-positive" : undefined,
    });
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <BadgeDollarSign className="h-4 w-4" /> Options market view
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {rows.map((r) => (
            <div key={r.label} className="rounded-md bg-muted/40 p-3">
              <p className="text-xs text-muted-foreground">{r.label}</p>
              {r.badge ? (
                <span className={`mt-1 inline-flex items-center rounded px-2 py-0.5 text-xs font-bold ${BIAS_STYLES[r.value] || BIAS_STYLES.NEUTRAL}`}>
                  {r.value}
                </span>
              ) : (
                <p className={`text-sm font-semibold ${r.tone || "text-foreground"}`}>{r.value}</p>
              )}
            </div>
          ))}
        </div>
        {options.recommendation && (
          <p className="mt-3 rounded-md border border-border bg-muted/40 p-3 text-sm text-muted-foreground">{options.recommendation}</p>
        )}
      </CardContent>
    </Card>
  );
}
