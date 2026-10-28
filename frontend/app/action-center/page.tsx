"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ClipboardList,
  Inbox,
  Loader2,
  PlayCircle,
  Power,
  RefreshCw,
  Save,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  Timer,
  Wallet,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, fmt } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ActionCenterItem {
  id: string;
  symbol: string;
  side: string;
  quantity: string;
  price: number;
  status: string;
  order_type: string | null;
  created_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

interface ActionCenterDecision {
  id: string;
  status: string;
}

interface ActionCenterExecution extends ActionCenterDecision {
  order_id: string | null;
  order_ids: (string | null)[];
}

interface AnalyzerStatus {
  analyzer_mode: boolean;
  sandbox_capital: number;
  margin_percent: number;
  square_off_time: string;
  session_reset_time: string;
}

interface AnalyzerForm {
  sandbox_capital: number;
  margin_percent: number;
  square_off_time: string;
  session_reset_time: string;
}

type FilterKey = "all" | "pending" | "approved" | "rejected" | "executed";
type ActionKind = "approve" | "reject" | "execute";

interface ActionVars {
  kind: ActionKind;
  id: string;
  note?: string;
}

interface Banner {
  type: "success" | "error";
  msg: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "executed", label: "Executed" },
];

const STATUS_META: Record<string, { label: string; variant: "outline" | "positive" | "negative" | "default"; className?: string }> = {
  pending: { label: "Pending", variant: "outline", className: "border-amber-500/40 text-amber-600 dark:text-amber-400" },
  approved: { label: "Approved", variant: "positive" },
  rejected: { label: "Rejected", variant: "negative" },
  executed: { label: "Executed", variant: "default" },
};

const HHMM = /^([01]\d|2[0-3]):([0-5]\d)$/;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function errMessage(error: unknown, fallback: string): string {
  const e = error as { message?: string; detail?: string } | null;
  return e?.message || e?.detail || fallback;
}

/** Backend timestamps are naive UTC ISO strings — tag them as UTC before parsing. */
function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const d = new Date(hasTz ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtTime(iso: string | null | undefined): string {
  const d = parseUtc(iso);
  return d ? d.toLocaleString() : "—";
}

function statusMeta(status: string) {
  return (
    STATUS_META[status] ?? {
      label: status ? status.charAt(0).toUpperCase() + status.slice(1) : "Unknown",
      variant: "outline" as const,
    }
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ActionCenterPage() {
  const queryClient = useQueryClient();

  const [filter, setFilter] = useState<FilterKey>("all");
  const [banner, setBanner] = useState<Banner | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectNote, setRejectNote] = useState("");

  // -- Analyzer ------------------------------------------------------------
  const analyzer = useQuery<AnalyzerStatus>({
    queryKey: ["analyzer", "status"],
    queryFn: () => api.get<AnalyzerStatus>("/v1/analyzer"),
    retry: false,
    refetchInterval: 10_000,
  });

  const [form, setForm] = useState<AnalyzerForm>({
    sandbox_capital: 0,
    margin_percent: 0,
    square_off_time: "15:15",
    session_reset_time: "00:00",
  });
  const [formDirty, setFormDirty] = useState(false);

  useEffect(() => {
    const a = analyzer.data;
    if (!a || formDirty) return;
    setForm({
      sandbox_capital: a.sandbox_capital,
      margin_percent: a.margin_percent,
      square_off_time: a.square_off_time,
      session_reset_time: a.session_reset_time,
    });
  }, [analyzer.data, formDirty]);

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      api.post<AnalyzerStatus>("/v1/analyzer/toggle", { enabled }),
    onSuccess: (data) => {
      queryClient.setQueryData(["analyzer", "status"], data);
      setBanner({
        type: "success",
        msg: data.analyzer_mode
          ? "Analyzer (sandbox) mode is ON — orders are simulated against the sandbox account."
          : "Analyzer (sandbox) mode is OFF — normal execution rules apply.",
      });
    },
    onError: (error) => setBanner({ type: "error", msg: errMessage(error, "Failed to toggle analyzer mode") }),
  });

  const configMutation = useMutation({
    mutationFn: (values: AnalyzerForm) =>
      api.patch<AnalyzerStatus>("/v1/analyzer/config", {
        analyzer_sandbox_capital: values.sandbox_capital,
        analyzer_margin_percent: values.margin_percent,
        analyzer_square_off_time: values.square_off_time,
        analyzer_session_reset_time: values.session_reset_time,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["analyzer", "status"], data);
      setFormDirty(false);
      setForm({
        sandbox_capital: data.sandbox_capital,
        margin_percent: data.margin_percent,
        square_off_time: data.square_off_time,
        session_reset_time: data.session_reset_time,
      });
      setBanner({ type: "success", msg: "Analyzer configuration saved." });
    },
    onError: (error) => setBanner({ type: "error", msg: errMessage(error, "Failed to save analyzer configuration") }),
  });

  const analyzerOn = analyzer.data?.analyzer_mode ?? false;

  const saveConfig = () => {
    if (!HHMM.test(form.square_off_time.trim())) {
      setBanner({ type: "error", msg: "Square-off time must be HH:MM (24h)." });
      return;
    }
    if (!HHMM.test(form.session_reset_time.trim())) {
      setBanner({ type: "error", msg: "Session reset time must be HH:MM (24h)." });
      return;
    }
    if (!Number.isFinite(form.sandbox_capital) || form.sandbox_capital <= 0) {
      setBanner({ type: "error", msg: "Sandbox capital must be a positive number." });
      return;
    }
    if (!Number.isFinite(form.margin_percent) || form.margin_percent <= 0 || form.margin_percent > 100) {
      setBanner({ type: "error", msg: "Margin percent must be between 0 and 100." });
      return;
    }
    configMutation.mutate({
      sandbox_capital: form.sandbox_capital,
      margin_percent: form.margin_percent,
      square_off_time: form.square_off_time.trim(),
      session_reset_time: form.session_reset_time.trim(),
    });
  };

  // -- Approval queue ------------------------------------------------------
  const queue = useQuery<ActionCenterItem[]>({
    queryKey: ["action-center", filter],
    queryFn: () =>
      api.get<ActionCenterItem[]>(
        filter === "all" ? "/action-center" : `/action-center?status_filter=${filter}`,
      ),
    retry: false,
    refetchInterval: 5000,
  });

  // Counts for the status tabs (all items). Disabled when the queue already
  // holds every item so we never issue the same request twice.
  const countsQuery = useQuery<ActionCenterItem[]>({
    queryKey: ["action-center", "all"],
    queryFn: () => api.get<ActionCenterItem[]>("/action-center"),
    retry: false,
    refetchInterval: 15_000,
    enabled: filter !== "all",
  });

  const counts = useMemo(() => {
    const source = filter === "all" ? queue.data : countsQuery.data;
    const map: Record<string, number> = { all: 0, pending: 0, approved: 0, rejected: 0, executed: 0 };
    for (const item of source ?? []) {
      map.all += 1;
      if (map[item.status] !== undefined) map[item.status] += 1;
    }
    return map;
  }, [filter, queue.data, countsQuery.data]);

  const actionMutation = useMutation<ActionCenterDecision | ActionCenterExecution, unknown, ActionVars>({
    mutationFn: async (vars: ActionVars) => {
      if (vars.kind === "approve") {
        return api.post<ActionCenterDecision>(`/action-center/${vars.id}/approve`);
      }
      if (vars.kind === "reject") {
        const note = (vars.note ?? "").trim();
        const qs = note ? `?note=${encodeURIComponent(note)}` : "";
        return api.post<ActionCenterDecision>(`/action-center/${vars.id}/reject${qs}`);
      }
      return api.post<ActionCenterExecution>(`/action-center/${vars.id}/execute`);
    },
    onSuccess: (data, vars) => {
      setRejectingId(null);
      setRejectNote("");
      if (vars.kind === "approve") {
        setBanner({ type: "success", msg: "Approved. Review the item and hit Execute to place the order." });
      } else if (vars.kind === "reject") {
        setBanner({ type: "success", msg: "Rejected. The order was discarded and will never be placed." });
      } else {
        const exec = data as ActionCenterExecution;
        const ids = (exec.order_ids ?? []).filter(Boolean);
        setBanner({
          type: "success",
          msg: ids.length
            ? `Order executed (paper). Order id${ids.length > 1 ? "s" : ""}: ${ids.join(", ")}`
            : "Order executed (paper).",
        });
      }
      queryClient.invalidateQueries({ queryKey: ["action-center"] });
    },
    onError: (error, vars) => {
      const what =
        vars.kind === "approve" ? "approve" : vars.kind === "reject" ? "reject" : "execute";
      setBanner({ type: "error", msg: errMessage(error, `Failed to ${what} the item`) });
    },
  });

  const busyId = actionMutation.isPending ? actionMutation.variables?.id : undefined;
  const busyKind = actionMutation.isPending ? actionMutation.variables?.kind : undefined;

  const items = queue.data ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Action Center</h1>
          <p className="text-sm text-muted-foreground">
            Human-in-the-loop approvals for AI-generated orders. Approve first, then execute to place the
            (paper) order.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={analyzerOn ? "positive" : "muted"} className={cn("px-3 py-1 text-sm", analyzerOn && "animate-pulse")}>
            {analyzerOn ? "ANALYZER / SANDBOX MODE ON" : "Analyzer mode off"}
          </Badge>
          <Button variant="outline" size="sm" onClick={() => queue.refetch()} disabled={queue.isFetching}>
            {queue.isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Refresh
          </Button>
        </div>
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

      {/* ---------------- Analyzer mode ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className={cn("h-4 w-4", analyzerOn ? "text-positive" : "text-muted-foreground")} />
                Analyzer Mode
              </CardTitle>
              <CardDescription>
                Sandbox simulation of the full trading day. While it is ON, orders run against a virtual
                account and must never reach a live broker.
              </CardDescription>
            </div>
            <Button
              variant={analyzerOn ? "secondary" : "default"}
              onClick={() => toggleMutation.mutate(!analyzerOn)}
              disabled={toggleMutation.isPending}
            >
              {toggleMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Power className="h-4 w-4" />
              )}
              {analyzerOn ? "Disable analyzer mode" : "Enable analyzer mode"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {analyzer.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : (
            <>
              {analyzerOn && (
                <div className="flex items-start gap-2 rounded-md border border-positive/40 bg-positive/10 px-4 py-3 text-sm text-positive">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    <strong>Analyzer / sandbox mode is active.</strong> Orders are simulated on the paper
                    broker with a virtual cash balance — keep live broker execution disabled while it is on.
                  </span>
                </div>
              )}
              {analyzer.isError && (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {errMessage(analyzer.error, "Could not load analyzer status")}
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatTile
                  icon={Power}
                  label="Analyzer mode"
                  value={analyzerOn ? "ON" : "OFF"}
                  tone={analyzerOn ? "positive" : "muted"}
                />
                <StatTile
                  icon={Wallet}
                  label="Sandbox capital"
                  value={`₹${fmt(analyzer.data?.sandbox_capital, 0)}`}
                  tone="default"
                />
                <StatTile
                  icon={ClipboardList}
                  label="Margin available"
                  value={`${fmt(analyzer.data?.margin_percent)}%`}
                  tone="default"
                />
                <StatTile
                  icon={Timer}
                  label="Square-off / reset"
                  value={`${analyzer.data?.square_off_time ?? "—"} / ${analyzer.data?.session_reset_time ?? "—"}`}
                  tone="default"
                />
              </div>

              <form
                className="grid gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  saveConfig();
                }}
              >
                <div className="grid gap-4 md:grid-cols-4">
                  <div className="space-y-2">
                    <Label htmlFor="sandbox-capital">Sandbox capital (₹)</Label>
                    <Input
                      id="sandbox-capital"
                      type="number"
                      min={1}
                      step={1000}
                      value={Number.isFinite(form.sandbox_capital) ? form.sandbox_capital : ""}
                      onChange={(e) => {
                        setFormDirty(true);
                        setForm((f) => ({ ...f, sandbox_capital: Number(e.target.value) }));
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="margin-percent">Margin percent (%)</Label>
                    <Input
                      id="margin-percent"
                      type="number"
                      min={0}
                      max={100}
                      step={0.5}
                      value={Number.isFinite(form.margin_percent) ? form.margin_percent : ""}
                      onChange={(e) => {
                        setFormDirty(true);
                        setForm((f) => ({ ...f, margin_percent: Number(e.target.value) }));
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="square-off-time">Square-off time (HH:MM)</Label>
                    <Input
                      id="square-off-time"
                      type="text"
                      placeholder="15:15"
                      value={form.square_off_time}
                      onChange={(e) => {
                        setFormDirty(true);
                        setForm((f) => ({ ...f, square_off_time: e.target.value }));
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="session-reset-time">Session reset time (HH:MM)</Label>
                    <Input
                      id="session-reset-time"
                      type="text"
                      placeholder="00:00"
                      value={form.session_reset_time}
                      onChange={(e) => {
                        setFormDirty(true);
                        setForm((f) => ({ ...f, session_reset_time: e.target.value }));
                      }}
                    />
                  </div>
                </div>
                <div className="flex justify-end">
                  <Button type="submit" disabled={configMutation.isPending}>
                    {configMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" />
                    )}
                    Save analyzer config
                  </Button>
                </div>
              </form>
            </>
          )}
        </CardContent>
      </Card>

      {/* ---------------- Approval queue ---------------- */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <ClipboardList className="h-4 w-4" />
                Approval Queue
              </CardTitle>
              <CardDescription>
                Auto-refreshes every 5 seconds so AI proposals show up as soon as they are generated.
              </CardDescription>
            </div>
            <Tabs value={filter} onValueChange={(v) => setFilter(v as FilterKey)}>
              <TabsList>
                {FILTERS.map((f) => (
                  <TabsTrigger key={f.key} value={f.key}>
                    {f.label}
                    {counts[f.key] > 0 && (
                      <span className="ml-1.5 text-[10px] text-muted-foreground">{counts[f.key]}</span>
                    )}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {queue.isError && (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(queue.error, "Could not load the approval queue")}
            </div>
          )}

          {queue.isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-md border border-dashed py-12 text-center">
              <Inbox className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm font-medium">
                {filter === "all" || filter === "pending"
                  ? "No items awaiting approval"
                  : `No ${filter} items`}
              </p>
              <p className="max-w-md text-xs text-muted-foreground">
                When the AI autopilot proposes a trade it lands here for your review. Nothing is placed
                until you approve it.
              </p>
            </div>
          ) : (
            <ul className="space-y-3">
              {items.map((item) => {
                const meta = statusMeta(item.status);
                const isBusy = busyId === item.id;
                const qty = Number(item.quantity);
                const qtyLabel = Number.isFinite(qty) ? String(qty) : item.quantity;
                const notional = Number.isFinite(qty) ? qty * Number(item.price) : Number(item.price);
                return (
                  <li
                    key={item.id}
                    className="rounded-lg border bg-card p-4 transition-colors hover:bg-muted/20"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-base font-semibold">{item.symbol}</span>
                          <Badge
                            variant="outline"
                            className={item.side?.toUpperCase() === "BUY" ? "text-positive" : "text-negative"}
                          >
                            {(item.side ?? "").toUpperCase()}
                          </Badge>
                          <Badge variant={meta.variant} className={meta.className}>
                            {meta.label}
                          </Badge>
                          {item.order_type && (
                            <Badge variant="muted" className="font-mono">
                              {item.order_type}
                            </Badge>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          <span>
                            Qty <span className="tabular-nums text-foreground">{qtyLabel}</span>
                          </span>
                          <span>
                            Price{" "}
                            <span className="tabular-nums text-foreground">₹{fmt(Number(item.price))}</span>
                          </span>
                          <span>
                            Notional{" "}
                            <span className="tabular-nums text-foreground">₹{fmt(notional, 0)}</span>
                          </span>
                          <span>Created {fmtTime(item.created_at)}</span>
                          {item.decided_at && <span>Decided {fmtTime(item.decided_at)}</span>}
                        </div>
                        {item.decision_note && (
                          <p className="rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
                            <span className="font-medium text-foreground">Note:</span> {item.decision_note}
                          </p>
                        )}
                      </div>

                      <div className="flex shrink-0 flex-wrap items-center gap-2">
                        {item.status === "pending" && (
                          <>
                            <Button
                              size="sm"
                              onClick={() => actionMutation.mutate({ kind: "approve", id: item.id })}
                              disabled={isBusy}
                            >
                              {isBusy && busyKind === "approve" ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <ThumbsUp className="h-4 w-4" />
                              )}
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => {
                                setRejectingId(rejectingId === item.id ? null : item.id);
                                setRejectNote("");
                              }}
                              disabled={isBusy}
                            >
                              <ThumbsDown className="h-4 w-4" />
                              Reject
                            </Button>
                          </>
                        )}

                        {item.status === "approved" && (
                          <Button
                            size="sm"
                            onClick={() => actionMutation.mutate({ kind: "execute", id: item.id })}
                            disabled={isBusy}
                          >
                            {isBusy && busyKind === "execute" ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <PlayCircle className="h-4 w-4" />
                            )}
                            Execute
                          </Button>
                        )}

                        {item.status === "executed" && (
                          <span className="inline-flex items-center gap-1 text-xs text-positive">
                            <CheckCircle2 className="h-4 w-4" />
                            Order placed
                          </span>
                        )}
                        {item.status === "rejected" && (
                          <span className="text-xs text-negative">Discarded</span>
                        )}
                      </div>
                    </div>

                    {item.status === "pending" && (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        Step 1 of 2 — approve to unlock execution, then execute to place the paper order.
                      </p>
                    )}
                    {item.status === "approved" && (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        Step 2 of 2 — execute to place the paper order.
                      </p>
                    )}

                    {rejectingId === item.id && (
                      <div className="mt-3 space-y-2 rounded-md border bg-muted/30 p-3">
                        <Label htmlFor={`reject-note-${item.id}`} className="text-xs">
                          Rejection note (optional)
                        </Label>
                        <Textarea
                          id={`reject-note-${item.id}`}
                          value={rejectNote}
                          onChange={(e) => setRejectNote(e.target.value)}
                          placeholder="Why is this order being rejected?"
                          className="min-h-[60px]"
                        />
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setRejectingId(null);
                              setRejectNote("");
                            }}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={isBusy}
                            onClick={() =>
                              actionMutation.mutate({ kind: "reject", id: item.id, note: rejectNote })
                            }
                          >
                            {isBusy && busyKind === "reject" ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <ThumbsDown className="h-4 w-4" />
                            )}
                            Confirm reject
                          </Button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small local presentational helper (kept inside this page file)
// ---------------------------------------------------------------------------

function StatTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Power;
  label: string;
  value: string;
  tone: "positive" | "muted" | "default";
}) {
  return (
    <div className="rounded-md bg-muted/50 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-sm font-semibold tabular-nums",
          tone === "positive" ? "text-positive" : tone === "muted" ? "text-muted-foreground" : "",
        )}
      >
        {value}
      </div>
    </div>
  );
}
