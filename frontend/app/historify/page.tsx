"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CalendarClock,
  Database,
  Download,
  FileJson,
  FileSpreadsheet,
  Layers,
  ListChecks,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Table2,
  Trash2,
  Upload,
} from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE, api, fmt, fmtCompact, getAuthToken, pctColor } from "@/lib/api";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* API response shapes (mirrors backend/app/services/historify/store.py)       */
/* -------------------------------------------------------------------------- */

interface HistorifyStatus {
  rows: number;
  symbols: string[];
  catalog: CatalogRow[];
}

interface IntervalsResponse {
  intervals: string[];
}

interface CatalogRow {
  symbol: string;
  exchange: string;
  interval: string;
  first_ts: string | null;
  last_ts: string | null;
  rows: number;
  updated_at: string | null;
}

interface WatchlistRow {
  symbol: string;
  exchange: string;
  created_at: string | null;
}

interface JobRow {
  id: string;
  status: string;
  exchange: string;
  interval: string;
  period: string | null;
  start_date: string | null;
  end_date: string | null;
  total: number;
  completed: number;
  failed: number;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface JobItem {
  id: string;
  job_id: string;
  symbol: string;
  exchange: string;
  interval: string;
  status: string;
  rows: number;
  error: string | null;
  updated_at: string | null;
}

interface JobDetail extends JobRow {
  config: Record<string, unknown>;
  items: JobItem[];
}

interface OhlcvRow {
  symbol: string;
  exchange: string;
  interval: string;
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  provider: string | null;
}

interface QueryResponse {
  symbol: string;
  interval: string;
  rows: OhlcvRow[];
}

interface GapRow {
  from: string;
  to: string;
  gap_days: number;
}

interface GapsResponse {
  symbol: string;
  interval: string;
  gaps: GapRow[];
}

interface SymbolMetaRow {
  symbol: string;
  exchange: string;
  instrument_type: string;
  underlying: string | null;
  expiry: string | null;
  strike: number | null;
  lot_size: number;
  tick_size: number | null;
  broker: string | null;
  updated_at: string | null;
}

interface ImportResult {
  inserted: number;
  skipped: number;
  total: number;
}

/* -------------------------------------------------------------------------- */
/* Constants & helpers                                                        */
/* -------------------------------------------------------------------------- */

const FALLBACK_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"];
const PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"];
const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "canceled"]);
const ALL = "all";

const SAMPLE_RECORDS = `[
  {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "interval": "1d",
    "ts": "2024-01-02T00:00:00",
    "open": 2300.0,
    "high": 2340.0,
    "low": 2290.0,
    "close": 2330.0,
    "volume": 1000000
  }
]`;

type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "positive"
  | "negative"
  | "muted";

const JOB_STATUS_VARIANT: Record<string, BadgeVariant> = {
  queued: "secondary",
  running: "default",
  paused: "muted",
  completed: "positive",
  failed: "negative",
  canceled: "outline",
};

function statusVariant(status: string): BadgeVariant {
  return JOB_STATUS_VARIANT[status] ?? "secondary";
}

function parseSymbols(raw: string): string[] {
  const parts = raw
    .split(/[\s,;]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  return Array.from(new Set(parts));
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

function shortTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString();
}

function dayOf(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts).slice(0, 10);
  return d.toLocaleDateString();
}

function useIntervals() {
  return useQuery({
    queryKey: ["historify", "intervals"],
    queryFn: () => api.get<IntervalsResponse>("/historify/intervals"),
  });
}

function useIntervalOptions(): string[] {
  const { data } = useIntervals();
  return data?.intervals?.length ? data.intervals : FALLBACK_INTERVALS;
}

/** Authenticated fetch for endpoints that need multipart or raw file responses. */
async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = (body as { detail?: string })?.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body — keep the status text */
    }
    throw new Error(detail);
  }
  return res;
}

/** Downloads a file through the bearer token (the export endpoints are authenticated). */
async function downloadBlob(path: string, filename: string): Promise<void> {
  const res = await authFetch(path);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* -------------------------------------------------------------------------- */
/* Small shared presentational pieces                                         */
/* -------------------------------------------------------------------------- */

function ErrorBanner({
  message,
  onDismiss,
}: {
  message: string | null;
  onDismiss?: () => void;
}) {
  if (!message) return null;
  return (
    <div className="mb-4 flex items-start justify-between gap-3 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
      <span className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{message}</span>
      </span>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-xs underline underline-offset-2 opacity-80 hover:opacity-100"
        >
          Dismiss
        </button>
      ) : null}
    </div>
  );
}

function SuccessBanner({ message, onDismiss }: { message: string | null; onDismiss?: () => void }) {
  if (!message) return null;
  return (
    <div className="mb-4 flex items-start justify-between gap-3 rounded-md bg-positive/10 px-4 py-3 text-sm text-positive">
      <span>{message}</span>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-xs underline underline-offset-2 opacity-80 hover:opacity-100"
        >
          Dismiss
        </button>
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          {icon}
        </div>
        <p className="mt-1 text-2xl font-semibold">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-sm text-muted-foreground">{children}</p>;
}

function TableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 1. Overview                                                                */
/* -------------------------------------------------------------------------- */

function OverviewTab() {
  const status = useQuery({
    queryKey: ["historify", "status"],
    queryFn: () => api.get<HistorifyStatus>("/historify/status"),
  });
  const intervals = useIntervals();
  const watchlist = useQuery({
    queryKey: ["historify", "watchlist"],
    queryFn: () => api.get<WatchlistRow[]>("/historify/watchlist"),
  });

  const rows = status.data?.rows ?? 0;
  const symbols = status.data?.symbols ?? [];
  const catalog = status.data?.catalog ?? [];
  const intervalList = intervals.data?.intervals ?? FALLBACK_INTERVALS;

  return (
    <div className="space-y-4">
      <ErrorBanner
        message={status.isError ? errorMessage(status.error, "Failed to load warehouse status") : null}
      />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Stored bars"
          value={fmtCompact(rows)}
          hint="OHLCV rows in DuckDB"
          icon={<Database className="h-4 w-4 text-muted-foreground" />}
        />
        <StatCard
          label="Symbols"
          value={String(symbols.length)}
          hint="Distinct symbols with data"
          icon={<Table2 className="h-4 w-4 text-muted-foreground" />}
        />
        <StatCard
          label="Datasets"
          value={String(catalog.length)}
          hint="Symbol x exchange x interval"
          icon={<Layers className="h-4 w-4 text-muted-foreground" />}
        />
        <StatCard
          label="Watchlist"
          value={String(watchlist.data?.length ?? 0)}
          hint="Symbols queued for download"
          icon={<ListChecks className="h-4 w-4 text-muted-foreground" />}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Warehouse status</CardTitle>
          <CardDescription>
            Live counters served by <span className="font-mono">/historify/status</span>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status.isLoading ? (
            <TableSkeleton rows={3} />
          ) : (
            <div className="space-y-5">
              <div>
                <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  Supported intervals
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {intervalList.map((i) => (
                    <Badge key={i} variant="secondary">
                      {i}
                    </Badge>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  Symbols with data
                </p>
                {symbols.length === 0 ? (
                  <EmptyState>
                    No data yet — queue a download job or import a CSV to populate the warehouse.
                  </EmptyState>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {symbols.map((s) => (
                      <Badge key={s} variant="outline">
                        {s}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  Catalog entries
                </p>
                {catalog.length === 0 ? (
                  <EmptyState>No datasets catalogued yet.</EmptyState>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {catalog.map((c) => (
                      <Badge key={`${c.symbol}-${c.exchange}-${c.interval}`} variant="outline">
                        {c.symbol} · {c.exchange} · {c.interval} · {fmtCompact(c.rows)} rows
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  status.refetch();
                  watchlist.refetch();
                  intervals.refetch();
                }}
                disabled={status.isFetching}
              >
                {status.isFetching ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Refresh
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 2. Watchlist                                                               */
/* -------------------------------------------------------------------------- */

function WatchlistTab() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("");
  const [bulk, setBulk] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const { data: rows, isLoading, isError, error: queryError } = useQuery({
    queryKey: ["historify", "watchlist"],
    queryFn: () => api.get<WatchlistRow[]>("/historify/watchlist"),
  });

  const addMutation = useMutation({
    mutationFn: (sym: string) =>
      api.post<WatchlistRow>("/historify/watchlist", { symbol: sym, exchange }),
    onSuccess: (_data, sym) => {
      setSymbol("");
      setError(null);
      setNotice(`${sym} added to the watchlist.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Failed to add symbol")),
  });

  const bulkMutation = useMutation({
    mutationFn: (syms: string[]) =>
      api.post<{ items: WatchlistRow[] }>("/historify/watchlist/bulk", {
        symbols: syms,
        exchange,
      }),
    onSuccess: (data, syms) => {
      setBulk("");
      setError(null);
      setNotice(`${syms.length} symbol(s) added to the watchlist.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
      void data;
    },
    onError: (e) => setError(errorMessage(e, "Failed to add symbols")),
  });

  const removeMutation = useMutation({
    mutationFn: (row: WatchlistRow) =>
      api.del<{ removed: string }>(
        `/historify/watchlist/${encodeURIComponent(row.symbol)}?exchange=${encodeURIComponent(
          row.exchange,
        )}`,
      ),
    onSuccess: (_d, row) => {
      setError(null);
      setNotice(`${row.symbol} removed from the watchlist.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Failed to remove symbol")),
  });

  const bulkSymbols = parseSymbols(bulk);

  return (
    <div className="space-y-4">
      <ErrorBanner
        message={error ?? (isError ? errorMessage(queryError, "Failed to load watchlist") : null)}
        onDismiss={() => setError(null)}
      />
      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Add a symbol</CardTitle>
            <CardDescription>
              Symbols are stored uppercase with an exchange tag. Duplicates are ignored.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                const sym = symbol.trim().toUpperCase();
                if (sym) addMutation.mutate(sym);
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="wl-symbol">Symbol</Label>
                <Input
                  id="wl-symbol"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  placeholder="RELIANCE"
                  disabled={addMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="wl-exchange">Exchange</Label>
                <Input
                  id="wl-exchange"
                  value={exchange}
                  onChange={(e) => setExchange(e.target.value.toUpperCase())}
                  placeholder="NSE"
                  disabled={addMutation.isPending}
                />
              </div>
              <Button type="submit" disabled={!symbol.trim() || addMutation.isPending}>
                {addMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-2 h-4 w-4" />
                )}
                Add symbol
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Bulk add</CardTitle>
            <CardDescription>
              Comma, space or newline separated. {bulkSymbols.length > 0 ? `${bulkSymbols.length} detected.` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                if (bulkSymbols.length > 0) bulkMutation.mutate(bulkSymbols);
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="wl-bulk">Symbols</Label>
                <Textarea
                  id="wl-bulk"
                  value={bulk}
                  onChange={(e) => setBulk(e.target.value)}
                  placeholder="RELIANCE, TCS INFY"
                  className="min-h-[100px]"
                  disabled={bulkMutation.isPending}
                />
              </div>
              <Button type="submit" disabled={bulkSymbols.length === 0 || bulkMutation.isPending}>
                {bulkMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-2 h-4 w-4" />
                )}
                Add {bulkSymbols.length > 0 ? `${bulkSymbols.length} symbol(s)` : "symbols"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Watchlist</CardTitle>
          <CardDescription>Symbols queued for warehouse download jobs.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <TableSkeleton />
          ) : !rows || rows.length === 0 ? (
            <EmptyState>No data yet — the watchlist is empty.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Added</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={`${row.exchange}:${row.symbol}`}>
                    <TableCell className="font-medium">{row.symbol}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{row.exchange}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {shortTs(row.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove ${row.symbol}`}
                        disabled={removeMutation.isPending}
                        onClick={() => removeMutation.mutate(row)}
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
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 3. Catalog                                                                 */
/* -------------------------------------------------------------------------- */

function CatalogTab() {
  const qc = useQueryClient();
  const [symbolFilter, setSymbolFilter] = useState("");
  const [exchangeFilter, setExchangeFilter] = useState("");
  const [intervalFilter, setIntervalFilter] = useState(ALL);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const intervalOptions = useIntervalOptions();

  const catalog = useQuery({
    queryKey: [
      "historify",
      "catalog",
      symbolFilter.trim().toUpperCase(),
      exchangeFilter.trim().toUpperCase(),
      intervalFilter,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim().toUpperCase());
      if (exchangeFilter.trim()) params.set("exchange", exchangeFilter.trim().toUpperCase());
      if (intervalFilter !== ALL) params.set("interval", intervalFilter);
      const qs = params.toString();
      return api.get<CatalogRow[]>(`/historify/catalog${qs ? `?${qs}` : ""}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (row: CatalogRow) => {
      const params = new URLSearchParams();
      params.set("exchange", row.exchange);
      params.set("interval", row.interval);
      return api.del<{ deleted: number; symbol: string }>(
        `/historify/catalog/${encodeURIComponent(row.symbol)}?${params.toString()}`,
      );
    },
    onSuccess: (_d, row) => {
      setError(null);
      setNotice(`${row.symbol} (${row.exchange} / ${row.interval}) deleted from the warehouse.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Failed to delete dataset")),
  });

  const hasFilters =
    symbolFilter.trim() !== "" || exchangeFilter.trim() !== "" || intervalFilter !== ALL;

  return (
    <div className="space-y-4">
      <ErrorBanner
        message={
          error ?? (catalog.isError ? errorMessage(catalog.error, "Failed to load catalog") : null)
        }
        onDismiss={() => setError(null)}
      />
      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Datasets</CardTitle>
          <CardDescription>
            One row per symbol / exchange / interval, with its stored bar count and date range.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 grid gap-3 md:grid-cols-4">
            <div className="space-y-2">
              <Label htmlFor="cat-symbol">Symbol</Label>
              <Input
                id="cat-symbol"
                value={symbolFilter}
                onChange={(e) => setSymbolFilter(e.target.value)}
                placeholder="RELIANCE"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cat-exchange">Exchange</Label>
              <Input
                id="cat-exchange"
                value={exchangeFilter}
                onChange={(e) => setExchangeFilter(e.target.value)}
                placeholder="NSE"
              />
            </div>
            <div className="space-y-2">
              <Label>Interval</Label>
              <Select value={intervalFilter} onValueChange={setIntervalFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="Any interval" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Any interval</SelectItem>
                  {intervalOptions.map((i) => (
                    <SelectItem key={i} value={i}>
                      {i}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSymbolFilter("");
                  setExchangeFilter("");
                  setIntervalFilter(ALL);
                }}
                disabled={!hasFilters}
              >
                Clear filters
              </Button>
            </div>
          </div>

          {catalog.isLoading ? (
            <TableSkeleton />
          ) : !catalog.data || catalog.data.length === 0 ? (
            <EmptyState>
              {hasFilters
                ? "No datasets match these filters."
                : "No data yet — the catalog is empty. Download or import some data first."}
            </EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Interval</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead>First</TableHead>
                  <TableHead>Last</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {catalog.data.map((row) => (
                  <TableRow key={`${row.exchange}:${row.symbol}:${row.interval}`}>
                    <TableCell className="font-medium">{row.symbol}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{row.exchange}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{row.interval}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmtCompact(row.rows)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{dayOf(row.first_ts)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{dayOf(row.last_ts)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {shortTs(row.updated_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${row.symbol} ${row.interval}`}
                        disabled={deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(row)}
                      >
                        <Trash2 className="h-4 w-4 text-muted-foreground" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          <p className="mt-3 text-xs text-muted-foreground">
            Deleting a dataset removes its bars and its catalog row from the warehouse.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 4. Download jobs                                                           */
/* -------------------------------------------------------------------------- */

function JobsTab() {
  const qc = useQueryClient();
  const [symbolsText, setSymbolsText] = useState("");
  const [useWatchlist, setUseWatchlist] = useState(false);
  const [exchange, setExchange] = useState("NSE");
  const [interval, setInterval] = useState("1d");
  const [period, setPeriod] = useState("5y");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const intervalOptions = useIntervalOptions();

  const jobs = useQuery({
    queryKey: ["historify", "jobs"],
    queryFn: () => api.get<JobRow[]>("/historify/jobs?limit=50"),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || data.length === 0) return false;
      return data.some((j) => !TERMINAL_JOB_STATUSES.has(j.status)) ? 3000 : false;
    },
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        exchange,
        interval,
        period: period || null,
      };
      if (useWatchlist) {
        body.watchlist = true;
      } else {
        body.symbols = parseSymbols(symbolsText);
      }
      if (startDate) body.start_date = startDate;
      if (endDate) body.end_date = endDate;
      return api.post<JobDetail>("/historify/jobs/download", body);
    },
    onSuccess: (job) => {
      setError(null);
      setNotice(`Job ${job?.id?.slice(0, 8) ?? ""} queued.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Failed to create download job")),
  });

  const controlMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pause" | "resume" | "cancel" | "retry" }) =>
      api.post<JobDetail>(`/historify/jobs/${id}/${action}`),
    onSuccess: (_d, vars) => {
      setError(null);
      setNotice(`Job ${vars.id.slice(0, 8)}: ${vars.action} sent.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Job action failed")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.del<{ deleted: string }>(`/historify/jobs/${id}`),
    onSuccess: (_d, id) => {
      setError(null);
      setNotice(`Job ${id.slice(0, 8)} cancelled and removed from the active list.`);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Failed to delete job")),
  });

  const parsed = parseSymbols(symbolsText);
  const jobRows = jobs.data ?? [];
  const activeCount = jobRows.filter((j) => !TERMINAL_JOB_STATUSES.has(j.status)).length;

  return (
    <div className="space-y-4">
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Create a download job</CardTitle>
          <CardDescription>
            Jobs run in the backend and stream OHLCV bars into the warehouse. The list refreshes every 3
            seconds while a job is queued, running or paused.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
          >
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="job-symbols">Symbols</Label>
                <Textarea
                  id="job-symbols"
                  value={symbolsText}
                  onChange={(e) => setSymbolsText(e.target.value)}
                  placeholder="RELIANCE, TCS INFY"
                  className="min-h-[90px]"
                  disabled={useWatchlist || createMutation.isPending}
                />
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    className="rounded"
                    checked={useWatchlist}
                    onChange={(e) => setUseWatchlist(e.target.checked)}
                    disabled={createMutation.isPending}
                  />
                  Use the saved watchlist instead ({parsed.length > 0 ? `${parsed.length} typed` : "no symbols typed"})
                </label>
              </div>

              <div className="space-y-2">
                <Label htmlFor="job-exchange">Exchange</Label>
                <Input
                  id="job-exchange"
                  value={exchange}
                  onChange={(e) => setExchange(e.target.value.toUpperCase())}
                  placeholder="NSE"
                  disabled={createMutation.isPending}
                />
              </div>

              <div className="space-y-2">
                <Label>Interval</Label>
                <Select value={interval} onValueChange={setInterval} disabled={createMutation.isPending}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select interval" />
                  </SelectTrigger>
                  <SelectContent>
                    {intervalOptions.map((i) => (
                      <SelectItem key={i} value={i}>
                        {i}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Period</Label>
                <Select value={period} onValueChange={setPeriod} disabled={createMutation.isPending}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select period" />
                  </SelectTrigger>
                  <SelectContent>
                    {PERIODS.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="job-start">Start date</Label>
                  <Input
                    id="job-start"
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    disabled={createMutation.isPending}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="job-end">End date</Label>
                  <Input
                    id="job-end"
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    disabled={createMutation.isPending}
                  />
                </div>
              </div>
            </div>

            <Button
              type="submit"
              disabled={
                createMutation.isPending || (!useWatchlist && parsed.length === 0)
              }
            >
              {createMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Download className="mr-2 h-4 w-4" />
              )}
              Queue download job
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Jobs</CardTitle>
          <CardDescription>
            {jobRows.length === 0
              ? "No jobs yet."
              : `${jobRows.length} job(s) · ${activeCount} active.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {jobs.isLoading ? (
            <TableSkeleton />
          ) : jobRows.length === 0 ? (
            <EmptyState>No jobs yet — queue a download above.</EmptyState>
          ) : (
            <div className="space-y-3">
              {jobRows.map((job) => (
                <div key={job.id} className="rounded-md border">
                  <div className="flex flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted-foreground">
                          {job.id.slice(0, 8)}
                        </span>
                        <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
                        <Badge variant="secondary">{job.exchange}</Badge>
                        <Badge variant="outline">{job.interval}</Badge>
                        {job.period ? <Badge variant="muted">{job.period}</Badge> : null}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {job.completed}/{job.total} done
                        {job.failed > 0 ? ` · ${job.failed} failed` : ""} · created{" "}
                        {shortTs(job.created_at)}
                        {job.start_date ? ` · from ${job.start_date}` : ""}
                        {job.end_date ? ` · to ${job.end_date}` : ""}
                      </p>
                      {job.error ? (
                        <p className="text-xs text-destructive">Error: {job.error}</p>
                      ) : null}
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={controlMutation.isPending}
                        onClick={() => controlMutation.mutate({ id: job.id, action: "pause" })}
                        title="Pause a running job"
                      >
                        <Pause className="mr-1 h-3.5 w-3.5" /> Pause
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={controlMutation.isPending}
                        onClick={() => controlMutation.mutate({ id: job.id, action: "resume" })}
                        title="Resume a paused job"
                      >
                        <Play className="mr-1 h-3.5 w-3.5" /> Resume
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={controlMutation.isPending}
                        onClick={() => controlMutation.mutate({ id: job.id, action: "cancel" })}
                        title="Cancel a job"
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={controlMutation.isPending}
                        onClick={() => controlMutation.mutate({ id: job.id, action: "retry" })}
                        title="Requeue every item of the job and run it again"
                      >
                        <RotateCcw className="mr-1 h-3.5 w-3.5" /> Retry
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(job.id)}
                        title="Cancel the job and drop it from the active list"
                      >
                        <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setExpanded(expanded === job.id ? null : job.id)}
                      >
                        {expanded === job.id ? "Hide details" : "Details"}
                      </Button>
                    </div>
                  </div>

                  {expanded === job.id ? (
                    <JobDetailsPanel jobId={job.id} />
                  ) : null}
                </div>
              ))}
            </div>
          )}

          <p className="mt-3 text-xs text-muted-foreground">
            The backend delete endpoint cancels the job and drops it from the active list; the stored record is
            retained for auditing.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function JobDetailsPanel({ jobId }: { jobId: string }) {
  const detail = useQuery({
    queryKey: ["historify", "job", jobId],
    queryFn: () => api.get<JobDetail>(`/historify/jobs/${jobId}`),
  });

  if (detail.isLoading) return <div className="border-t p-3"><TableSkeleton rows={2} /></div>;
  if (detail.isError || !detail.data) {
    return (
      <div className="border-t p-3">
        <ErrorBanner message={errorMessage(detail.error, "Failed to load job details")} />
      </div>
    );
  }

  const job = detail.data;
  const configSymbols = Array.isArray(job.config?.symbols)
    ? (job.config.symbols as unknown[]).map((s) => String(s))
    : [];

  return (
    <div className="border-t p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium">Job items</span>
        {configSymbols.length > 0 ? (
          <span>· requested: {configSymbols.join(", ")}</span>
        ) : null}
        <span>· period: {job.period ?? "—"}</span>
        <span>
          · {job.start_date ?? "—"} → {job.end_date ?? "—"}
        </span>
      </div>
      {!job.items || job.items.length === 0 ? (
        <EmptyState>No items recorded for this job.</EmptyState>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Symbol</TableHead>
              <TableHead>Exchange</TableHead>
              <TableHead>Interval</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Rows</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {job.items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="font-medium">{item.symbol}</TableCell>
                <TableCell>{item.exchange}</TableCell>
                <TableCell>{item.interval}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums">{fmtCompact(item.rows)}</TableCell>
                <TableCell className="text-xs text-destructive">{item.error ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 5. Query & export                                                          */
/* -------------------------------------------------------------------------- */

function QueryTab() {
  const [symbol, setSymbol] = useState("");
  const [interval, setInterval] = useState("1d");
  const [limit, setLimit] = useState("100");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const intervalOptions = useIntervalOptions();

  const known = useQuery({
    queryKey: ["historify", "status"],
    queryFn: () => api.get<HistorifyStatus>("/historify/status"),
  });
  const watchlist = useQuery({
    queryKey: ["historify", "watchlist"],
    queryFn: () => api.get<WatchlistRow[]>("/historify/watchlist"),
  });

  const sym = symbol.trim().toUpperCase();
  const lim = Math.min(Math.max(Number(limit) || 100, 1), 5000);

  const query = useQuery({
    queryKey: ["historify", "query", sym, interval, lim],
    queryFn: () =>
      api.get<QueryResponse>(
        `/historify/query?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(
          interval,
        )}&limit=${lim}`,
      ),
    enabled: sym.length > 0,
  });

  const suggestions = Array.from(
    new Set([...(known.data?.symbols ?? []), ...(watchlist.data ?? []).map((w) => w.symbol)]),
  );

  const doDownload = async (format: "csv" | "parquet" | "json") => {
    if (!sym) return;
    setBusy(format);
    setDownloadError(null);
    setNotice(null);
    try {
      await downloadBlob(
        `/historify/export?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(
          interval,
        )}&format=${format}&limit=${lim}`,
        `${sym}_${interval}.${format}`,
      );
      setNotice(`${sym} exported as ${format.toUpperCase()}.`);
    } catch (e) {
      setDownloadError(errorMessage(e, `${format.toUpperCase()} export failed for ${sym}`));
    } finally {
      setBusy(null);
    }
  };

  const rows = query.data?.rows ?? [];

  return (
    <div className="space-y-4">
      <ErrorBanner message={downloadError} onDismiss={() => setDownloadError(null)} />
      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Query stored bars</CardTitle>
          <CardDescription>
            Reads the last N OHLCV rows for a symbol and interval straight out of the warehouse.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="q-symbol">Symbol</Label>
              <Input
                id="q-symbol"
                list="historify-symbols"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="RELIANCE"
              />
              <datalist id="historify-symbols">
                {suggestions.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </div>
            <div className="space-y-2">
              <Label>Interval</Label>
              <Select value={interval} onValueChange={setInterval}>
                <SelectTrigger>
                  <SelectValue placeholder="Select interval" />
                </SelectTrigger>
                <SelectContent>
                  {intervalOptions.map((i) => (
                    <SelectItem key={i} value={i}>
                      {i}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="q-limit">Limit</Label>
              <Input
                id="q-limit"
                type="number"
                min={1}
                max={5000}
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={!sym || query.isFetching}>
              {query.isFetching ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Search className="mr-2 h-4 w-4" />
              )}
              Run query
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => doDownload("csv")}
              disabled={!sym || busy !== null}
            >
              {busy === "csv" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="mr-2 h-4 w-4" />
              )}
              Download CSV
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => doDownload("parquet")}
              disabled={!sym || busy !== null}
            >
              {busy === "parquet" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Download className="mr-2 h-4 w-4" />
              )}
              Download Parquet
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => doDownload("json")}
              disabled={!sym || busy !== null}
            >
              {busy === "json" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <FileJson className="mr-2 h-4 w-4" />
              )}
              Download JSON
            </Button>
          </div>

          <p className="mt-3 text-xs text-muted-foreground">
            Exports are fetched with your bearer token and saved locally — the export endpoints are
            authenticated, so a plain link would be rejected. Parquet output additionally requires a parquet
            engine (pyarrow / fastparquet) in the backend environment.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Last {lim} rows</CardTitle>
          <CardDescription>
            {sym ? (
              <>
                {sym} · {interval}
              </>
            ) : (
              "Enter a symbol to run the query."
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!sym ? (
            <EmptyState>Enter a symbol to run the query.</EmptyState>
          ) : query.isLoading ? (
            <TableSkeleton rows={5} />
          ) : query.isError ? (
            <ErrorBanner message={errorMessage(query.error, "Query failed")} />
          ) : rows.length === 0 ? (
            <EmptyState>
              No data yet — nothing stored for {sym} at {interval}.
            </EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                  <TableHead className="text-right">High</TableHead>
                  <TableHead className="text-right">Low</TableHead>
                  <TableHead className="text-right">Close</TableHead>
                  <TableHead className="text-right">Change</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead>Provider</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const change =
                    row.open && Number.isFinite(row.open) && Number.isFinite(row.close)
                      ? ((row.close - row.open) / row.open) * 100
                      : null;
                  return (
                    <TableRow key={`${row.symbol}-${row.exchange}-${row.interval}-${row.ts}`}>
                      <TableCell className="whitespace-nowrap text-xs">{shortTs(row.ts)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(row.open)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(row.high)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(row.low)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(row.close)}</TableCell>
                      <TableCell
                        className={cn(
                          "text-right tabular-nums",
                          change != null ? pctColor(change) : "text-muted-foreground",
                        )}
                      >
                        {change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{fmtCompact(row.volume)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {row.provider ?? "—"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 6. Import                                                                  */
/* -------------------------------------------------------------------------- */

function ImportTab() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [exchange, setExchange] = useState("NSE");
  const [interval, setInterval] = useState("1d");
  const [recordsText, setRecordsText] = useState(SAMPLE_RECORDS);
  const [mode, setMode] = useState("incremental");
  const [error, setError] = useState<string | null>(null);
  const [csvResult, setCsvResult] = useState<ImportResult | null>(null);
  const [jsonResult, setJsonResult] = useState<ImportResult | null>(null);
  const intervalOptions = useIntervalOptions();

  const csvMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a CSV file first");
      const form = new FormData();
      form.append("file", file);
      const params = new URLSearchParams({ exchange, interval });
      const res = await authFetch(`/historify/import/csv?${params.toString()}`, {
        method: "POST",
        body: form,
      });
      return (await res.json()) as ImportResult;
    },
    onSuccess: (result) => {
      setCsvResult(result);
      setError(null);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "CSV import failed")),
  });

  const jsonMutation = useMutation({
    mutationFn: async () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(recordsText);
      } catch {
        throw new Error("Records must be valid JSON");
      }
      if (!Array.isArray(parsed)) {
        throw new Error("Records must be a JSON array of OHLCV objects");
      }
      if (parsed.length === 0) {
        throw new Error("Records array is empty");
      }
      return api.post<ImportResult>("/historify/import", { records: parsed, mode });
    },
    onSuccess: (result) => {
      setJsonResult(result);
      setError(null);
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "JSON import failed")),
  });

  return (
    <div className="space-y-4">
      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Import a CSV file</CardTitle>
            <CardDescription>
              Uploads a CSV of OHLCV rows. The exchange and interval below are applied when the file does not
              carry them.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                csvMutation.mutate();
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="import-file">CSV file</Label>
                <input
                  id="import-file"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-secondary-foreground hover:file:bg-secondary/80"
                />
                {file ? (
                  <p className="text-xs text-muted-foreground">
                    {file.name} · {(file.size / 1024).toFixed(1)} KB
                  </p>
                ) : null}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="import-exchange">Exchange</Label>
                  <Input
                    id="import-exchange"
                    value={exchange}
                    onChange={(e) => setExchange(e.target.value.toUpperCase())}
                    placeholder="NSE"
                    disabled={csvMutation.isPending}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Interval</Label>
                  <Select value={interval} onValueChange={setInterval} disabled={csvMutation.isPending}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select interval" />
                    </SelectTrigger>
                    <SelectContent>
                      {intervalOptions.map((i) => (
                        <SelectItem key={i} value={i}>
                          {i}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <Button type="submit" disabled={!file || csvMutation.isPending}>
                {csvMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-4 w-4" />
                )}
                Upload CSV
              </Button>

              {csvResult ? <ImportSummary result={csvResult} /> : null}
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Import JSON records</CardTitle>
            <CardDescription>
              Posts a JSON array of OHLCV objects. Incremental mode skips bars that already exist; replace mode
              upserts everything.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                jsonMutation.mutate();
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="import-records">Records</Label>
                <Textarea
                  id="import-records"
                  value={recordsText}
                  onChange={(e) => setRecordsText(e.target.value)}
                  className="min-h-[220px] font-mono text-xs"
                  spellCheck={false}
                  disabled={jsonMutation.isPending}
                />
              </div>

              <div className="space-y-2">
                <Label>Mode</Label>
                <Select value={mode} onValueChange={setMode} disabled={jsonMutation.isPending}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="incremental">Incremental</SelectItem>
                    <SelectItem value="replace">Replace (upsert)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button type="submit" disabled={jsonMutation.isPending}>
                {jsonMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-4 w-4" />
                )}
                Import records
              </Button>

              {jsonResult ? <ImportSummary result={jsonResult} /> : null}
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ImportSummary({ result }: { result: ImportResult }) {
  return (
    <div className="rounded-md border bg-muted/40 p-3 text-xs">
      <p className="mb-1 font-medium text-foreground">Import finished</p>
      <p className="text-muted-foreground">
        {result.inserted ?? 0} inserted · {result.skipped ?? 0} skipped · {result.total ?? 0} total
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 7. FNO / symbol metadata                                                   */
/* -------------------------------------------------------------------------- */

function FnoTab() {
  const qc = useQueryClient();
  const [underlying, setUnderlying] = useState("");
  const [expiry, setExpiry] = useState(ALL);
  const [instrumentType, setInstrumentType] = useState(ALL);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [metaSymbol, setMetaSymbol] = useState("");
  const [metaExchange, setMetaExchange] = useState("NSE");
  const [metaType, setMetaType] = useState("EQUITY");
  const [metaUnderlying, setMetaUnderlying] = useState("");
  const [metaExpiry, setMetaExpiry] = useState("");
  const [metaStrike, setMetaStrike] = useState("");
  const [metaLotSize, setMetaLotSize] = useState("1");
  const [metaTickSize, setMetaTickSize] = useState("");
  const [metaBroker, setMetaBroker] = useState("");

  const underlyings = useQuery({
    queryKey: ["historify", "fno", "underlyings"],
    queryFn: () => api.get<string[]>("/historify/fno/underlyings"),
  });

  const expiries = useQuery({
    queryKey: ["historify", "fno", "expiries", underlying],
    queryFn: () =>
      api.get<string[]>(`/historify/fno/expiries?underlying=${encodeURIComponent(underlying)}`),
    enabled: underlying.length > 0,
  });

  const contracts = useQuery({
    queryKey: ["historify", "fno", "contracts", underlying, expiry, instrumentType],
    queryFn: () => {
      const params = new URLSearchParams({ underlying });
      if (expiry !== ALL) params.set("expiry", expiry);
      if (instrumentType !== ALL) params.set("instrument_type", instrumentType);
      return api.get<SymbolMetaRow[]>(`/historify/fno/contracts?${params.toString()}`);
    },
    enabled: underlying.length > 0,
  });

  const upsertMutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        symbol: metaSymbol.trim().toUpperCase(),
        exchange: metaExchange.trim().toUpperCase() || "NSE",
        instrument_type: metaType.trim().toUpperCase() || "EQUITY",
        underlying: metaUnderlying.trim().toUpperCase() || null,
        expiry: metaExpiry.trim() || null,
        strike: metaStrike.trim() === "" ? null : Number(metaStrike),
        lot_size: Number(metaLotSize) || 1,
        tick_size: metaTickSize.trim() === "" ? null : Number(metaTickSize),
        broker: metaBroker.trim() || null,
      };
      return api.post<{ symbol: string; exchange: string; instrument_type: string }>(
        "/historify/symbol-metadata",
        body,
      );
    },
    onSuccess: (res) => {
      setError(null);
      setNotice(`Metadata saved for ${res?.symbol ?? metaSymbol.toUpperCase()}.`);
      setMetaSymbol("");
      setMetaStrike("");
      qc.invalidateQueries({ queryKey: ["historify"] });
    },
    onError: (e) => setError(errorMessage(e, "Failed to save metadata")),
  });

  const underlyingList = underlyings.data ?? [];
  const expiryList = expiries.data ?? [];

  return (
    <div className="space-y-4">
      <ErrorBanner
        message={
          error ??
          (underlyings.isError ? errorMessage(underlyings.error, "Failed to load underlyings") : null)
        }
        onDismiss={() => setError(null)}
      />
      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Contract metadata</CardTitle>
          <CardDescription>
            Underlyings, expiries and contracts stored in the warehouse. Add an entry below to seed the
            catalogue.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2 md:col-span-2">
              <Label>Underlying</Label>
              <Select value={underlying} onValueChange={setUnderlying}>
                <SelectTrigger>
                  <SelectValue placeholder="Select an underlying" />
                </SelectTrigger>
                <SelectContent>
                  {underlyingList.length === 0 ? (
                    <SelectItem value="none" disabled>
                      No underlyings yet
                    </SelectItem>
                  ) : null}
                  {underlyingList.map((u) => (
                    <SelectItem key={u} value={u}>
                      {u}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Expiry</Label>
              <Select value={expiry} onValueChange={setExpiry} disabled={!underlying}>
                <SelectTrigger>
                  <SelectValue placeholder="All expiries" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All expiries</SelectItem>
                  {expiryList.map((e) => (
                    <SelectItem key={e} value={e}>
                      {e}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Instrument</Label>
              <Select value={instrumentType} onValueChange={setInstrumentType} disabled={!underlying}>
                <SelectTrigger>
                  <SelectValue placeholder="All instruments" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All instruments</SelectItem>
                  <SelectItem value="EQUITY">EQUITY</SelectItem>
                  <SelectItem value="FUTURE">FUTURE</SelectItem>
                  <SelectItem value="CE">CE (call)</SelectItem>
                  <SelectItem value="PE">PE (put)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Contracts</CardTitle>
          <CardDescription>
            {underlying
              ? `${underlying}${expiry !== ALL ? ` · ${expiry}` : ""}${
                  instrumentType !== ALL ? ` · ${instrumentType}` : ""
                }`
              : "Select an underlying to list its contracts."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!underlying ? (
            <EmptyState>Select an underlying to list its contracts.</EmptyState>
          ) : contracts.isLoading ? (
            <TableSkeleton />
          ) : contracts.isError ? (
            <ErrorBanner message={errorMessage(contracts.error, "Failed to load contracts")} />
          ) : !contracts.data || contracts.data.length === 0 ? (
            <EmptyState>No contracts stored for {underlying} yet.</EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Instrument</TableHead>
                  <TableHead>Underlying</TableHead>
                  <TableHead>Expiry</TableHead>
                  <TableHead className="text-right">Strike</TableHead>
                  <TableHead className="text-right">Lot</TableHead>
                  <TableHead className="text-right">Tick</TableHead>
                  <TableHead>Broker</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {contracts.data.map((row) => (
                  <TableRow key={`${row.exchange}:${row.symbol}`}>
                    <TableCell className="font-medium">{row.symbol}</TableCell>
                    <TableCell>{row.exchange}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{row.instrument_type}</Badge>
                    </TableCell>
                    <TableCell>{row.underlying ?? "—"}</TableCell>
                    <TableCell>{row.expiry ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.strike != null ? fmt(row.strike) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{row.lot_size ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.tick_size != null ? fmt(row.tick_size) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{row.broker ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add contract metadata</CardTitle>
          <CardDescription>
            Upserts a row in the symbol metadata table. Options contracts use CE / PE as the instrument type.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (metaSymbol.trim()) upsertMutation.mutate();
            }}
          >
            <div className="grid gap-3 md:grid-cols-4">
              <div className="space-y-2">
                <Label htmlFor="meta-symbol">Symbol</Label>
                <Input
                  id="meta-symbol"
                  value={metaSymbol}
                  onChange={(e) => setMetaSymbol(e.target.value)}
                  placeholder="RELIANCE26JAN24500CE"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-exchange">Exchange</Label>
                <Input
                  id="meta-exchange"
                  value={metaExchange}
                  onChange={(e) => setMetaExchange(e.target.value.toUpperCase())}
                  placeholder="NSE"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-type">Instrument type</Label>
                <Input
                  id="meta-type"
                  value={metaType}
                  onChange={(e) => setMetaType(e.target.value.toUpperCase())}
                  placeholder="EQUITY"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-underlying">Underlying</Label>
                <Input
                  id="meta-underlying"
                  value={metaUnderlying}
                  onChange={(e) => setMetaUnderlying(e.target.value.toUpperCase())}
                  placeholder="RELIANCE"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-expiry">Expiry</Label>
                <Input
                  id="meta-expiry"
                  value={metaExpiry}
                  onChange={(e) => setMetaExpiry(e.target.value)}
                  placeholder="2026-01-29"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-strike">Strike</Label>
                <Input
                  id="meta-strike"
                  type="number"
                  step="any"
                  value={metaStrike}
                  onChange={(e) => setMetaStrike(e.target.value)}
                  placeholder="2450"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-lot">Lot size</Label>
                <Input
                  id="meta-lot"
                  type="number"
                  value={metaLotSize}
                  onChange={(e) => setMetaLotSize(e.target.value)}
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-tick">Tick size</Label>
                <Input
                  id="meta-tick"
                  type="number"
                  step="any"
                  value={metaTickSize}
                  onChange={(e) => setMetaTickSize(e.target.value)}
                  placeholder="0.05"
                  disabled={upsertMutation.isPending}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="meta-broker">Broker</Label>
                <Input
                  id="meta-broker"
                  value={metaBroker}
                  onChange={(e) => setMetaBroker(e.target.value)}
                  placeholder="zerodha"
                  disabled={upsertMutation.isPending}
                />
              </div>
            </div>

            <Button type="submit" disabled={!metaSymbol.trim() || upsertMutation.isPending}>
              {upsertMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              Save metadata
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 8. Gap detection                                                           */
/* -------------------------------------------------------------------------- */

function GapsTab() {
  const [symbol, setSymbol] = useState("");
  const [interval, setInterval] = useState("1d");
  const [exchange, setExchange] = useState("NSE");
  const intervalOptions = useIntervalOptions();

  const known = useQuery({
    queryKey: ["historify", "status"],
    queryFn: () => api.get<HistorifyStatus>("/historify/status"),
  });
  const watchlist = useQuery({
    queryKey: ["historify", "watchlist"],
    queryFn: () => api.get<WatchlistRow[]>("/historify/watchlist"),
  });

  const sym = symbol.trim().toUpperCase();

  const gaps = useQuery({
    queryKey: ["historify", "gaps", sym, interval, exchange],
    queryFn: () =>
      api.get<GapsResponse>(
        `/historify/gaps?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(
          interval,
        )}&exchange=${encodeURIComponent(exchange.toUpperCase() || "NSE")}`,
      ),
    enabled: sym.length > 0,
  });

  const suggestions = Array.from(
    new Set([...(known.data?.symbols ?? []), ...(watchlist.data ?? []).map((w) => w.symbol)]),
  );
  const gapRows = gaps.data?.gaps ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Gap detection</CardTitle>
          <CardDescription>
            Reports missing daily bars: any calendar jump greater than one day between two consecutive stored
            timestamps.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="gap-symbol">Symbol</Label>
              <Input
                id="gap-symbol"
                list="historify-gap-symbols"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="RELIANCE"
              />
              <datalist id="historify-gap-symbols">
                {suggestions.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </div>
            <div className="space-y-2">
              <Label>Interval</Label>
              <Select value={interval} onValueChange={setInterval}>
                <SelectTrigger>
                  <SelectValue placeholder="Select interval" />
                </SelectTrigger>
                <SelectContent>
                  {intervalOptions.map((i) => (
                    <SelectItem key={i} value={i}>
                      {i}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gap-exchange">Exchange</Label>
              <Input
                id="gap-exchange"
                value={exchange}
                onChange={(e) => setExchange(e.target.value.toUpperCase())}
                placeholder="NSE"
              />
            </div>
          </div>
          <Button
            className="mt-4"
            variant="outline"
            size="sm"
            onClick={() => gaps.refetch()}
            disabled={!sym || gaps.isFetching}
          >
            {gaps.isFetching ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <CalendarClock className="mr-2 h-4 w-4" />
            )}
            Detect gaps
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Gaps</CardTitle>
          <CardDescription>
            {sym ? `${sym} · ${interval} · ${exchange.toUpperCase() || "NSE"}` : "Enter a symbol first."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!sym ? (
            <EmptyState>Enter a symbol to detect gaps.</EmptyState>
          ) : gaps.isLoading ? (
            <TableSkeleton rows={3} />
          ) : gaps.isError ? (
            <ErrorBanner message={errorMessage(gaps.error, "Gap detection failed")} />
          ) : gapRows.length === 0 ? (
            <EmptyState>
              No data yet — no gaps found for {sym} at {interval}.
            </EmptyState>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>From</TableHead>
                  <TableHead>To</TableHead>
                  <TableHead className="text-right">Missing days</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {gapRows.map((gap) => (
                  <TableRow key={`${gap.from}-${gap.to}`}>
                    <TableCell>{gap.from}</TableCell>
                    <TableCell>{gap.to}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span className={cn("font-medium", pctColor(-gap.gap_days))}>
                        {gap.gap_days}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function HistorifyPage() {
  return (
    <div className="container mx-auto space-y-6 p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-bold">Market Data Warehouse</h1>
          <p className="text-sm text-muted-foreground">
            Historify — a local DuckDB warehouse for OHLCV bars, watchlists, download jobs, F&amp;O contract
            metadata and gap detection.
          </p>
        </div>
        <Badge variant="outline" className="w-fit gap-1.5">
          <Database className="h-3.5 w-3.5" /> DuckDB
        </Badge>
      </header>

      <Tabs defaultValue="overview">
        <TabsList className="grid h-auto w-full grid-cols-2 md:grid-cols-4">
          <TabsTrigger value="overview" className="gap-1.5">
            <Database className="h-4 w-4" /> Overview
          </TabsTrigger>
          <TabsTrigger value="watchlist" className="gap-1.5">
            <ListChecks className="h-4 w-4" /> Watchlist
          </TabsTrigger>
          <TabsTrigger value="catalog" className="gap-1.5">
            <Table2 className="h-4 w-4" /> Catalog
          </TabsTrigger>
          <TabsTrigger value="jobs" className="gap-1.5">
            <Download className="h-4 w-4" /> Jobs
          </TabsTrigger>
          <TabsTrigger value="query" className="gap-1.5">
            <Search className="h-4 w-4" /> Query &amp; export
          </TabsTrigger>
          <TabsTrigger value="import" className="gap-1.5">
            <Upload className="h-4 w-4" /> Import
          </TabsTrigger>
          <TabsTrigger value="fno" className="gap-1.5">
            <Layers className="h-4 w-4" /> F&amp;O metadata
          </TabsTrigger>
          <TabsTrigger value="gaps" className="gap-1.5">
            <CalendarClock className="h-4 w-4" /> Gaps
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab />
        </TabsContent>
        <TabsContent value="watchlist">
          <WatchlistTab />
        </TabsContent>
        <TabsContent value="catalog">
          <CatalogTab />
        </TabsContent>
        <TabsContent value="jobs">
          <JobsTab />
        </TabsContent>
        <TabsContent value="query">
          <QueryTab />
        </TabsContent>
        <TabsContent value="import">
          <ImportTab />
        </TabsContent>
        <TabsContent value="fno">
          <FnoTab />
        </TabsContent>
        <TabsContent value="gaps">
          <GapsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
