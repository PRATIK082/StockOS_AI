"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import AppShell from "@/components/layout/shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, fmt, fmtCompact, pctColor, type Portfolio } from "@/lib/api";

export default function PortfolioPage() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [cost, setCost] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api.get<Portfolio>("/portfolio"),
  });

  const addMutation = useMutation({
    mutationFn: () => api.post("/portfolio", { symbol, quantity: qty, average_cost: cost }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      setSymbol("");
      setQty("");
      setCost("");
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Failed to add holding"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.del(`/portfolio/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio"] }),
  });

  const s = data?.summary;

  return (
    <AppShell>
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Portfolio</h1>
          <p className="text-sm text-muted-foreground">Live P&L using real market prices.</p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (symbol && qty && cost) addMutation.mutate();
          }}
          className="flex flex-wrap gap-2"
        >
          <Input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol e.g. NSE:TCS" className="w-40" required />
          <Input value={qty} onChange={(e) => setQty(e.target.value)} placeholder="Qty" className="w-20" required />
          <Input value={cost} onChange={(e) => setCost(e.target.value)} placeholder="Avg cost" className="w-24" required />
          <Button type="submit" disabled={addMutation.isPending}>
            <Plus className="mr-2 h-4 w-4" /> Add
          </Button>
        </form>
      </div>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      {isLoading && <Skeleton className="h-32 w-full" />}

      {data && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground">Invested</p>
              <p className="text-xl font-semibold">{fmt(s?.invested)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground">Current Value</p>
              <p className="text-xl font-semibold">{fmt(s?.value)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground">P&L</p>
              <p className={`text-xl font-semibold ${pctColor(s?.pnl)}`}>
                {s?.pnl != null && s.pnl >= 0 ? "+" : ""}
                {fmt(s?.pnl)}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground">Return %</p>
              <p className={`text-xl font-semibold ${pctColor(s?.pnl_pct)}`}>
                {s?.pnl_pct != null ? `${s.pnl_pct >= 0 ? "+" : ""}${s.pnl_pct.toFixed(2)}%` : "—"}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {data && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-base">Holdings</CardTitle>
          </CardHeader>
          <CardContent>
            {data.holdings.length === 0 && (
              <p className="py-8 text-center text-sm text-muted-foreground">No holdings yet. Add one above.</p>
            )}
            {data.holdings.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Avg Cost</TableHead>
                    <TableHead className="text-right">Current</TableHead>
                    <TableHead className="text-right">Invested</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                    <TableHead className="text-right">P&L</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.holdings.map((h) => (
                    <TableRow key={h.id}>
                      <TableCell className="font-medium">{h.symbol}</TableCell>
                      <TableCell className="text-right">{h.quantity}</TableCell>
                      <TableCell className="text-right">{fmt(Number(h.average_cost))}</TableCell>
                      <TableCell className="text-right">{fmt(h.current_price)}</TableCell>
                      <TableCell className="text-right">{fmtCompact(h.invested)}</TableCell>
                      <TableCell className="text-right">{fmtCompact(h.value)}</TableCell>
                      <TableCell className={`text-right ${pctColor(h.pnl)}`}>
                        {h.pnl >= 0 ? "+" : ""}
                        {fmt(h.pnl)}
                        <span className="ml-1 text-xs">
                          ({h.pnl_pct >= 0 ? "+" : ""}
                          {h.pnl_pct.toFixed(1)}%)
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => deleteMutation.mutate(h.id)}
                          aria-label={`Remove ${h.symbol}`}
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
      )}
    </AppShell>
  );
}