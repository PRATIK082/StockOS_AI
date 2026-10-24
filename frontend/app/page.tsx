"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { TrendingUp, TrendingDown, Activity, Plus, X } from "lucide-react";
import Markdown from "@/components/ui/Markdown";
import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/layout/shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import SymbolSearch from "@/components/stock/SymbolSearch";
import OptionPositionsWidget from "@/components/stock/OptionPositionsWidget";
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel";
import LearningMemoryCard from "@/components/stock/LearningMemoryCard";
import {
  api,
  fmt,
  fmtCompact,
  getAuthToken,
  pctColor,
  type OptionPosition,
  type Quote,
  type ResearchResult,
  type SearchResult,
  type Watchlist,
} from "@/lib/api";

const TABS = [
  { id: "india", label: "India" },
  { id: "us", label: "US" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const DEFAULTS: Record<TabId, string[]> = {
  india: ["NSE:NIFTY", "NSE:BANKNIFTY", "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY", "NSE:SBIN", "BSE:TATASTEEL"],
  us: ["NYSE:DJI", "NYSE:SPX", "NASDAQ:IXIC", "NYSE:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NYSE:JPM"],
};

function QuoteCard({ symbol, removable, onRemove }: { symbol: string; removable: boolean; onRemove: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["quote", symbol],
    queryFn: () => api.get<Quote>(`/market/quote/${encodeURIComponent(symbol)}`),
    refetchInterval: 15_000,
  });

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (isError || !data)
    return (
      <Card>
        <CardContent className="flex h-24 items-center justify-between text-sm text-muted-foreground">
          <span>Could not load {symbol}</span>
          {removable && (
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onRemove} aria-label={`Remove ${symbol}`}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </CardContent>
      </Card>
    );

  const change = data.day_change_pct;
  const Icon = change != null && change >= 0 ? TrendingUp : TrendingDown;
  return (
    <Card className="relative transition-colors hover:bg-muted/40">
      {removable && (
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-1 top-1 z-10 h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
          aria-label={`Remove ${symbol}`}
        >
          <X className="h-4 w-4" />
        </Button>
      )}
      <CardContent className="pt-5">
        <div className="flex items-start justify-between">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{data.name}</p>
            <p className="text-xs text-muted-foreground">
              {data.symbol} · {data.provider}
            </p>
          </div>
          <Badge variant={change != null && change >= 0 ? "positive" : "negative"}>
            <Icon className="mr-1 h-3 w-3" />
            {change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "—"}
          </Badge>
        </div>
        <p className="mt-3 text-2xl font-semibold">
          {data.price == null ? "—" : `${data.currency ?? ""} ${fmt(data.price)}`}
        </p>
        <p className={cn("mt-1 text-xs", pctColor(change))}>
          Prev {fmt(data.previous_close)} · Mkt cap {fmtCompact(data.market_cap)}
        </p>
      </CardContent>
    </Card>
  );
}

function ResearchPanel({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["research", symbol],
    queryFn: () => api.post<ResearchResult>("/research", { symbol }),
    enabled: Boolean(symbol),
    retry: false,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4" /> AI Research
          {data && <Badge variant="secondary">confidence {Math.round(data.confidence * 100)}%</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-11/12" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        )}
        {isError && <p className="text-sm text-muted-foreground">Research is unavailable right now (LLM provider not responding).</p>}
        {data && (
          <article className="prose-invert prose-sm max-w-none text-sm">
            <Markdown>{data.answer}</Markdown>
          </article>
        )}
      </CardContent>
    </Card>
  );
}

function SignInHint() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
        <span className="text-muted-foreground">
          Sign in to save stocks to your board and track PUT/CALL option positions.
        </span>
        <Button asChild size="sm">
          <Link href="/login">Sign in</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export default function Home() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabId>("india");
  const [custom, setCustom] = useState<SearchResult | null>(null);
  const [researchSymbol, setResearchSymbol] = useState<string | null>(null);
  const [guestError, setGuestError] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    setAuthenticated(Boolean(getAuthToken()));
  }, []);

  const { data: watchlists } = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => api.get<Watchlist[]>("/watchlist"),
    retry: false,
    enabled: authenticated,
  });
  const watchlistSymbols = watchlists?.[0]?.symbols ?? [];

  const { data: positions } = useQuery({
    queryKey: ["option-positions"],
    queryFn: () => api.get<OptionPosition[]>("/options/positions"),
    retry: false,
    refetchInterval: 30_000,
    enabled: authenticated,
  });

  const symbols = useMemo(() => {
    const isUs = (s: string) => ["NYSE", "NASDAQ", "AMEX"].includes(s.split(":")[0]);
    const set = new Set<string>(DEFAULTS[tab]);
    for (const s of watchlistSymbols) {
      if ((tab === "india" && !isUs(s)) || (tab === "us" && isUs(s))) set.add(s);
    }
    if (custom && custom.market === (tab === "india" ? "india" : "us")) set.add(custom.symbol);
    return [...set].slice(0, 9);
  }, [tab, watchlistSymbols, custom]);

  const addToWatchlist = useMutation({
    mutationFn: async (sym: string) => {
      let list = watchlists?.[0];
      if (!list) list = await api.post<Watchlist>("/watchlist", { name: "Default" });
      await api.patch(`/watchlist/${list.id}/symbols`, { symbol: sym, action: "add" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      if (custom) {
        setResearchSymbol(custom.symbol);
        setCustom(null);
      }
    },
    onError: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const removeFromWatchlist = useMutation({
    mutationFn: async (sym: string) => {
      const list = watchlists?.[0];
      if (!list) return;
      await api.patch(`/watchlist/${list.id}/symbols`, { symbol: sym, action: "remove" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!custom) return;
    if (!authenticated) {
      setGuestError(true);
      return;
    }
    setGuestError(false);
    addToWatchlist.mutate(custom.symbol);
  };

  return (
    <AppShell>
      <div className="mb-6 flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">AI Agentic Trading Command Center</h1>
            <p className="text-sm text-muted-foreground">
              {tab === "india" ? "NSE / BSE — Indian market" : "NYSE / NASDAQ — US market"} · live quotes + AI research
            </p>
          </div>
          <div className="flex items-center gap-1 rounded-md border p-0.5">
            {TABS.map((t) => (
              <Button key={t.id} variant="ghost" size="sm" className={cn("h-7", tab === t.id && "bg-accent")} onClick={() => setTab(t.id)}>
                {t.label}
              </Button>
            ))}
          </div>
        </div>

        <form onSubmit={handleAdd} className="flex items-center gap-2">
          <SymbolSearch market={tab === "india" ? "india" : "us"} onSelect={(r) => setCustom(r)} placeholder={`Add a ${tab === "india" ? "NSE/BSE" : "US"} stock to your board…`} />
          <Button type="submit" disabled={!custom || addToWatchlist.isPending}>
            <Plus className="mr-2 h-4 w-4" /> Add
          </Button>
        </form>

        {!authenticated && <SignInHint />}
        {guestError && (
          <p className="text-sm text-destructive">
            Sign in to save stocks to your board. <Link href="/login" className="underline">Go to login →</Link>
          </p>
        )}
        {addToWatchlist.isError && (
          <p className="text-sm text-destructive">Failed to add {custom?.symbol ?? "symbol"}. Please sign in.</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {symbols.map((s) => (
          <QuoteCard
            key={s}
            symbol={s}
            removable={authenticated && watchlistSymbols.includes(s)}
            onRemove={() => removeFromWatchlist.mutate(s)}
          />
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AgenticTradingPanel defaultOpen />
        <LearningMemoryCard />
      </div>

      {positions && positions.length > 0 && (
        <div className="mt-8">
          <OptionPositionsWidget title="Your Option Positions" />
        </div>
      )}

      {researchSymbol && (
        <div className="mt-6">
          <ResearchPanel symbol={researchSymbol} />
        </div>
      )}
    </AppShell>
  );
}
