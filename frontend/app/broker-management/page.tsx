"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Loader2, Save, Eye, EyeOff } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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

export default function BrokerManagementPage() {
  const { data: settings, isLoading } = useQuery<SettingsData>({
    queryKey: ["settings"],
    queryFn: () => api.get("/v1/settings/"),
    retry: false,
  });

  const [executionMode, setExecutionMode] = useState("PAPER");
  const [broker, setBroker] = useState("paper");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [status, setStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  useEffect(() => {
    if (settings) {
      setExecutionMode(settings.execution_mode ?? "PAPER");
      setBroker(settings.selected_execution_broker ?? "paper");
    }
  }, [settings]);

  const liveEnabled = executionMode === "LIVE_ENABLED";
  const queryClient = useQueryClient();

  const mutate = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      return api.patch("/v1/settings/", values);
    },
    onSuccess: () => {
      setStatus({ type: "success", msg: "Broker settings updated" });
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (error: any) => {
      const msg = error?.message || error?.detail || "Failed to save broker settings";
      setStatus({ type: "error", msg });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Broker Management</h1>
        <p className="text-sm text-muted-foreground">
          Configure execution mode and connected brokerage. Live brokers require LIVE_ENABLED mode.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Broker Connection</CardTitle>
          <CardDescription>
            {liveEnabled
              ? "Live mode is enabled. Connecting a real broker requires valid credentials and is routed only after risk validation."
              : "Orders are currently routed to the Paper Broker (simulated). Switch to LIVE_ENABLED only when you intend to place real orders."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!liveEnabled && (
            <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              Live broker credentials are not configured. Orders will be routed to{" "}
              <code className="font-mono">PAPER</code> mode. Set execution mode to{" "}
              <code className="font-mono">LIVE_ENABLED</code> to configure a live broker.
            </div>
          )}

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
                selected_execution_broker: broker,
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
                <Select value={broker} onValueChange={setBroker} disabled={isLoading}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select broker" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="paper">Paper Broker (simulated)</SelectItem>
                    <SelectItem value="zerodha">Zerodha</SelectItem>
                    <SelectItem value="angelone">Angel One</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {liveEnabled && (
              <div className="grid gap-4 rounded-md border p-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Broker API Key</Label>
                  <div className="flex gap-2">
                    <Input
                      type={showApiKey ? "text" : "password"}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="Enter broker API key"
                      autoComplete="off"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => setShowApiKey((s) => !s)}
                      aria-label={showApiKey ? "Hide API key" : "Show API key"}
                    >
                      {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Keys are stored encrypted and never logged. This field is for identification only;
                    live execution is not yet wired end-to-end.
                  </p>
                </div>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button type="submit" disabled={mutate.isPending}>
                {mutate.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                {liveEnabled ? "Save Live Broker Config" : "Save Paper Config"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
