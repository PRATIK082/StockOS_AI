"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import Markdown from "@/components/ui/Markdown";
import { Activity, TrendingDown, TrendingUp, Star } from "lucide-react";
import AppShell from "@/components/layout/shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import MarketChart from "@/components/stock/MarketChart";
import TechnicalChart from "@/components/stock/TechnicalChart";
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel";
import LearningMemoryCard from "@/components/stock/LearningMemoryCard";
import {
  api,
  fmt,
  fmtCompact,
  getAuthToken,
  pctColor,
  type History,
  type Quote,
  type ResearchResult,
  type Watchlist,
} from "@/lib/api";
import { latestSignals, type SignalSnapshot } from "@/lib/indicators";

function SignalSummary({ s }: { s: SignalSnapshot }) {
  const rows: { label: string; value: string; tone?: "pos" | "neg" }[] = [
    { label: "Trend", value: s.trend, tone: s.trend === "bullish" ? "pos" : "neg" },
    {
      label: "RSI (14)",
      value: s.rsi_14 != null ? s.rsi_14.toFixed(1) : "—",
      tone: s.rsi_14 != null ? (s.rsi_14 > 70 ? "neg" : s.rsi_14 < 30 ? "pos" : undefined) : undefined,
    },
    { label: "EMA 9", value: s.ema_9 != null ? fmt(s.ema_9) : "—" },
    { label: "EMA 21", value: s.ema_21 != null ? fmt(s.ema_21) : "—" },
    { label: "EMA 50", value: s.ema_50 != null ? fmt(s.ema_50) : "—" },
    { label: "MACD", value: s.macd != null ? s.macd.toFixed(2) : "—" },
    { label: "MACD Signal", value: s.macd_signal != null ? s.macd_signal.toFixed(2) : "—" },
    { label: "Support", value: s.support != null ? fmt(s.support) : "—" },
    { label: "Resistance", value: s.resistance != null ? fmt(s.resistance) : "—" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {rows.map((r) => (
        <div key={r.label} className="rounded-md border p-2">
          <p className="text-xs text-muted-foreground">{r.label}</p>
          <p className={`text-sm font-medium ${r.tone === "pos" ? "text-positive" : r.tone === "neg" ? "text-negative" : ""}`}>
            {r.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function AddToWatchlist({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const { data: lists } = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => api.get<Watchlist[]>("/watchlist"),
    enabled: Boolean(getAuthToken()),
  });
  const has = lists?.[0]?.symbols?.includes(symbol) ?? false;

  const add = useMutation({
    mutationFn: async (sym: string) => {
      let list = lists?.[0];
      if (!list) {
        list = await api.post<Watchlist>("/watchlist", { name: "Default" });
      }
      await api.patch(`/watchlist/${list.id}/symbols`, { symbol: sym, action: "add" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  return (
    <Button variant="outline" size="sm" onClick={() => add.mutate(symbol)} disabled={add.isPending || has}>
      <Star className={`mr-1 h-4 w-4 ${has ? "fill-current text-primary" : ""}`} />
      {has ? "Added" : "Watchlist"}
    </Button>
  );
}

export default function StockPage() {
  const params = useParams();
  const symbol = decodeURIComponent((params.symbol as string) || "");

  const { data: quote } = useQuery({
    queryKey: ["quote", symbol],
    queryFn: () => api.get<Quote>(`/market/quote/${encodeURIComponent(symbol)}`),
    refetchInterval: 15_000,
  });

  const { data: history } = useQuery({
    queryKey: ["history", symbol],
    queryFn: () => api.get<History>(`/market/history/${encodeURIComponent(symbol)}?period=6mo&interval=1d`),
  });

  const { data: research, isLoading: researchLoading } = useQuery({
    queryKey: ["research", "stock", symbol],
    queryFn: () => api.post<ResearchResult>("/research", { symbol }),
  });

  const signals = history?.candles ? latestSignals(history.candles) : null;
  const change = quote?.day_change_pct;
  const Icon = change != null && change >= 0 ? TrendingUp : TrendingDown;

  return (
    <AppShell>
      <div className="mb-6 flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold">{quote?.name ?? symbol}</h1>
              <Badge variant="secondary">{symbol}</Badge>
              <Badge variant="outline">provider: {quote?.provider ?? "…"}</Badge>
            </div>
            <div className="mt-2 flex items-center gap-3">
              <span className="text-3xl font-semibold">
                {quote?.price != null ? `${quote.currency ?? ""} ${fmt(quote.price)}` : "—"}
              </span>
              <span className={`flex items-center text-lg ${pctColor(change)}`}>
                <Icon className="mr-1 h-5 w-5" />
                {change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "—"}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Prev close {fmt(quote?.previous_close)} · Open {fmt(quote?.open)} · Mkt cap {fmtCompact(quote?.market_cap)}
              {quote?.sector ? ` · ${quote.sector}` : ""}
            </p>
          </div>
          <AddToWatchlist symbol={symbol} />
        </div>

        <Card>
          <CardContent className="pt-5">
            <MarketChart symbol={symbol} />
          </CardContent>
        </Card>

        <AgenticTradingPanel symbol={symbol} defaultOpen />

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" /> Technical Indicators
            </CardTitle>
          </CardHeader>
          <CardContent>
            <TechnicalChart symbol={symbol} />
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Technical Snapshot</CardTitle>
          </CardHeader>
          <CardContent>
            {signals ? <SignalSummary s={signals} /> : <Skeleton className="h-40 w-full" />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4" /> AI Research
              {research && <Badge variant="secondary">confidence {Math.round(research.confidence * 100)}%</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {researchLoading && (
              <div className="space-y-2">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-11/12" />
                <Skeleton className="h-3 w-4/5" />
              </div>
            )}
            {research && (
              <article className="prose-invert prose-sm max-w-none text-sm">
                <Markdown>{research.answer}</Markdown>
              </article>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4">
        <LearningMemoryCard />
      </div>
    </AppShell>
  );
}