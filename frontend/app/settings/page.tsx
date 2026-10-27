"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Check, Copy, KeyRound, Loader2, LogOut, Save, ShieldCheck, ShieldOff } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useEffect, useState } from "react";
import { api, getAuthToken, setAuthToken } from "@/lib/api";
import { cn } from "@/lib/utils";

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

interface MeResponse {
  id: string;
  email: string;
  username: string;
  role: string;
  totp_enabled: boolean;
}

interface TOTPSetupResponse {
  secret: string;
  provisioning_uri: string;
  enabled: boolean;
}

interface LogoutResponse {
  detail: string;
  revoked: boolean;
}

type Feedback = { type: "success" | "error"; msg: string } | null;

const onlyDigits = (value: string) => value.replace(/\D/g, "");

// The shared API helper clears the stored token on any 401. A mistyped TOTP code
// answers 401 too, so the token is captured and restored to keep the session alive.
async function postTotp<T>(path: string, body: { code: string }): Promise<T> {
  const token = getAuthToken();
  try {
    return await api.post<T>(path, body);
  } catch (error: any) {
    if (error?.status === 401 && token) setAuthToken(token);
    throw error;
  }
}

export default function SettingsPage() {
  const router = useRouter();
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

  // --- Two-factor authentication state ---
  const [twoFaStatus, setTwoFaStatus] = useState<Feedback>(null);
  const [totpSetup, setTotpSetup] = useState<TOTPSetupResponse | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [copied, setCopied] = useState(false);
  const [sessionStatus, setSessionStatus] = useState<Feedback>(null);

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

  const meQuery = useQuery<MeResponse>({
    queryKey: ["auth", "me"],
    queryFn: () => api.get("/auth/me"),
    retry: false,
  });

  const totpEnabled = Boolean(meQuery.data?.totp_enabled);

  const setupMutation = useMutation({
    mutationFn: () => api.post<TOTPSetupResponse>("/auth/totp/setup"),
    onSuccess: (res) => {
      setTotpSetup(res);
      setTwoFaStatus({
        type: "success",
        msg: "Secret generated. Add it to your authenticator app, then enter the code to enable 2FA.",
      });
    },
    onError: (error: any) => {
      const msg = error?.message || error?.detail || "Failed to generate a 2FA secret";
      setTwoFaStatus({ type: "error", msg });
    },
  });

  const verifyMutation = useMutation({
    mutationFn: (code: string) => postTotp<{ enabled: boolean }>("/auth/totp/verify", { code }),
    onSuccess: () => {
      setTotpCode("");
      setTwoFaStatus({ type: "success", msg: "2FA enabled. A code will be required at sign-in." });
      queryClient.setQueryData<MeResponse>(["auth", "me"], (prev) =>
        prev ? { ...prev, totp_enabled: true } : prev,
      );
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
    onError: (error: any) => {
      const msg = error?.message || error?.detail || "Invalid 2FA code";
      setTwoFaStatus({ type: "error", msg });
    },
  });

  const disableMutation = useMutation({
    mutationFn: (code: string) => postTotp<{ enabled: boolean }>("/auth/totp/disable", { code }),
    onSuccess: () => {
      setTotpCode("");
      setTotpSetup(null);
      setTwoFaStatus({ type: "success", msg: "2FA disabled. Only your password is required now." });
      queryClient.setQueryData<MeResponse>(["auth", "me"], (prev) =>
        prev ? { ...prev, totp_enabled: false } : prev,
      );
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
    onError: (error: any) => {
      const msg = error?.message || error?.detail || "Invalid 2FA code";
      setTwoFaStatus({ type: "error", msg });
    },
  });

  const logoutMutation = useMutation({
    mutationFn: () => api.post<LogoutResponse>("/auth/logout"),
    onSuccess: (res) => {
      setSessionStatus({
        type: "success",
        msg: res?.revoked ? "Session revoked on the server. Redirecting to sign in…" : "Signed out. Redirecting to sign in…",
      });
      finishLogout();
    },
    onError: (error: any) => {
      const msg = error?.message || error?.detail || "Could not revoke the session on the server";
      setSessionStatus({ type: "error", msg: `${msg} — signing out locally.` });
      finishLogout();
    },
  });

  function finishLogout() {
    setAuthToken(null);
    window.setTimeout(() => router.push("/login"), 800);
  }

  const copySecret = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
      setTwoFaStatus({
        type: "error",
        msg: "Clipboard access is unavailable — select the secret and copy it manually.",
      });
    }
  };

  const codeInputClass = cn("font-mono tracking-widest", "sm:w-48");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground">Execution mode, broker, data source and risk limits.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Execution &amp; Risk Configuration</CardTitle>
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

      <Card>
        <CardHeader>
          <CardTitle>Two-Factor Authentication (2FA)</CardTitle>
          <CardDescription>
            Require a time-based one-time password (TOTP) in addition to your password. Codes are
            generated by an authenticator app such as Google Authenticator, Authy or 1Password.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {twoFaStatus && (
            <div
              className={cn(
                "rounded-md px-4 py-3 text-sm",
                twoFaStatus.type === "success"
                  ? "bg-positive/10 text-positive"
                  : "bg-destructive/10 text-destructive",
              )}
            >
              {twoFaStatus.msg}
            </div>
          )}

          {meQuery.isLoading ? (
            <Skeleton className="h-6 w-48" />
          ) : meQuery.isError ? (
            <p className="text-sm text-destructive">
              Could not load your account details — sign in again to manage 2FA.
            </p>
          ) : totpEnabled ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="positive" className="gap-1">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  2FA active
                </Badge>
                <span className="text-sm text-muted-foreground">
                  A 6-digit code from your authenticator app is required at sign-in.
                </span>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="space-y-2">
                  <Label htmlFor="totp-disable-code">Authenticator code</Label>
                  <Input
                    id="totp-disable-code"
                    value={totpCode}
                    onChange={(e) => setTotpCode(onlyDigits(e.target.value))}
                    inputMode="numeric"
                    maxLength={8}
                    autoComplete="one-time-code"
                    placeholder="123456"
                    className={codeInputClass}
                    disabled={disableMutation.isPending}
                  />
                </div>
                <Button
                  variant="destructive"
                  onClick={() => disableMutation.mutate(totpCode)}
                  disabled={disableMutation.isPending || totpCode.length !== 6}
                >
                  {disableMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <ShieldOff className="mr-2 h-4 w-4" />
                  )}
                  Disable 2FA
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Disabling removes the stored secret — you will have to set 2FA up again from scratch.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                2FA is not enabled for this account. Set it up to require a one-time code at sign-in.
              </p>

              {!totpSetup && (
                <Button onClick={() => setupMutation.mutate()} disabled={setupMutation.isPending}>
                  {setupMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <KeyRound className="mr-2 h-4 w-4" />
                  )}
                  Set up 2FA
                </Button>
              )}

              {totpSetup && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="totp-secret">Secret key</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        id="totp-secret"
                        readOnly
                        value={totpSetup.secret}
                        onFocus={(e) => e.currentTarget.select()}
                        className="font-mono tracking-widest"
                      />
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => copySecret(totpSetup.secret)}
                        aria-label="Copy secret key"
                      >
                        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Enter this secret manually in your authenticator app (Google Authenticator,
                      Authy, 1Password…). Keep it private — anyone with it can generate your codes.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="totp-uri">Setup URI (otpauth://)</Label>
                    <pre
                      id="totp-uri"
                      className="select-all break-all rounded-md border bg-muted/40 p-3 font-mono text-xs text-muted-foreground"
                    >
                      {totpSetup.provisioning_uri}
                    </pre>
                    <p className="text-xs text-muted-foreground">
                      No QR generator ships with this build, so add the account manually: choose
                      &quot;Add account&quot; → &quot;Enter setup key&quot; in your authenticator app and
                      paste this URI (or type the secret above). Then copy the 6-digit code it shows.
                    </p>
                  </div>

                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <div className="space-y-2">
                      <Label htmlFor="totp-verify-code">6-digit code</Label>
                      <Input
                        id="totp-verify-code"
                        value={totpCode}
                        onChange={(e) => setTotpCode(onlyDigits(e.target.value))}
                        inputMode="numeric"
                        maxLength={8}
                        autoComplete="one-time-code"
                        placeholder="123456"
                        className={codeInputClass}
                        disabled={verifyMutation.isPending}
                      />
                    </div>
                    <Button
                      onClick={() => verifyMutation.mutate(totpCode)}
                      disabled={verifyMutation.isPending || totpCode.length !== 6}
                    >
                      {verifyMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <ShieldCheck className="mr-2 h-4 w-4" />
                      )}
                      Verify &amp; Enable
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Session</CardTitle>
          <CardDescription>
            Signing out revokes the current access token on the server and clears it from this browser.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {sessionStatus && (
            <div
              className={cn(
                "rounded-md px-4 py-3 text-sm",
                sessionStatus.type === "success"
                  ? "bg-positive/10 text-positive"
                  : "bg-destructive/10 text-destructive",
              )}
            >
              {sessionStatus.msg}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {meQuery.data
                ? `Signed in as ${meQuery.data.username} (${meQuery.data.email}).`
                : "Signed in with the access token stored in this browser."}
            </p>
            <Button
              variant="destructive"
              onClick={() => logoutMutation.mutate()}
              disabled={logoutMutation.isPending}
            >
              {logoutMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <LogOut className="mr-2 h-4 w-4" />
              )}
              Log out
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
