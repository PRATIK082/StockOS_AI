"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface SettingsData {
  execution_mode: string;
  selected_execution_broker: string;
  selected_market_data_source: string;
  max_order_risk_rupees?: number;
  max_daily_loss_rupees?: number;
  max_open_positions?: number;
  max_capital_deployed_percent?: number;
  max_fno_lots?: number;
}

export default function SettingsPage() {
  const { data: settings, isLoading } = useQuery<SettingsData>({
    queryKey: ["settings"],
    queryFn: () => api.get("/v1/settings/"),
    retry: false,
  });

  const [executionMode, setExecutionMode] = useState("PAPER");
  const [selectedBroker, setSelectedBroker] = useState("paper");
  const [selectedDataSource, setSelectedDataSource] = useState("yahoo");
  const [dailyLossLimit, setDailyLossLimit] = useState(5000);
  const [capitalDeployedPct, setCapitalDeployedPct] = useState(50);
  const [maxFnoLots, setMaxFnoLots] = useState(10);
  const [status, setStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  useEffect(() => {
    if (settings) {
      setExecutionMode(settings.execution_mode ?? "PAPER");
      setSelectedBroker(settings.selected_execution_broker ?? "paper");
      setSelectedDataSource(settings.selected_market_data_source ?? "yahoo");
      setDailyLossLimit(settings.max_daily_loss_rupees ?? 5000);
      setCapitalDeployedPct(settings.max_capital_deployed_percent ?? 50);
      setMaxFnoLots(settings.max_fno_lots ?? 10);
    }
  }, [settings]);

  const queryClient = useQueryClient();

  const mutate = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      return api.patch("/v1/settings/", values);
    },
    onSuccess: () => {
      setStatus({ type: "success", msg: "Settings updated" });
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (error: any) => {
      const msg = error?.message || error?.detail || "Failed to save settings";
      setStatus({ type: "error", msg });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground">Execution mode, broker, data source and risk limits.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Execution & Risk Configuration</CardTitle>
          <CardDescription>
            Orders are routed to the Paper Broker by default. Selecting a live broker
            (Zerodha/Angel One) only takes effect when execution mode is set to LIVE_ENABLED with valid credentials.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status && (
            <div
              className={`mb-4 rounded-md px-4 py-3 text-sm ${
                status.type === "success"
                  ? "bg-positive/10 text-positive"
                  : "bg-destructive/10 text-destructive"
              }`}
            >
              {status.msg}
            </div>
          )}

          <form
            className="grid gap-5"
            onSubmit={(e) => {
              e.preventDefault();
              mutate.mutate({
                execution_mode: executionMode,
                selected_execution_broker: selectedBroker,
                selected_market_data_source: selectedDataSource,
                max_daily_loss_rupees: dailyLossLimit,
                max_capital_deployed_percent: capitalDeployedPct,
                max_fno_lots: maxFnoLots,
              });
            }}
          >
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Execution Mode</Label>
                <Select value={executionMode} onValueChange={setExecutionMode} disabled={isLoading}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select execution mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="PAPER">PAPER (simulated)</SelectItem>
                    <SelectItem value="REQUIRE_APPROVAL">REQUIRE_APPROVAL (review before execution)</SelectItem>
                    <SelectItem value="LIVE_ENABLED">LIVE_ENABLED (real orders)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Selected Broker</Label>
                <Select value={selectedBroker} onValueChange={setSelectedBroker} disabled={isLoading}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select broker" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="paper">Paper Broker (simulated)</SelectItem>
                    <SelectItem value="zerodha">Zerodha (LIVE_ENABLED required)</SelectItem>
                    <SelectItem value="angelone">Angel One (LIVE_ENABLED required)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Market Data Source</Label>
                <Select value={selectedDataSource} onValueChange={setSelectedDataSource} disabled={isLoading}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select data source" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="yahoo">Yahoo Finance</SelectItem>
                    <SelectItem value="nse">NSE Public API</SelectItem>
                    <SelectItem value="tradingview">TradingView (NSE/BSE)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Max Daily Loss</Label>
                <Input
                  type="number"
                  value={dailyLossLimit}
                  onChange={(e) => setDailyLossLimit(Number(e.target.value))}
                  min={1}
                  disabled={isLoading}
                  placeholder="5000"
                />
              </div>

              <div className="space-y-2">
                <Label>Capital Deployed (%)</Label>
                <Input
                  type="number"
                  value={capitalDeployedPct}
                  onChange={(e) => setCapitalDeployedPct(Number(e.target.value))}
                  min={0}
                  max={100}
                  disabled={isLoading}
                  placeholder="50"
                />
              </div>

              <div className="space-y-2">
                <Label>Max F&amp;O Lots</Label>
                <Input
                  type="number"
                  value={maxFnoLots}
                  onChange={(e) => setMaxFnoLots(Number(e.target.value))}
                  min={1}
                  disabled={isLoading}
                  placeholder="10"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <Button type="submit" disabled={mutate.isPending}>
                {mutate.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                Save Settings
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
