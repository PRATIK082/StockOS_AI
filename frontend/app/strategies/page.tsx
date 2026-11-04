"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Plus, Square, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  API shapes (shape-tolerant: backend is still being built, see §8.2)       */
/* -------------------------------------------------------------------------- */

interface StrategyScript {
  id: string;
  name?: string | null;
  title?: string | null;
  code?: string | null;
  enabled?: boolean | null;
  is_enabled?: boolean | null;
  schedule_cron?: string | null;
  cron?: string | null;
  schedule?: string | null;
  last_run_status?: string | null;
  last_run_state?: string | null;
  last_status?: string | null;
  status?: string | null;
  state?: string | null;
  last_run_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                    */
/* -------------------------------------------------------------------------- */

type Banner = { type: "success" | "error"; msg: string } | null;

function errMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

/** Accept either a bare array or an enveloped object (scripts|items|data). */
function normalizeScripts(raw: unknown): StrategyScript[] {
  if (Array.isArray(raw)) return raw as StrategyScript[];
  const obj = asRecord(raw);
  if (!obj) return [];
  for (const key of ["scripts", "items", "data", "results"]) {
    if (Array.isArray(obj[key])) return obj[key] as StrategyScript[];
  }
  return [];
}

function scriptId(s: StrategyScript): string {
  return String(s.id ?? "");
}

function scriptName(s: StrategyScript): string | null {
  const v = s.name ?? s.title ?? null;
  return typeof v === "string" && v.trim() ? v : null;
}

function scriptEnabled(s: StrategyScript): boolean {
  if (typeof s.enabled === "boolean") return s.enabled;
  if (typeof s.is_enabled === "boolean") return s.is_enabled;
  return false;
}

function scriptSchedule(s: StrategyScript): string | null {
  const v = s.schedule_cron ?? s.cron ?? s.schedule ?? null;
  return typeof v === "string" && v.trim() ? v : null;
}

function scriptLastRun(s: StrategyScript): string | null {
  const v =
    s.last_run_status ?? s.last_run_state ?? s.last_status ?? s.status ?? s.state ?? null;
  return typeof v === "string" && v.trim() ? v : null;
}

function scriptLastRunAt(s: StrategyScript): string | null {
  return typeof s.last_run_at === "string" && s.last_run_at.trim() ? s.last_run_at : null;
}

function statusVariant(
  s: string | null,
): "positive" | "negative" | "muted" | "secondary" {
  if (!s) return "muted";
  const v = s.toLowerCase();
  if (["running", "ok", "success", "succeeded", "completed", "done"].includes(v))
    return "positive";
  if (["failed", "error", "errored", "timeout", "timed_out", "killed"].includes(v))
    return "negative";
  if (["stopped", "idle", "disabled", "pending", "queued", "scheduled"].includes(v))
    return "muted";
  return "secondary";
}

const NEW_SCRIPT_TEMPLATE = `# New strategy — runs out-of-process with a minimal "ctx" object.
# Available: ctx.history(symbol, interval, period), ctx.place_order(...), ctx.log(...)
def main(ctx):
    ctx.log("hello from strategy")
`;

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function StrategiesPage() {
  const queryClient = useQueryClient();
  const [banner, setBanner] = useState<Banner>(null);
  const [newName, setNewName] = useState("");
  const [pending, setPending] = useState<{ kind: string; id: string } | null>(null);

  const scriptsQuery = useQuery({
    queryKey: ["strategy-scripts"],
    queryFn: () => api.get<unknown>("/strategy-host/scripts"),
    retry: false,
  });

  const scripts = normalizeScripts(scriptsQuery.data);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["strategy-scripts"] });

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      api.post<unknown>("/strategy-host/scripts", {
        name,
        code: NEW_SCRIPT_TEMPLATE,
        enabled: false,
      }),
    onSuccess: () => {
      setNewName("");
      setBanner({ type: "success", msg: "Script created." });
      invalidate();
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to create script") });
    },
  });

  const runMutation = useMutation({
    mutationFn: (id: string) =>
      api.post<unknown>(`/strategy-host/scripts/${encodeURIComponent(id)}/run`),
    onMutate: (id) => setPending({ kind: "run", id }),
    onSettled: () => setPending(null),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Run requested." });
      invalidate();
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to start run") });
    },
  });

  const stopMutation = useMutation({
    mutationFn: (id: string) =>
      api.post<unknown>(`/strategy-host/scripts/${encodeURIComponent(id)}/stop`),
    onMutate: (id) => setPending({ kind: "stop", id }),
    onSettled: () => setPending(null),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Stop requested." });
      invalidate();
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to stop run") });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (s: StrategyScript) =>
      api.patch<unknown>(`/strategy-host/scripts/${encodeURIComponent(scriptId(s))}`, {
        enabled: !scriptEnabled(s),
      }),
    onMutate: (s) => setPending({ kind: "toggle", id: scriptId(s) }),
    onSettled: () => setPending(null),
    onSuccess: () => invalidate(),
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to update script") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api.del<unknown>(`/strategy-host/scripts/${encodeURIComponent(id)}`),
    onMutate: (id) => setPending({ kind: "delete", id }),
    onSettled: () => setPending(null),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Script deleted." });
      invalidate();
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to delete script") });
    },
  });

  const isBusy = (kind: string, id: string) =>
    pending !== null && pending.kind === kind && pending.id === id;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Strategies</h1>
          <p className="text-sm text-muted-foreground">
            User-written Python strategies, run out-of-process on a schedule. Paper-only in v1.
          </p>
        </div>
      </div>

      {banner ? (
        <div
          className={cn(
            "rounded-md px-4 py-3 text-sm",
            banner.type === "success"
              ? "bg-positive/10 text-positive"
              : "bg-destructive/10 text-destructive",
          )}
        >
          {banner.msg}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>New script</CardTitle>
          <CardDescription>
            Creates a disabled script with a starter template — open it to edit, schedule and run.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              const name = newName.trim();
              if (!name || createMutation.isPending) return;
              createMutation.mutate(name);
            }}
          >
            <div className="flex-1 space-y-2">
              <Label htmlFor="new-script-name">Name</Label>
              <Input
                id="new-script-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. rsi-pullback"
                required
              />
            </div>
            <Button type="submit" disabled={!newName.trim() || createMutation.isPending}>
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              New script
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scripts</CardTitle>
          <CardDescription>
            {scriptsQuery.isLoading ? "Loading…" : `${scripts.length} script(s).`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {scriptsQuery.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : scriptsQuery.isError ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(scriptsQuery.error, "Failed to load scripts")}
            </div>
          ) : scripts.length === 0 ? (
            <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
              No strategy scripts yet. Create one above to get started.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead>Schedule</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scripts.map((s) => {
                  const id = scriptId(s);
                  const name = scriptName(s);
                  const enabled = scriptEnabled(s);
                  const schedule = scriptSchedule(s);
                  const lastRun = scriptLastRun(s);
                  const lastRunAt = scriptLastRunAt(s);
                  return (
                    <TableRow key={id}>
                      <TableCell className="font-medium">
                        <Link
                          href={`/strategies/${encodeURIComponent(id)}`}
                          className="text-primary hover:underline"
                        >
                          {name ?? "—"}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant={enabled ? "positive" : "muted"}>
                          {enabled ? "enabled" : "disabled"}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{schedule ?? "—"}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <Badge variant={statusVariant(lastRun)} className="w-fit">
                            {lastRun ?? "—"}
                          </Badge>
                          {lastRunAt ? (
                            <span className="text-[11px] text-muted-foreground">{lastRunAt}</span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={runMutation.isPending && runMutation.variables === id}
                            onClick={() => runMutation.mutate(id)}
                            title="Run now"
                          >
                            {isBusy("run", id) ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Play className="h-3.5 w-3.5" />
                            )}
                            Run
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={stopMutation.isPending && stopMutation.variables === id}
                            onClick={() => stopMutation.mutate(id)}
                            title="Stop running script"
                          >
                            {isBusy("stop", id) ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Square className="h-3.5 w-3.5" />
                            )}
                            Stop
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={enabled ? "outline" : "secondary"}
                            disabled={isBusy("toggle", id)}
                            onClick={() => toggleMutation.mutate(s)}
                            title={enabled ? "Disable schedule" : "Enable schedule"}
                          >
                            {isBusy("toggle", id) ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : null}
                            {enabled ? "Disable" : "Enable"}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            disabled={isBusy("delete", id)}
                            onClick={() => {
                              if (
                                window.confirm(
                                  `Delete script "${name ?? id}"? This cannot be undone.`,
                                )
                              ) {
                                deleteMutation.mutate(id);
                              }
                            }}
                            title="Delete script"
                          >
                            {isBusy("delete", id) ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                          </Button>
                        </div>
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
