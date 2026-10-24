"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import OptionPremiumChart from "@/components/stock/OptionPremiumChart";
import { api, getAuthToken, fmt, type OptionPosition } from "@/lib/api";
import { LineChart, Activity, Trash2, TrendingUp, AlertTriangle } from "lucide-react";

/**
 * Tracked F&O widget — a per-user list of paper CE/PE positions. Each row can
 * toggle its **option premium chart** on/off and switch between a line and an
 * area view (the premium, not the underlying). Used on the dashboard, Options,
 * Backtest, Factor Lab and Scheduled pages so F&O positions are visible from
 * everywhere.
 */
export default function OptionPositionsWidget({
  title = "Tracked F&O positions",
}: {
  title?: string;
}) {
  const [authenticated] = useState(() => Boolean(getAuthToken()));
  const [showChart, setShowChart] = useState<Record<string, boolean>>({});
  const [variant, setVariant] = useState<Record<string, "area" | "line">>({});
  const qc = useQueryClient();

  const { data: positions } = useQuery({
    queryKey: ["option-positions"],
    queryFn: () => api.get<OptionPosition[]>("/options/positions"),
    retry: false,
    enabled: authenticated,
  });

  const removePosition = useMutation({
    mutationFn: (id: string) => api.del(`/options/positions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["option-positions"] }),
  });

  if (!authenticated) return null;

  return (
    <Card className="mb-6">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-2">
            <Activity className="h-4 w-4" /> {title}
          </span>
          <Link
            href="/options"
            className="rounded-md px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
          >
            Open F&O page
          </Link>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {!positions || positions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No tracked positions.{" "}
            <Link href="/options" className="underline">
              Track a CE/PE contract
            </Link>{" "}
            to see its premium chart here.
          </p>
        ) : (
          positions.map((p) => {
            const open = Boolean(showChart[p.id]);
            const v = variant[p.id] ?? "area";
            return (
              <div key={p.id} className="rounded-md border p-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span
                      className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${
                        p.option_type === "CALL"
                          ? "bg-positive/15 text-positive"
                          : "bg-negative/15 text-negative"
                      }`}
                    >
                      {p.option_type === "CALL" ? "CE" : "PE"}
                    </span>
                    <span className="font-medium">{p.symbol}</span>
                    <span className="text-muted-foreground">
                      {fmt(p.strike, 0)} · {p.expiry?.slice(0, 10)} · Qty {fmt(p.quantity, 0)} ·
                      Prem ₹{fmt(p.premium)}
                    </span>
                  </span>
                  <span className="flex items-center gap-1">
                    <Button
                      asChild
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 text-muted-foreground"
                    >
                      <Link
                        href={`/prediction?symbol=${encodeURIComponent(p.symbol)}&option_type=${
                          p.option_type === "CALL" ? "CE" : "PE"
                        }&strike=${p.strike}&expiry=${encodeURIComponent(p.expiry?.slice(0, 10) ?? "")}`}
                      >
                        <TrendingUp className="h-4 w-4" /> Predict
                      </Link>
                    </Button>
                    <Button
                      variant={open ? "secondary" : "ghost"}
                      size="sm"
                      className="h-7 gap-1 text-muted-foreground"
                      onClick={() =>
                        setShowChart((prev) => ({ ...prev, [p.id]: !open }))
                      }
                      aria-pressed={open}
                      title={open ? "Hide premium chart" : "Show premium chart"}
                    >
                      <LineChart className="h-4 w-4" /> {open ? "Hide chart" : "Chart"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => removePosition.mutate(p.id)}
                      aria-label={`Delete ${p.option_type} ${p.strike} position`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </span>
                </div>

                {open && (
                  <div className="mt-2">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-xs font-medium text-muted-foreground">
                        Option premium — {p.symbol} {p.option_type === "CALL" ? "CE" : "PE"}{" "}
                        {fmt(p.strike, 0)}
                      </span>
                      <div className="flex items-center gap-0.5 rounded-md border p-0.5">
                        {(["area", "line"] as const).map((t) => (
                          <button
                            key={t}
                            onClick={() => setVariant((prev) => ({ ...prev, [p.id]: t }))}
                            className={`h-6 rounded px-2 text-xs font-medium capitalize transition-colors ${
                              v === t
                                ? "bg-foreground/10 text-foreground"
                                : "text-muted-foreground hover:bg-muted/40"
                            }`}
                          >
                            {t}
                          </button>
                        ))}
                      </div>
                    </div>
                    <OptionPremiumChart
                      symbol={p.symbol}
                      strike={p.strike}
                      expiry={p.expiry?.slice(0, 10)}
                      optionType={p.option_type === "CALL" ? "CE" : "PE"}
                      variant={v}
                    />
                    {p.symbol && (
                      <p className="mt-1 flex items-start gap-1 text-[11px] text-muted-foreground">
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                        Theoretical premium (Black-Scholes on real underlying history) — the free
                        scanner publishes no historical option prices.
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
