"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Loader2, Save, Eye, EyeOff, RefreshCw, KeyRound, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, API_BASE, ApiError, getAuthToken } from "@/lib/api";

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

// --- Broker Diagnostics (GET /brokers/diagnostics; secrets are write-only) ---

interface BrokerLastAuth {
  ok: boolean | null;
  at: string | null;
  error?: string | null;
}

interface BrokerDiagnostics {
  name: string;
  display_name?: string;
  broker_type?: string | null;
  auth_required?: boolean;
  plugin_present?: boolean;
  present?: boolean;
  class_loadable?: boolean;
  credentials_stored?: boolean;
  totp_configured?: boolean;
  last_auth?: BrokerLastAuth | null;
  last_auth_ok?: boolean | null;
  last_auth_at?: string | null;
  last_auth_error?: string | null;
  supported_exchanges?: string[];
  exchanges?: string[];
  capabilities?: string[];
}

interface DiagnosticsResponse {
  brokers: BrokerDiagnostics[];
}

interface VerifyResponse {
  name: string;
  authenticated: boolean;
  message: string;
  last_auth_at: string;
}

function diagPresent(b: BrokerDiagnostics): boolean {
  return b.plugin_present ?? b.present ?? true;
}

function diagExchanges(b: BrokerDiagnostics): string[] {
  return b.supported_exchanges ?? b.exchanges ?? [];
}

function diagLastAuth(b: BrokerDiagnostics): { ok: boolean | null; at: string | null; error: string | null } {
  if (b.last_auth) {
    return { ok: b.last_auth.ok ?? null, at: b.last_auth.at ?? null, error: b.last_auth.error ?? null };
  }
  return { ok: b.last_auth_ok ?? null, at: b.last_auth_at ?? null, error: b.last_auth_error ?? null };
}

function formatTime(ts: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

function apiErrorStatus(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null;
}

function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/** PUT helper — "@/lib/api" only exports get/post/patch/del, so PUT goes through fetch directly. */
async function putJson<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method: "PUT", headers, body: JSON.stringify(body ?? {}) });
  } catch {
    throw new ApiError(`Cannot reach backend at ${API_BASE} - is it running?`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const parsed = (await res.json()) as { detail?: string };
      detail = parsed.detail || JSON.stringify(parsed);
    } catch {
      /* keep status text */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

function YesNo({ value }: { value: boolean }) {
  return (
    <Badge variant={value ? "positive" : "muted"}>{value ? "Y" : "N"}</Badge>
  );
}

function BrokerDiagnosticsCard({ broker }: { broker: BrokerDiagnostics }) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [totpSeed, setTotpSeed] = useState("");
  const [showSeed, setShowSeed] = useState(false);
  const [notice, setNotice] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["brokers", "diagnostics"] });

  const credsMutation = useMutation({
    mutationFn: (body: { api_key?: string; api_secret?: string }) =>
      api.post<{ name: string; credentials_stored: boolean }>(
        `/brokers/${encodeURIComponent(broker.name)}/credentials`,
        body,
      ),
    onSuccess: () => {
      // Write-only: clear inputs so values are never rendered back.
      setApiKey("");
      setApiSecret("");
      setNotice({ type: "success", msg: `Credentials stored for ${broker.name}.` });
      invalidate();
    },
    onError: (err: unknown) => setNotice({ type: "error", msg: apiErrorMessage(err, "Failed to save credentials") }),
  });

  const verifyMutation = useMutation({
    mutationFn: () =>
      api.post<VerifyResponse>(`/brokers/${encodeURIComponent(broker.name)}/auth/verify`),
    onSuccess: (data) => {
      setNotice({
        type: data.authenticated ? "success" : "error",
        msg: data.authenticated
          ? `Handshake OK for ${broker.name}${data.message ? ` — ${data.message}` : ""}`
          : `Handshake not authenticated for ${broker.name}${data.message ? ` — ${data.message}` : ""}`,
      });
      invalidate();
    },
    onError: (err: unknown) => {
      const status = apiErrorStatus(err);
      if (status === 409) {
        setNotice({ type: "error", msg: `No credentials stored for ${broker.name} — store credentials first, then verify.` });
      } else {
        setNotice({ type: "error", msg: apiErrorMessage(err, "Handshake verification failed") });
      }
      invalidate();
    },
  });

  const totpMutation = useMutation({
    mutationFn: (seed: string) =>
      putJson<{ name: string; totp_configured: boolean }>(
        `/brokers/${encodeURIComponent(broker.name)}/totp-seed`,
        { seed },
      ),
    onSuccess: () => {
      // Write-only: clear the seed input.
      setTotpSeed("");
      setNotice({ type: "success", msg: `TOTP seed saved for ${broker.name}.` });
      invalidate();
    },
    onError: (err: unknown) => {
      const status = apiErrorStatus(err);
      if (status === 422) {
        setNotice({ type: "error", msg: "Invalid seed — must be valid base32 (A–Z, 2–7, no spaces)." });
      } else if (status === 403) {
        setNotice({ type: "error", msg: "Saving a TOTP seed is admin-only." });
      } else {
        setNotice({ type: "error", msg: apiErrorMessage(err, "Failed to save TOTP seed") });
      }
    },
  });

  const lastAuth = diagLastAuth(broker);
  const exchanges = diagExchanges(broker);
  const busy = credsMutation.isPending || verifyMutation.isPending || totpMutation.isPending;

  return (
    <div className="rounded-md border p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="font-medium">{broker.display_name ?? broker.name}</span>
        <Badge variant="secondary">{broker.name}</Badge>
        {broker.auth_required ? <Badge variant="outline">auth required</Badge> : null}
        <YesNo value={diagPresent(broker)} />
        <span className="text-xs text-muted-foreground">present</span>
        <YesNo value={Boolean(broker.class_loadable)} />
        <span className="text-xs text-muted-foreground">class loadable</span>
      </div>

      <div className="mb-3 grid gap-2 text-sm md:grid-cols-2">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Credentials stored:</span>
          <YesNo value={Boolean(broker.credentials_stored)} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">TOTP configured:</span>
          <YesNo value={Boolean(broker.totp_configured)} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Last auth:</span>
          {lastAuth.at == null && lastAuth.ok == null ? (
            <span className="text-muted-foreground">never</span>
          ) : (
            <Badge variant={lastAuth.ok ? "positive" : "negative"}>
              {lastAuth.ok ? "OK" : "Failed"}
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">{formatTime(lastAuth.at)}</span>
        </div>
        <div className="text-xs text-muted-foreground">
          Exchanges: {exchanges.length > 0 ? exchanges.join(", ") : "—"}
          {broker.capabilities && broker.capabilities.length > 0
            ? ` · Capabilities: ${broker.capabilities.join(", ")}`
            : ""}
        </div>
      </div>
      {lastAuth.error ? (
        <p className="mb-3 text-xs text-destructive">Last error: {lastAuth.error}</p>
      ) : null}

      {notice && (
        <div
          className={`mb-3 rounded-md px-4 py-3 text-sm ${
            notice.type === "success" ? "bg-positive/10 text-positive" : "bg-destructive/10 text-destructive"
          }`}
        >
          {notice.msg}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <form
          className="space-y-2 rounded-md border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            const key = apiKey.trim();
            const secret = apiSecret.trim();
            if (!key && !secret) {
              setNotice({ type: "error", msg: "Enter an API key and/or API secret to store." });
              return;
            }
            const body: { api_key?: string; api_secret?: string } = {};
            if (key) body.api_key = key;
            if (secret) body.api_secret = secret;
            credsMutation.mutate(body);
          }}
        >
          <p className="flex items-center gap-1.5 text-sm font-medium">
            <KeyRound className="h-4 w-4" /> Credentials (write-only)
          </p>
          <div className="space-y-2">
            <Label htmlFor={`cred-key-${broker.name}`}>API key</Label>
            <Input
              id={`cred-key-${broker.name}`}
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter API key"
              autoComplete="off"
              disabled={busy}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`cred-secret-${broker.name}`}>API secret</Label>
            <div className="flex gap-2">
              <Input
                id={`cred-secret-${broker.name}`}
                type={showSecret ? "text" : "password"}
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                placeholder="Enter API secret"
                autoComplete="off"
                disabled={busy}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setShowSecret((s) => !s)}
                aria-label={showSecret ? "Hide API secret" : "Show API secret"}
              >
                {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Stored encrypted; values are never displayed back — only Y/N flags above.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              {credsMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              Save credentials
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => verifyMutation.mutate()}
            >
              {verifyMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Verify handshake
            </Button>
          </div>
        </form>

        <form
          className="space-y-2 rounded-md border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            const seed = totpSeed.trim();
            if (!seed) {
              setNotice({ type: "error", msg: "Enter a TOTP seed to store." });
              return;
            }
            totpMutation.mutate(seed);
          }}
        >
          <p className="flex items-center gap-1.5 text-sm font-medium">
            <ShieldCheck className="h-4 w-4" /> TOTP seed (admin, write-only)
          </p>
          <div className="space-y-2">
            <Label htmlFor={`totp-${broker.name}`}>TOTP seed (base32)</Label>
            <div className="flex gap-2">
              <Input
                id={`totp-${broker.name}`}
                type={showSeed ? "text" : "password"}
                value={totpSeed}
                onChange={(e) => setTotpSeed(e.target.value)}
                placeholder="JBSWY3DPEHPK3PXP"
                autoComplete="off"
                disabled={busy}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setShowSeed((s) => !s)}
                aria-label={showSeed ? "Hide TOTP seed" : "Show TOTP seed"}
              >
                {showSeed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Admin-only. Must be valid base32; the value is never displayed back.
          </p>
          <Button type="submit" size="sm" variant="outline" disabled={busy}>
            {totpMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Save TOTP seed
          </Button>
        </form>
      </div>
    </div>
  );
}

function BrokerDiagnosticsSection() {
  const diagnostics = useQuery<DiagnosticsResponse>({
    queryKey: ["brokers", "diagnostics"],
    queryFn: () => api.get("/brokers/diagnostics"),
    retry: false,
  });

  const brokers = diagnostics.data?.brokers ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Broker Diagnostics</CardTitle>
        <CardDescription>
          Plugin presence, credential Y/N flags, and last handshake outcome. Secrets are write-only and
          never displayed.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {diagnostics.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading broker diagnostics…
          </div>
        ) : diagnostics.isError ? (
          <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {apiErrorMessage(diagnostics.error, "Failed to load broker diagnostics")}
          </div>
        ) : brokers.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">No broker plugins found.</p>
        ) : (
          <div className="space-y-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Broker</TableHead>
                  <TableHead>Present</TableHead>
                  <TableHead>Class loadable</TableHead>
                  <TableHead>Creds</TableHead>
                  <TableHead>TOTP</TableHead>
                  <TableHead>Last auth</TableHead>
                  <TableHead>Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {brokers.map((b) => {
                  const lastAuth = diagLastAuth(b);
                  return (
                    <TableRow key={b.name}>
                      <TableCell className="font-medium">{b.display_name ?? b.name}</TableCell>
                      <TableCell>
                        <YesNo value={diagPresent(b)} />
                      </TableCell>
                      <TableCell>
                        <YesNo value={Boolean(b.class_loadable)} />
                      </TableCell>
                      <TableCell>
                        <YesNo value={Boolean(b.credentials_stored)} />
                      </TableCell>
                      <TableCell>
                        <YesNo value={Boolean(b.totp_configured)} />
                      </TableCell>
                      <TableCell>
                        {lastAuth.at == null && lastAuth.ok == null ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <Badge variant={lastAuth.ok ? "positive" : "negative"}>
                            {lastAuth.ok ? "OK" : "Failed"}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatTime(lastAuth.at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {brokers.some((b) => diagLastAuth(b).error) ? (
              <div className="space-y-1">
                {brokers
                  .filter((b) => diagLastAuth(b).error)
                  .map((b) => (
                    <p key={b.name} className="text-xs text-destructive">
                      {b.display_name ?? b.name}: {diagLastAuth(b).error}
                    </p>
                  ))}
              </div>
            ) : null}

            <div className="space-y-4">
              {brokers.map((b) => (
                <BrokerDiagnosticsCard key={b.name} broker={b} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
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

      <BrokerDiagnosticsSection />
    </div>
  );
}
