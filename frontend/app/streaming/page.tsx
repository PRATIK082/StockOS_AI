"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Inbox, Loader2, PlugZap, Radio, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, ApiError, fmt, getAuthToken } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types (shape-tolerant: the S4 streaming backend may name keys differently;
// never fabricate values — render "—" when a key is absent)
// ---------------------------------------------------------------------------

type ConnState = "connecting" | "live" | "closed";

interface LiveTick {
  symbol: string;
  price: number | null;
  change: number | null;
  changePct: number | null;
  volume: number | null;
  tickTime: string | null;
}

interface WsMessage {
  type: string;
  [key: string]: unknown;
}

type JsonRecord = Record<string, unknown>;

function asRecord(v: unknown): JsonRecord | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as JsonRecord)
    : null;
}

function numOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)))
    return Number(v);
  return null;
}

function strOrNull(v: unknown): string | null {
  if (typeof v === "string" && v.trim() !== "") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return null;
}

/** First non-nullish value found under any of the candidate keys. */
function pick(obj: JsonRecord, keys: string[]): unknown {
  for (const k of keys) {
    const v = obj[k];
    if (v !== null && v !== undefined) return v;
  }
  return undefined;
}

function normTick(raw: unknown): LiveTick | null {
  const o = asRecord(raw);
  if (!o) return null;
  const symbol = strOrNull(pick(o, ["symbol", "ticker", "instrument"]));
  if (!symbol) return null;
  return {
    symbol,
    price: numOrNull(pick(o, ["price", "last", "last_price", "ltp"])),
    change: numOrNull(pick(o, ["change", "day_change", "net_change"])),
    changePct: numOrNull(
      pick(o, ["change_pct", "changePct", "pct_change", "day_change_pct", "pnl_pct", "change_percent"]),
    ),
    volume: numOrNull(pick(o, ["volume", "vol", "qty", "total_volume"])),
    tickTime: strOrNull(
      pick(o, ["tick_time", "tickTime", "time", "ts", "timestamp", "as_of", "updated_at"]),
    ),
  };
}

/** A snapshot payload may be a bare array or an object wrapping one. */
function normTickList(payload: unknown): LiveTick[] {
  const arr = Array.isArray(payload)
    ? payload
    : (() => {
        const o = asRecord(payload);
        if (!o) return [];
        for (const k of ["ticks", "data", "quotes", "prices", "symbols"]) {
          if (Array.isArray(o[k])) return o[k] as unknown[];
        }
        return [];
      })();
  return arr
    .map(normTick)
    .filter((t): t is LiveTick => t !== null);
}

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.message} (HTTP ${err.status})`;
  if (err instanceof Error) return err.message;
  return fallback;
}

/** Backend timestamps are usually naive UTC ISO strings — tag as UTC. */
function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const d = new Date(hasTz ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtTime(iso: string | null | undefined): string {
  const d = parseUtc(iso);
  return d ? d.toLocaleTimeString() : "—";
}

function fmtAge(iso: string | null | undefined): string {
  const d = parseUtc(iso);
  if (!d) return "—";
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  return s < 60 ? `${s}s ago` : `${Math.floor(s / 60)}m ${s % 60}s ago`;
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return fmt(v, digits);
}

function fmtInt(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return Math.round(v).toLocaleString();
}

// ---------------------------------------------------------------------------
// Small building blocks (match operations/pnl conventions)
// ---------------------------------------------------------------------------

function ErrorBanner({ err, fallback }: { err: unknown; fallback: string }) {
  return (
    <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
      {errText(err, fallback)}
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      <Inbox className="h-8 w-8 text-muted-foreground" />
      {children}
    </div>
  );
}

function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string | null;
}) {
  return (
    <div className="rounded-md bg-muted/50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold tabular-nums">{value}</div>
      {hint ? (
        <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}

function ConnBadge({ state }: { state: ConnState }) {
  if (state === "live")
    return (
      <Badge variant="positive" className="gap-1">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
        live
      </Badge>
    );
  if (state === "connecting")
    return (
      <Badge className="gap-1 border-transparent bg-amber-500/15 text-amber-600 dark:text-amber-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        connecting
      </Badge>
    );
  return <Badge variant="muted">closed</Badge>;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const DEFAULT_SYMBOLS = "NSE:RELIANCE,NSE:INFY";
const DEFAULT_INTERVAL_MS = "2000";

function wsBase(): string {
  const http =
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return http.replace(/^http/, "ws");
}

export default function StreamingPage() {
  const [symbolsInput, setSymbolsInput] = useState(DEFAULT_SYMBOLS);
  const [intervalInput, setIntervalInput] = useState(DEFAULT_INTERVAL_MS);
  const [conn, setConn] = useState<ConnState>("closed");
  const [ticks, setTicks] = useState<Record<string, LiveTick>>({});
  const [lastHeartbeat, setLastHeartbeat] = useState<string | null>(null);
  const [subNote, setSubNote] = useState<string | null>(null);
  const [wsError, setWsError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  // Socket closes on unmount.
  useEffect(() => {
    return () => {
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  // ---------------- REST: status (15s) ----------------
  const status = useQuery<JsonRecord>({
    queryKey: ["streaming", "status"],
    queryFn: () => api.get<JsonRecord>("/streaming/status"),
    retry: false,
    refetchInterval: 15_000,
  });
  const st = status.data ?? null;

  // ---------------- REST: market (30s) ----------------
  const market = useQuery<JsonRecord>({
    queryKey: ["streaming", "market"],
    queryFn: () => api.get<JsonRecord>("/streaming/market"),
    retry: false,
    refetchInterval: 30_000,
  });
  const mk = market.data ?? null;
  const marketOpenRaw = mk ? pick(mk, ["is_open", "open", "market_open"]) : undefined;
  const marketOpen =
    typeof marketOpenRaw === "boolean" ? marketOpenRaw : null;
  const marketReason = mk
    ? strOrNull(pick(mk, ["reason", "message", "note", "status", "session"]))
    : null;
  const marketTime = mk
    ? strOrNull(pick(mk, ["time", "as_of", "timestamp", "server_time", "updated_at"]))
    : null;
  const nextTradingDay = mk
    ? strOrNull(pick(mk, ["next_trading_day", "next_open", "next_session", "next_trading_session"]))
    : null;

  // ---------------- REST: latest snapshot (manual refresh) ----------------
  const latestSymbols = symbolsInput.trim() || DEFAULT_SYMBOLS;
  const latest = useQuery<unknown>({
    queryKey: ["streaming", "latest", latestSymbols],
    queryFn: () =>
      api.get<unknown>(
        `/streaming/quotes/latest?symbols=${encodeURIComponent(latestSymbols)}`,
      ),
    retry: false,
  });
  const latestTicks = normTickList(latest.data);

  // ---------------- WebSocket ----------------
  function connect() {
    if (
      socketRef.current &&
      (socketRef.current.readyState === WebSocket.OPEN ||
        socketRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    const symbols = symbolsInput.trim() || DEFAULT_SYMBOLS;
    const parsed = parseInt(intervalInput.trim(), 10);
    const intervalMs = Number.isFinite(parsed) && parsed > 0 ? parsed : 2000;
    const params = new URLSearchParams({
      symbols,
      interval_ms: String(intervalMs),
    });
    const token = getAuthToken();
    if (token) params.set("token", token);
    const url = `${wsBase()}/api/streaming/quotes?${params.toString()}`;

    setWsError(null);
    setConn("connecting");
    const ws = new WebSocket(url);
    socketRef.current = ws;

    ws.onopen = () => setConn("live");

    ws.onmessage = (ev: MessageEvent) => {
      let msg: WsMessage;
      try {
        msg = JSON.parse(String(ev.data)) as WsMessage;
      } catch {
        return;
      }
      if (!msg || typeof msg.type !== "string") return;
      switch (msg.type) {
        case "snapshot": {
          const list = normTickList(
            msg.ticks ?? msg.data ?? msg.quotes ?? msg.prices ?? msg,
          );
          setTicks(Object.fromEntries(list.map((t) => [t.symbol, t])));
          break;
        }
        case "tick": {
          const t = normTick(msg.tick ?? msg.data ?? msg);
          if (t) setTicks((prev) => ({ ...prev, [t.symbol]: t }));
          break;
        }
        case "heartbeat": {
          const at = strOrNull(
            msg.at ?? msg.time ?? msg.ts ?? msg.timestamp ?? new Date().toISOString(),
          );
          setLastHeartbeat(at);
          break;
        }
        case "subscribed":
        case "unsubscribed": {
          const syms = msg.symbols ?? msg.data;
          setSubNote(
            strOrNull(msg.note ?? msg.message) ??
              (Array.isArray(syms)
                ? `${msg.type}: ${syms.map(String).join(", ")}`
                : `${msg.type}`),
          );
          break;
        }
        case "error": {
          setWsError(
            strOrNull(msg.detail ?? msg.message ?? msg.error) ??
              "Streaming error from server.",
          );
          break;
        }
        default:
          break;
      }
    };

    ws.onerror = () => {
      setWsError(
        "WebSocket error — is the backend running at ws://localhost:8000?",
      );
    };
    ws.onclose = () => {
      if (socketRef.current === ws) socketRef.current = null;
      setConn("closed");
    };
  }

  function disconnect() {
    socketRef.current?.close();
    socketRef.current = null;
    setConn("closed");
  }

  const tickRows = Object.values(ticks).sort((a, b) =>
    a.symbol.localeCompare(b.symbol),
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Streaming</h1>
          <p className="text-sm text-muted-foreground">
            Live quotes over the S4 WebSocket feed. The socket closes
            automatically when you leave this page (unmount).
          </p>
        </div>
        <ConnBadge state={conn} />
      </div>

      {/* ---------------- Status ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4" />
                Stream status
              </CardTitle>
              <CardDescription>
                Authenticated GET /streaming/status, auto-refreshed every 15
                seconds.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void status.refetch()}
              disabled={status.isFetching}
            >
              {status.isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {status.isError && (
            <ErrorBanner err={status.error} fallback="Could not load stream status" />
          )}
          {status.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : st ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile
                label="Provider"
                value={strOrNull(pick(st, ["provider", "provider_name", "data_provider"])) ?? "—"}
                hint={strOrNull(pick(st, ["mode", "stream_mode", "run_mode"])) ? `mode: ${strOrNull(pick(st, ["mode", "stream_mode", "run_mode"]))}` : undefined}
              />
              <StatTile
                label="Connected symbols"
                value={fmtInt(
                  numOrNull(pick(st, ["connected_symbols", "symbol_count", "connected", "num_symbols"])) ??
                    (Array.isArray(pick(st, ["symbols", "connected_symbol_list"]))
                      ? (pick(st, ["symbols", "connected_symbol_list"]) as unknown[]).length
                      : null),
                )}
                hint={
                  Array.isArray(pick(st, ["symbols", "connected_symbol_list"]))
                    ? (pick(st, ["symbols", "connected_symbol_list"]) as unknown[]).map(String).slice(0, 4).join(", ")
                    : undefined
                }
              />
              <StatTile
                label="Subscribers"
                value={fmtInt(
                  numOrNull(pick(st, ["subscribers", "subscriber_count", "connections", "num_subscribers", "clients"])),
                )}
              />
              <StatTile
                label="Interval"
                value={
                  numOrNull(pick(st, ["interval_ms", "interval", "poll_interval_ms"])) != null
                    ? `${fmtInt(numOrNull(pick(st, ["interval_ms", "interval", "poll_interval_ms"])))} ms`
                    : "—"
                }
              />
              <StatTile
                label="Heartbeat age"
                value={
                  strOrNull(pick(st, ["heartbeat_age", "heartbeat_age_human"])) ??
                  fmtAge(strOrNull(pick(st, ["last_heartbeat", "last_heartbeat_at", "heartbeat_at"])))
                }
                hint={
                  strOrNull(pick(st, ["last_heartbeat", "last_heartbeat_at", "heartbeat_at"]))
                    ? `last: ${fmtTime(strOrNull(pick(st, ["last_heartbeat", "last_heartbeat_at", "heartbeat_at"])))}`
                    : undefined
                }
              />
              <StatTile
                label="Mode"
                value={strOrNull(pick(st, ["mode", "stream_mode", "run_mode"])) ?? "—"}
              />
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ---------------- Live quotes (WebSocket) ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Radio className="h-4 w-4" />
                Live quotes
              </CardTitle>
              <CardDescription>
                Native WebSocket to /api/streaming/quotes. Snapshot replaces the
                table; each tick upserts one row (latest tick per symbol).
              </CardDescription>
            </div>
            <ConnBadge state={conn} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_160px_auto]">
            <div className="space-y-1.5">
              <Label htmlFor="stream-symbols">Symbols (comma-separated)</Label>
              <Input
                id="stream-symbols"
                value={symbolsInput}
                onChange={(e) => setSymbolsInput(e.target.value)}
                placeholder={DEFAULT_SYMBOLS}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="stream-interval">Interval (ms)</Label>
              <Input
                id="stream-interval"
                value={intervalInput}
                onChange={(e) => setIntervalInput(e.target.value)}
                placeholder={DEFAULT_INTERVAL_MS}
                inputMode="numeric"
              />
            </div>
            <div className="flex items-end gap-2">
              {conn === "live" || conn === "connecting" ? (
                <Button variant="outline" onClick={disconnect}>
                  Disconnect
                </Button>
              ) : (
                <Button onClick={connect}>
                  <PlugZap className="mr-2 h-4 w-4" />
                  Connect
                </Button>
              )}
            </div>
          </div>

          {wsError && (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {wsError}
            </div>
          )}
          {subNote && (
            <p className="text-xs text-muted-foreground">{subNote}</p>
          )}
          <p className="text-xs text-muted-foreground">
            Last heartbeat:{" "}
            <span className="tabular-nums">
              {lastHeartbeat ? `${fmtTime(lastHeartbeat)} (${fmtAge(lastHeartbeat)})` : "—"}
            </span>
          </p>

          {tickRows.length === 0 ? (
            <EmptyState>
              <p className="font-medium text-foreground">No ticks yet</p>
              <p className="max-w-md text-xs">
                Press Connect to open the socket — a snapshot fills this table
                and each tick updates its symbol row in place.
              </p>
            </EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="text-right">Change</TableHead>
                  <TableHead className="text-right">Change %</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Tick time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tickRows.map((t) => (
                  <TableRow key={t.symbol}>
                    <TableCell className="font-medium">{t.symbol}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNum(t.price)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        (t.change ?? 0) > 0
                          ? "text-positive"
                          : (t.change ?? 0) < 0
                            ? "text-negative"
                            : "",
                      )}
                    >
                      {t.change == null
                        ? "—"
                        : `${t.change > 0 ? "+" : ""}${fmtNum(t.change)}`}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        (t.changePct ?? 0) > 0
                          ? "text-positive"
                          : (t.changePct ?? 0) < 0
                            ? "text-negative"
                            : "",
                      )}
                    >
                      {t.changePct == null
                        ? "—"
                        : `${t.changePct > 0 ? "+" : ""}${fmtNum(t.changePct)}%`}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtInt(t.volume)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtTime(t.tickTime)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* ---------------- Market status + latest snapshot ---------------- */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>Market status</CardTitle>
                <CardDescription>
                  GET /streaming/market, auto-refreshed every 30 seconds.
                </CardDescription>
              </div>
              {marketOpen === true ? (
                <Badge variant="positive">Open</Badge>
              ) : marketOpen === false ? (
                <Badge variant="negative">Closed</Badge>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {market.isError && (
              <ErrorBanner err={market.error} fallback="Could not load market status" />
            )}
            {market.isLoading ? (
              <div className="space-y-2">
                {[0, 1].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : mk ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <StatTile
                  label="State"
                  value={marketOpen === true ? "Open" : marketOpen === false ? "Closed" : "—"}
                  hint={marketReason}
                />
                <StatTile
                  label="As of"
                  value={marketTime ? fmtTime(marketTime) : "—"}
                  hint={nextTradingDay ? `Next trading day: ${nextTradingDay}` : undefined}
                />
              </div>
            ) : null}
            {!market.isLoading && !market.isError && !mk ? (
              <EmptyState>No market status returned yet.</EmptyState>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>Latest snapshot (REST)</CardTitle>
                <CardDescription>
                  GET /streaming/quotes/latest for the symbols above.
                </CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void latest.refetch()}
                disabled={latest.isFetching}
              >
                {latest.isFetching ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {latest.isError && (
              <ErrorBanner err={latest.error} fallback="Could not load latest quotes" />
            )}
            {latest.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : latestTicks.length === 0 ? (
              <EmptyState>
                No snapshot rows for “{latestSymbols}” yet.
              </EmptyState>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Change %</TableHead>
                    <TableHead className="text-right">Volume</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {latestTicks.map((t) => (
                    <TableRow key={t.symbol}>
                      <TableCell className="font-medium">{t.symbol}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtNum(t.price)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right tabular-nums",
                          (t.changePct ?? 0) > 0
                            ? "text-positive"
                            : (t.changePct ?? 0) < 0
                              ? "text-negative"
                              : "",
                        )}
                      >
                        {t.changePct == null
                          ? "—"
                          : `${t.changePct > 0 ? "+" : ""}${fmtNum(t.changePct)}%`}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtInt(t.volume)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
