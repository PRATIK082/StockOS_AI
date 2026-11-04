"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Gauge, HeartPulse, Loader2, RefreshCw, Server } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types (tolerant: backend may omit optional fields, never fabricate)
// ---------------------------------------------------------------------------

interface HealthResponse {
  app?: string | null;
  environment?: string | null;
  status?: string | null;
  process?: {
    rss_mb?: number | null;
    threads?: number | null;
    handles?: number | null;
    fds?: number | null;
    cpu_percent?: number | null;
  } | null;
  database?: {
    kind?: string | null;
    path?: string | null;
    size_mb?: number | null;
  } | null;
  metrics?: {
    rows_7d?: number | null;
  } | null;
}

interface LatencyRoute {
  route: string;
  method?: string | null;
  count?: number | null;
  requests?: number | null;
  avg_ms?: number | null;
  p50_ms?: number | null;
  p95_ms?: number | null;
}

interface LatencyResponse {
  window_hours?: number | null;
  routes?: LatencyRoute[] | null;
}

interface TrafficRoute {
  route: string;
  count?: number | null;
  requests?: number | null;
  errors?: number | null;
  errors_5xx?: number | null;
  error_rate?: number | null;
}

interface TrafficResponse {
  window_hours?: number | null;
  total_requests?: number | null;
  errors_5xx?: number | null;
  by_status?: Record<string, number> | null;
  routes?: TrafficRoute[] | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.message} (HTTP ${err.status})`;
  if (err instanceof Error) return err.message;
  return fallback;
}

function num(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function int(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return Math.round(v).toLocaleString();
}

function routeCount(r: TrafficRoute | LatencyRoute): number {
  const v = (r as TrafficRoute).count ?? (r as TrafficRoute).requests ?? 0;
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function routeErrors(r: TrafficRoute): number {
  const v = r.errors ?? r.errors_5xx ?? 0;
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function ErrorBanner({ err, fallback }: { err: unknown; fallback: string }) {
  return (
    <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
      {errText(err, fallback)}
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
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
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold tabular-nums">{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OperationsPage() {
  const health = useQuery<HealthResponse>({
    queryKey: ["monitoring", "health"],
    queryFn: () => api.get<HealthResponse>("/monitoring/health"),
    retry: false,
    refetchInterval: 15_000,
  });

  const latency = useQuery<LatencyResponse>({
    queryKey: ["monitoring", "latency"],
    queryFn: () => api.get<LatencyResponse>("/monitoring/latency?window_hours=24"),
    retry: false,
  });

  const traffic = useQuery<TrafficResponse>({
    queryKey: ["monitoring", "traffic"],
    queryFn: () => api.get<TrafficResponse>("/monitoring/traffic?window_hours=24"),
    retry: false,
    refetchInterval: 15_000,
  });

  const trafficSummary = useMemo(() => {
    const routes = traffic.data?.routes ?? [];
    const total =
      traffic.data?.total_requests ?? routes.reduce((acc, r) => acc + routeCount(r), 0);
    const errors =
      traffic.data?.errors_5xx ?? routes.reduce((acc, r) => acc + routeErrors(r), 0);
    return { routes, total, errors };
  }, [traffic.data]);

  const latencyRoutes = useMemo(() => latency.data?.routes ?? [], [latency.data]);

  // Handles on Windows, fds on Linux — the backend keys it as `fds` on Linux
  // and `handles` via num_handles() on Windows; surface whichever is present.
  const handles = health.data?.process?.handles ?? health.data?.process?.fds ?? null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Operations</h1>
          <p className="text-sm text-muted-foreground">
            Service health, per-route latency and traffic. Health and traffic refresh every
            15 seconds.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void health.refetch();
            void latency.refetch();
            void traffic.refetch();
          }}
          disabled={health.isFetching || latency.isFetching || traffic.isFetching}
        >
          {health.isFetching || latency.isFetching || traffic.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Refresh all
        </Button>
      </div>

      {/* ---------------- Service Health ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <HeartPulse className="h-4 w-4" />
                Service Health
              </CardTitle>
              <CardDescription>
                Process and database snapshot from the authenticated /monitoring/health endpoint.
              </CardDescription>
            </div>
            {health.data?.status ? (
              <Badge variant="positive">{health.data.status}</Badge>
            ) : health.data ? (
              <Badge variant="positive">OK</Badge>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {health.isError && <ErrorBanner err={health.error} fallback="Could not load service health" />}
          {health.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : health.data ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatTile label="RSS memory" value={health.data.process?.rss_mb != null ? `${num(health.data.process.rss_mb)} MB` : "—"} />
                <StatTile label="Threads" value={int(health.data.process?.threads)} />
                <StatTile
                  label="Handles / FDs"
                  value={int(handles)}
                  hint="handles on Windows, fds on Linux"
                />
                <StatTile
                  label="CPU"
                  value={health.data.process?.cpu_percent != null ? `${num(health.data.process.cpu_percent, 1)}%` : "—"}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatTile
                  label="DB size"
                  value={health.data.database?.size_mb != null ? `${num(health.data.database.size_mb)} MB` : "—"}
                  hint={health.data.database?.kind ?? health.data.database?.path ?? undefined}
                />
                <StatTile
                  label="Metrics rows (7d)"
                  value={health.data.metrics?.rows_7d != null ? int(health.data.metrics.rows_7d) : "—"}
                  hint={health.data.metrics?.rows_7d == null ? "No metrics rows recorded yet" : undefined}
                />
                <StatTile label="App" value={health.data.app ?? "—"} />
                <StatTile label="Environment" value={health.data.environment ?? "—"} />
              </div>
              {health.data.metrics?.rows_7d == null ? (
                <EmptyState>
                  No request-metric rows recorded in the last 7 days yet. Latency and traffic
                  panels below will stay empty until the metrics middleware records traffic.
                </EmptyState>
              ) : null}
            </>
          ) : null}
        </CardContent>
      </Card>

      {/* ---------------- Per-route Latency ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Gauge className="h-4 w-4" />
                Per-route Latency
              </CardTitle>
              <CardDescription>
                Count / average / p50 / p95 per route over the last
                {latency.data?.window_hours != null ? ` ${latency.data.window_hours}h` : " 24h"}.
                Fetched on demand.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => latency.refetch()}
              disabled={latency.isFetching}
            >
              {latency.isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {latency.isError && (
            <ErrorBanner err={latency.error} fallback="Could not load latency metrics" />
          )}
          {latency.isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : latencyRoutes.length === 0 ? (
            <EmptyState>
              No latency metrics recorded yet for this window. Routes appear here once requests
              flow through the metrics middleware.
            </EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Route</TableHead>
                  <TableHead>Method</TableHead>
                  <TableHead className="text-right">Requests</TableHead>
                  <TableHead className="text-right">Avg ms</TableHead>
                  <TableHead className="text-right">p50 ms</TableHead>
                  <TableHead className="text-right">p95 ms</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {latencyRoutes.map((r) => (
                  <TableRow key={`${r.method ?? ""}:${r.route}`}>
                    <TableCell className="font-mono text-xs">{r.route}</TableCell>
                    <TableCell>
                      {r.method ? (
                        <Badge variant="muted" className="font-mono">
                          {r.method}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{int(routeCount(r))}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(r.avg_ms)}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(r.p50_ms)}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        r.p95_ms != null && r.avg_ms != null && r.p95_ms > r.avg_ms * 3
                          ? "text-negative"
                          : "",
                      )}
                    >
                      {num(r.p95_ms)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* ---------------- Traffic ---------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Traffic Summary
          </CardTitle>
          <CardDescription>
            Request counts and 5xx errors per route over the last
            {traffic.data?.window_hours != null ? ` ${traffic.data.window_hours}h` : " 24h"}.
            Auto-refreshes every 15 seconds.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {traffic.isError && (
            <ErrorBanner err={traffic.error} fallback="Could not load traffic metrics" />
          )}
          {traffic.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatTile label="Total requests" value={int(trafficSummary.total)} />
                <StatTile label="5xx errors" value={int(trafficSummary.errors)} />
                <StatTile
                  label="Error rate"
                  value={
                    trafficSummary.total > 0
                      ? `${num((trafficSummary.errors / trafficSummary.total) * 100)}%`
                      : "—"
                  }
                />
                <StatTile label="Routes" value={int(trafficSummary.routes.length)} />
              </div>

              {traffic.data?.by_status && Object.keys(traffic.data.by_status).length > 0 ? (
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-medium">
                    <Server className="h-4 w-4" />
                    By status
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(traffic.data.by_status).map(([status, count]) => (
                      <Badge
                        key={status}
                        variant={String(status).startsWith("5") ? "negative" : "muted"}
                        className="tabular-nums"
                      >
                        {status}: {int(count)}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No per-status breakdown reported for this window.
                </p>
              )}

              {trafficSummary.routes.length === 0 ? (
                <EmptyState>
                  No traffic recorded yet for this window. Per-route counts appear here once
                  requests flow through the metrics middleware.
                </EmptyState>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Route</TableHead>
                      <TableHead className="text-right">Requests</TableHead>
                      <TableHead className="text-right">5xx</TableHead>
                      <TableHead className="text-right">Error rate</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {trafficSummary.routes.map((r) => {
                      const count = routeCount(r);
                      const errors = routeErrors(r);
                      const rate =
                        r.error_rate != null
                          ? r.error_rate
                          : count > 0
                            ? errors / count
                            : null;
                      return (
                        <TableRow key={r.route}>
                          <TableCell className="font-mono text-xs">{r.route}</TableCell>
                          <TableCell className="text-right tabular-nums">{int(count)}</TableCell>
                          <TableCell
                            className={cn(
                              "text-right tabular-nums",
                              errors > 0 ? "text-negative" : "",
                            )}
                          >
                            {int(errors)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {rate != null ? `${num(rate * 100)}%` : "—"}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
