"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  Clock,
  Loader2,
  Plus,
  RefreshCw,
  ShieldAlert,
  Trash2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types (tolerant of both the documented shapes and the live backend shapes)
// ---------------------------------------------------------------------------

interface CalendarHoliday {
  date: string;
  name: string;
  source?: string;
  provisional?: boolean;
}

interface HolidaysResponse {
  year: number;
  count?: number;
  holidays: CalendarHoliday[];
}

interface CalendarStatus {
  exchange?: string;
  is_open?: boolean;
  is_trading_day?: boolean;
  reason?: string;
  session?: string | { state?: string } | null;
  server_time_ist?: string;
  now_ist?: string;
  date_ist?: string;
  next_trading_day?: string | null;
  market_open?: string;
  market_close?: string;
  trading_open?: string;
  trading_close?: string;
  pre_market_start?: string;
  post_market_end?: string;
  timezone?: string;
  holiday?: string | null;
}

interface TimingsResponse {
  exchange?: string;
  timezone?: string;
  open?: string;
  close?: string;
  source?: string;
  market_open?: string;
  market_close?: string;
  pre_market_start?: string;
  post_market_end?: string;
}

interface Banner {
  type: "success" | "error";
  msg: string;
}

const THIS_YEAR = new Date().getFullYear();
const YEARS = [THIS_YEAR - 2, THIS_YEAR - 1, THIS_YEAR, THIS_YEAR + 1, THIS_YEAR + 2];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const ADMIN_ONLY_MSG =
  "Holiday management is admin-only. Sign in with an admin account to add or remove holidays.";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function errMessage(error: unknown, fallback: string): string {
  const e = error as { message?: string; detail?: string } | null;
  return e?.message || e?.detail || fallback;
}

function isForbidden(error: unknown): boolean {
  return (error as ApiError)?.status === 403;
}

/** Backend `session` is a plain string; tolerate a {state} object too. */
function sessionState(session: CalendarStatus["session"]): string | null {
  if (!session) return null;
  if (typeof session === "string") return session;
  return session.state ?? null;
}

function weekdayOf(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { weekday: "short" });
}

function reasonLabel(status: CalendarStatus | undefined): string {
  if (!status) return "—";
  if (status.reason === "holiday") return status.holiday ? `Holiday — ${status.holiday}` : "Holiday";
  if (status.reason === "weekend") return "Weekend";
  return "Trading session";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CalendarPage() {
  const queryClient = useQueryClient();

  const [year, setYear] = useState(THIS_YEAR);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [adminNotice, setAdminNotice] = useState<string | null>(null);
  const [newDate, setNewDate] = useState("");
  const [newName, setNewName] = useState("");

  const status = useQuery<CalendarStatus>({
    queryKey: ["calendar", "status"],
    queryFn: () => api.get<CalendarStatus>("/calendar/status"),
    retry: false,
    refetchInterval: 30_000,
  });

  const holidays = useQuery<HolidaysResponse>({
    queryKey: ["calendar", "holidays", year],
    queryFn: () => api.get<HolidaysResponse>(`/calendar/holidays?year=${year}`),
    retry: false,
  });

  const timings = useQuery<TimingsResponse>({
    queryKey: ["calendar", "timings"],
    queryFn: () => api.get<TimingsResponse>("/calendar/timings"),
    retry: false,
  });

  const addMutation = useMutation<
    { date: string; name: string; source?: string },
    ApiError,
    { date: string; name: string }
  >({
    mutationFn: (vars) => api.post("/calendar/holidays", vars),
    onSuccess: (data) => {
      setNewDate("");
      setNewName("");
      setAdminNotice(null);
      setBanner({ type: "success", msg: `Holiday added: ${data.date} — ${data.name}.` });
      queryClient.invalidateQueries({ queryKey: ["calendar", "holidays"] });
      queryClient.invalidateQueries({ queryKey: ["calendar", "status"] });
    },
    onError: (error) => {
      if (isForbidden(error)) setAdminNotice(ADMIN_ONLY_MSG);
      else setBanner({ type: "error", msg: errMessage(error, "Failed to add holiday") });
    },
  });

  const deleteMutation = useMutation<{ date: string; deleted: boolean }, ApiError, string>({
    mutationFn: (date) => api.del(`/calendar/holidays/${date}`),
    onSuccess: (data) => {
      setAdminNotice(null);
      setBanner({ type: "success", msg: `Holiday removed: ${data.date}.` });
      queryClient.invalidateQueries({ queryKey: ["calendar", "holidays"] });
      queryClient.invalidateQueries({ queryKey: ["calendar", "status"] });
    },
    onError: (error) => {
      if (isForbidden(error)) setAdminNotice(ADMIN_ONLY_MSG);
      else setBanner({ type: "error", msg: errMessage(error, "Failed to remove holiday") });
    },
  });

  const submitAdd = () => {
    const date = newDate.trim();
    const name = newName.trim();
    if (!DATE_RE.test(date)) {
      setBanner({ type: "error", msg: "Date must be YYYY-MM-DD." });
      return;
    }
    if (!name) {
      setBanner({ type: "error", msg: "Holiday name is required." });
      return;
    }
    addMutation.mutate({ date, name });
  };

  const s = status.data;
  const isOpen = s?.is_open ?? false;
  const tradingDay = s ? (s.is_trading_day ?? s.reason === "session") : null;
  const session = sessionState(s?.session);
  const istTime = s?.server_time_ist ?? s?.now_ist ?? null;
  const dateIst = s?.date_ist ?? istTime?.slice(0, 10) ?? "—";
  const openTime = s?.market_open ?? s?.trading_open ?? "—";
  const closeTime = s?.market_close ?? s?.trading_close ?? "—";

  const holidayList = holidays.data?.holidays ?? [];
  const holidayCount = holidays.data?.count ?? holidayList.length;

  const t = timings.data;
  const timingOpen = t?.market_open ?? t?.open ?? "—";
  const timingClose = t?.market_close ?? t?.close ?? "—";

  const deletingDate = deleteMutation.isPending ? deleteMutation.variables : undefined;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Market Calendar</h1>
          <p className="text-sm text-muted-foreground">
            Live NSE trading status, session timings, and the merged seed + admin holiday list.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            status.refetch();
            holidays.refetch();
            timings.refetch();
          }}
          disabled={status.isFetching || holidays.isFetching || timings.isFetching}
        >
          {status.isFetching || holidays.isFetching || timings.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Refresh
        </Button>
      </div>

      {banner && (
        <div
          className={cn(
            "rounded-md px-4 py-3 text-sm",
            banner.type === "success" ? "bg-positive/10 text-positive" : "bg-destructive/10 text-destructive",
          )}
        >
          {banner.msg}
        </div>
      )}

      {/* ---------------- Live status ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <CalendarDays className="h-4 w-4" />
                Market Status
              </CardTitle>
              <CardDescription>
                {s?.exchange ?? "NSE"} · {s?.timezone ?? "Asia/Kolkata (IST, UTC+5:30)"}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {tradingDay !== null && (
                <Badge variant={tradingDay ? "positive" : "muted"}>
                  {tradingDay ? "Trading day" : "Not a trading day"}
                </Badge>
              )}
              <Badge variant={isOpen ? "positive" : "muted"} className={cn(isOpen && "animate-pulse")}>
                {isOpen ? "MARKET OPEN" : "MARKET CLOSED"}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {status.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : status.isError ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(status.error, "Could not load market status")}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <StatusTile label="Session" value={session ?? reasonLabel(s)} />
              <StatusTile label="IST time" value={istTime ?? "—"} />
              <StatusTile label="Date (IST)" value={dateIst} />
              <StatusTile label="Open / Close" value={`${openTime} / ${closeTime}`} />
              <StatusTile label="Next trading day" value={s?.next_trading_day ?? "—"} />
            </div>
          )}
          {!status.isLoading && !status.isError && s?.reason === "holiday" && s.holiday && (
            <p className="mt-3 text-xs text-muted-foreground">
              Closed for {s.holiday}. Next trading day: {s.next_trading_day ?? "—"}.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ---------------- Holidays + Timings ---------------- */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <CalendarDays className="h-4 w-4" />
                  Holidays
                </CardTitle>
                <CardDescription>
                  {holidayCount} holiday{holidayCount === 1 ? "" : "s"} in {year}. Admin rows override
                  the seed list.
                </CardDescription>
              </div>
              <div className="w-32">
                <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
                  <SelectTrigger aria-label="Select year">
                    <SelectValue placeholder="Year" />
                  </SelectTrigger>
                  <SelectContent>
                    {YEARS.map((y) => (
                      <SelectItem key={y} value={String(y)}>
                        {y}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {holidays.isError && (
              <div className="mb-3 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {errMessage(holidays.error, "Could not load holidays")}
              </div>
            )}
            {holidays.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : holidayList.length === 0 ? (
              <p className="rounded-md border border-dashed py-8 text-center text-sm text-muted-foreground">
                No holidays on record for {year}.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Day</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="w-16 text-right">Remove</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {holidayList.map((h) => (
                    <TableRow key={h.date}>
                      <TableCell className="tabular-nums">{h.date}</TableCell>
                      <TableCell className="text-muted-foreground">{weekdayOf(h.date)}</TableCell>
                      <TableCell>
                        {h.name}
                        {h.provisional && (
                          <Badge variant="secondary" className="ml-2">
                            provisional
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={h.source === "admin" ? "secondary" : "outline"}>
                          {h.source ?? "seed"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={`Remove holiday ${h.date}`}
                          onClick={() => deleteMutation.mutate(h.date)}
                          disabled={deletingDate === h.date}
                        >
                          {deletingDate === h.date ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Timings
              </CardTitle>
              <CardDescription>
                {t?.exchange ?? "NSE"} equity sessions · {t?.timezone ?? "Asia/Kolkata (IST, UTC+5:30)"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {timings.isLoading ? (
                <div className="space-y-2">
                  {[0, 1].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : timings.isError ? (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {errMessage(timings.error, "Could not load timings")}
                </div>
              ) : (
                <dl className="space-y-2 text-sm">
                  <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2">
                    <dt className="text-muted-foreground">Market open</dt>
                    <dd className="font-semibold tabular-nums">{timingOpen}</dd>
                  </div>
                  <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2">
                    <dt className="text-muted-foreground">Market close</dt>
                    <dd className="font-semibold tabular-nums">{timingClose}</dd>
                  </div>
                  <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2">
                    <dt className="text-muted-foreground">Pre-market from</dt>
                    <dd className="font-semibold tabular-nums">{t?.pre_market_start ?? "—"}</dd>
                  </div>
                  <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2">
                    <dt className="text-muted-foreground">Post-market until</dt>
                    <dd className="font-semibold tabular-nums">{t?.post_market_end ?? "—"}</dd>
                  </div>
                  {t?.source && (
                    <p className="pt-1 text-xs text-muted-foreground">Source: {t.source}</p>
                  )}
                </dl>
              )}
            </CardContent>
          </Card>

          {/* ---------------- Admin: add / remove ---------------- */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className="h-4 w-4" />
                Manage Holidays
              </CardTitle>
              <CardDescription>Admin-only. Adds or overrides a date; deleting a seed date hides it.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {adminNotice && (
                <div className="flex items-start gap-2 rounded-md border bg-muted/50 px-4 py-3 text-sm text-muted-foreground">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{adminNotice}</span>
                </div>
              )}
              <form
                className="space-y-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  submitAdd();
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="holiday-date">Date (YYYY-MM-DD)</Label>
                  <Input
                    id="holiday-date"
                    type="date"
                    value={newDate}
                    onChange={(e) => setNewDate(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="holiday-name">Name</Label>
                  <Input
                    id="holiday-name"
                    type="text"
                    placeholder="e.g. Diwali — Laxmi Pujan"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    maxLength={128}
                  />
                </div>
                <div className="flex justify-end">
                  <Button type="submit" disabled={addMutation.isPending}>
                    {addMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Plus className="mr-2 h-4 w-4" />
                    )}
                    Add holiday
                  </Button>
                </div>
              </form>
              <p className="text-xs text-muted-foreground">
                To remove a holiday, use the trash icon on its row in the holidays table.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small local presentational helper (kept inside this page file)
// ---------------------------------------------------------------------------

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/50 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}
