"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Search } from "lucide-react";
import AppShell from "@/components/layout/shell";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api, fmt, pctColor, type Quote } from "@/lib/api";

const UNIVERSE = [
  "NSE:RELIANCE",
  "NSE:TCS",
  "NSE:HDFCBANK",
  "NSE:INFY",
  "NSE:ICICIBANK",
  "NSE:SBIN",
  "NSE:TATAMOTORS",
  "BSE:TATASTEEL",
  "NYSE:AAPL",
  "NASDAQ:MSFT",
  "NASDAQ:GOOGL",
  "NASDAQ:AMZN",
  "NASDAQ:NVDA",
  "NYSE:TESLA",
  "NYSE:JPM",
];

export default function ScreenerPage() {
  const [query, setQuery] = useState("");
  const [minGain, setMinGain] = useState("");

  const quotes = useQuery({
    queryKey: ["screener", UNIVERSE.join(",")],
    queryFn: async () => {
      const results = await Promise.allSettled(
        UNIVERSE.map((s) => api.get<Quote>(`/market/quote/${encodeURIComponent(s)}`)),
      );
      return results
        .filter((r): r is PromiseFulfilledResult<Quote> => r.status === "fulfilled")
        .map((r) => r.value);
    },
    staleTime: 5 * 60_000,
  });

  const filtered = (quotes.data ?? []).filter((q) => {
    const matchText = !query || q.symbol.toLowerCase().includes(query.toLowerCase()) || (q.name ?? "").toLowerCase().includes(query.toLowerCase());
    const min = parseFloat(minGain);
    const matchGain = Number.isNaN(min) || (q.day_change_pct ?? -Infinity) >= min;
    return matchText && matchGain;
  });

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Screener</h1>
        <p className="text-sm text-muted-foreground">
          First pass universe screener — live quotes from free providers. Calculated scanners (breakout, 52-week high, fundamentals) arrive in later phases.
        </p>
      </div>

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value.toLowerCase())} placeholder="Filter by symbol or name" className="pl-8" />
        </div>
        <Input value={minGain} onChange={(e) => setMinGain(e.target.value)} placeholder="Min day gain % (e.g. 1)" className="sm:w-48" />
      </div>

      {quotes.isLoading && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((q) => (
          <Link key={q.symbol} href={`/stock/${encodeURIComponent(q.symbol)}`}>
            <Card className="h-full transition-colors hover:bg-muted/40">
              <CardContent className="flex items-center justify-between pt-5">
                <div>
                  <p className="text-sm font-medium">{q.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {q.symbol} · {q.provider}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-medium">
                    {fmt(q.price)} <span className="text-xs text-muted-foreground">{q.currency}</span>
                  </p>
                  <Badge variant={q.day_change_pct != null && q.day_change_pct >= 0 ? "positive" : "negative"}>
                    {q.day_change_pct != null ? `${q.day_change_pct >= 0 ? "+" : ""}${q.day_change_pct.toFixed(2)}%` : "—"}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {!quotes.isLoading && filtered.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">No symbols match your filters.</p>
      )}
    </AppShell>
  );
}