"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import AppShell from "@/components/layout/shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, fmt, pctColor, type Quote, type SearchResult, type Watchlist } from "@/lib/api";
import SymbolSearch from "@/components/stock/SymbolSearch";

export default function WatchlistPage() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: lists, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => api.get<Watchlist[]>("/watchlist"),
  });

  const addMutation = useMutation({
    mutationFn: async (sym: string) => {
      let list = lists?.[0];
      if (!list) {
        const created = await api.post<Watchlist>("/watchlist", { name: "Default" });
        list = created;
      }
      await api.patch(`/watchlist/${list.id}/symbols`, { symbol: sym, action: "add" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      setSymbol(null);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Failed to add symbol"),
  });

  const removeMutation = useMutation({
    mutationFn: ({ id, sym }: { id: string; sym: string }) =>
      api.patch(`/watchlist/${id}/symbols`, { symbol: sym, action: "remove" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const list = lists?.[0];

  return (
    <AppShell>
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Watchlist</h1>
          <p className="text-sm text-muted-foreground">Search to add symbols from India & US markets.</p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (symbol) addMutation.mutate(symbol.symbol);
          }}
          className="flex w-full gap-2 md:max-w-md"
        >
          <SymbolSearch
            onSelect={(r) => setSymbol(r)}
            value={symbol}
            placeholder="Search & add a symbol…"
          />
          <Button type="submit" disabled={!symbol || addMutation.isPending}>
            <Plus className="mr-2 h-4 w-4" /> Add
          </Button>
        </form>
      </div>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{list?.name ?? "Watchlist"}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="space-y-3">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}
          {!isLoading && (!list || list.symbols.length === 0) && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Your watchlist is empty. Add symbols to start tracking.
            </p>
          )}
          {list && list.symbols.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol / Price</TableHead>
                  <TableHead className="text-right">Change</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.symbols.map((s) => (
                  <TableRow key={s}>
                    <TableCell>
                      <Link href={`/stock/${s}`} className="block hover:underline">
                        <div className="flex items-center justify-between gap-4">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">
                              <CountCell symbol={s} label="name" />
                            </p>
                            <p className="text-xs text-muted-foreground">{s}</p>
                          </div>
                          <div className="text-right">
                            <CountCell symbol={s} label="price" />
                          </div>
                        </div>
                      </Link>
                    </TableCell>
                    <TableCell className="text-right align-middle text-sm">
                      <CountCell symbol={s} label="change" />
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeMutation.mutate({ id: list.id, sym: s })}
                        aria-label={`Remove ${s}`}
                      >
                        <Trash2 className="h-4 w-4 text-muted-foreground" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </AppShell>
  );
}

function CountCell({ symbol, label }: { symbol: string; label: "name" | "price" | "change" }) {
  const { data } = useQuery({
    queryKey: ["quote", symbol],
    queryFn: () => api.get<Quote>(`/market/quote/${symbol}`),
  });
  if (!data) return <span className="text-muted-foreground">—</span>;
  if (label === "name") return <>{data.name ?? symbol}</>;
  if (label === "price")
    return (
      <>
        {fmt(data.price)} <span className="text-xs text-muted-foreground">{data.currency}</span>
      </>
    );
  return (
    <span className={pctColor(data.day_change_pct)}>
      {data.day_change_pct != null ? `${data.day_change_pct >= 0 ? "+" : ""}${data.day_change_pct.toFixed(2)}%` : "—"}
    </span>
  );
}