"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import {
  ArrowLeft,
  Eraser,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Square,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { API_BASE, ApiError, api, getAuthToken } from "@/lib/api";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  Python highlighting via @codemirror/lang-python                           */
/* -------------------------------------------------------------------------- */

const pythonMode = python();

/* -------------------------------------------------------------------------- */
/*  API shapes (shape-tolerant: backend is still being built, see §8.2)       */
/* -------------------------------------------------------------------------- */

interface StrategyScript {
  id: string;
  name?: string | null;
  title?: string | null;
  code?: string | null;
  source?: string | null;
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

function normalizeScriptDetail(raw: unknown): StrategyScript | null {
  const rec = asRecord(raw);
  if (!rec) return null;
  for (const key of ["script", "item"]) {
    const inner = asRecord(rec[key]);
    if (inner) return inner as unknown as StrategyScript;
  }
  const innerData = asRecord(rec["data"]);
  if (innerData) return innerData as unknown as StrategyScript;
  if (typeof rec["id"] === "string" || typeof rec["id"] === "number") {
    return rec as unknown as StrategyScript;
  }
  return null;
}

/** GET /env never returns values — only the names of keys that are set. */
function normalizeEnvKeys(raw: unknown): string[] {
  const out: string[] = [];
  const push = (v: unknown) => {
    if (typeof v === "string") {
      if (v.trim()) out.push(v.trim());
      return;
    }
    const r = asRecord(v);
    if (r) {
      const n = r["name"] ?? r["key"] ?? null;
      if (typeof n === "string" && n.trim()) out.push(n.trim());
    }
  };
  if (Array.isArray(raw)) {
    raw.forEach(push);
    return out;
  }
  const obj = asRecord(raw);
  if (!obj) return [];
  for (const key of ["keys", "set_keys", "setKeys", "env_keys", "names"]) {
    if (Array.isArray(obj[key])) {
      (obj[key] as unknown[]).forEach(push);
      return out;
    }
  }
  for (const key of ["env", "vars", "variables", "data"]) {
    const v = obj[key];
    if (Array.isArray(v)) {
      v.forEach(push);
      return out;
    }
    const m = asRecord(v);
    if (m) return Object.keys(m);
  }
  return [];
}

/** Accept {logs|lines|output} as strings, string arrays, or {message|text|…} objects. */
function normalizeLogLines(raw: unknown): string[] {
  const pick = (v: unknown): string => {
    if (typeof v === "string") return v;
    const r = asRecord(v);
    if (r) {
      for (const k of ["message", "text", "line", "content", "output", "log"]) {
        if (typeof r[k] === "string") return r[k] as string;
      }
      try {
        return JSON.stringify(r);
      } catch {
        return String(r);
      }
    }
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    return "";
  };
  if (typeof raw === "string") return raw.split("\n");
  if (Array.isArray(raw)) return raw.map(pick);
  const obj = asRecord(raw);
  if (!obj) return [];
  for (const key of ["logs", "lines", "output", "data", "entries"]) {
    const v = obj[key];
    if (Array.isArray(v)) return (v as unknown[]).map(pick);
    if (typeof v === "string") return v.split("\n");
  }
  return [];
}

function scriptName(s: StrategyScript): string | null {
  const v = s.name ?? s.title ?? null;
  return typeof v === "string" && v.trim() ? v : null;
}

function scriptCode(s: StrategyScript): string {
  const v = s.code ?? s.source ?? null;
  return typeof v === "string" ? v : "";
}

function scriptEnabled(s: StrategyScript): boolean {
  if (typeof s.enabled === "boolean") return s.enabled;
  if (typeof s.is_enabled === "boolean") return s.is_enabled;
  return false;
}

function scriptSchedule(s: StrategyScript): string {
  const v = s.schedule_cron ?? s.cron ?? s.schedule ?? null;
  return typeof v === "string" ? v : "";
}

function scriptLastRun(s: StrategyScript): string | null {
  const v =
    s.last_run_status ?? s.last_run_state ?? s.last_status ?? s.status ?? s.state ?? null;
  return typeof v === "string" && v.trim() ? v : null;
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

/**
 * The shared `api` helper has no PUT export, so the env save uses a raw fetch
 * with the same auth header and ApiError conventions (same pattern as the
 * settings page Telegram card).
 */
async function putEnv(path: string, body: Record<string, unknown>): Promise<unknown> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "PUT",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(`Cannot reach backend at ${API_BASE} - is it running?`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined;
  return res.json();
}

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function StrategyDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const rawId = params.id;
  const id = typeof rawId === "string" ? rawId : Array.isArray(rawId) ? (rawId[0] ?? "") : "";
  const encId = encodeURIComponent(id);
  const basePath = `/strategy-host/scripts/${encId}`;

  const [banner, setBanner] = useState<Banner>(null);
  const [envBanner, setEnvBanner] = useState<Banner>(null);

  // Editable fields, initialised from the server exactly once per script id.
  const [initFor, setInitFor] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [schedule, setSchedule] = useState("");
  const [enabled, setEnabled] = useState(false);

  // Env editor (values are write-only: inputs are never populated from GET).
  const [envKey, setEnvKey] = useState("");
  const [envValue, setEnvValue] = useState("");

  // Log viewer.
  const [tail, setTail] = useState("200");
  const [clearedLines, setClearedLines] = useState<string[] | null>(null);
  const logBoxRef = useRef<HTMLPreElement>(null);

  const extensions = useMemo(() => [pythonMode], []);

  const scriptQuery = useQuery({
    queryKey: ["strategy-script", id],
    queryFn: () => api.get<unknown>(basePath),
    enabled: id.length > 0,
    retry: false,
  });

  const envQuery = useQuery({
    queryKey: ["strategy-script-env", id],
    queryFn: () => api.get<unknown>(`${basePath}/env`),
    enabled: id.length > 0,
    retry: false,
  });

  const logsQuery = useQuery({
    queryKey: ["strategy-script-logs", id, tail],
    queryFn: () =>
      api.get<unknown>(`${basePath}/logs?tail=${encodeURIComponent(tail.trim() || "200")}`),
    enabled: id.length > 0,
    retry: false,
    refetchInterval: 3000,
  });

  const script = normalizeScriptDetail(scriptQuery.data);
  const envKeys = normalizeEnvKeys(envQuery.data);
  const logLines = normalizeLogLines(logsQuery.data);

  useEffect(() => {
    if (script && initFor !== id) {
      setName(scriptName(script) ?? "");
      setCode(scriptCode(script));
      setSchedule(scriptSchedule(script));
      setEnabled(scriptEnabled(script));
      setInitFor(id);
      setClearedLines(null);
    }
  }, [script, id, initFor]);

  const codeDirty = initFor === id && script !== null && code !== scriptCode(script);

  // "Clear" only hides already-seen lines locally; the next poll repopulates.
  let visibleLines = logLines;
  if (clearedLines) {
    let i = 0;
    while (
      i < visibleLines.length &&
      i < clearedLines.length &&
      visibleLines[i] === clearedLines[i]
    ) {
      i += 1;
    }
    if (i === clearedLines.length) visibleLines = visibleLines.slice(i);
  }
  const visibleText = visibleLines.join("\n");

  useEffect(() => {
    const el = logBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visibleText]);

  const invalidateScript = () =>
    queryClient.invalidateQueries({ queryKey: ["strategy-script", id] });

  const codeMutation = useMutation({
    mutationFn: (value: string) => api.patch<unknown>(basePath, { code: value }),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Code saved." });
      invalidateScript();
      queryClient.invalidateQueries({ queryKey: ["strategy-scripts"] });
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to save code") });
    },
  });

  const settingsMutation = useMutation({
    mutationFn: () =>
      api.patch<unknown>(basePath, {
        name: name.trim(),
        schedule_cron: schedule.trim() ? schedule.trim() : null,
        enabled,
      }),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Settings saved." });
      invalidateScript();
      queryClient.invalidateQueries({ queryKey: ["strategy-scripts"] });
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to save settings") });
    },
  });

  const runMutation = useMutation({
    mutationFn: () => api.post<unknown>(`${basePath}/run`),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Run requested." });
      invalidateScript();
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to start run") });
    },
  });

  const stopMutation = useMutation({
    mutationFn: () => api.post<unknown>(`${basePath}/stop`),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Stop requested." });
      invalidateScript();
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to stop run") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.del<unknown>(basePath),
    onSuccess: () => {
      router.push("/strategies");
    },
    onError: (err) => {
      setBanner({ type: "error", msg: errMessage(err, "Failed to delete script") });
    },
  });

  const envMutation = useMutation({
    mutationFn: (vars: { key: string; value: string }) =>
      putEnv(`${basePath}/env`, { [vars.key]: vars.value }),
    onSuccess: () => {
      setEnvValue("");
      setEnvBanner({ type: "success", msg: "Environment variable saved (value is write-only)." });
      queryClient.invalidateQueries({ queryKey: ["strategy-script-env", id] });
    },
    onError: (err) => {
      setEnvBanner({ type: "error", msg: errMessage(err, "Failed to save variable") });
    },
  });

  const lastRun = script ? scriptLastRun(script) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <Link
            href="/strategies"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to strategies
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold">
              {scriptQuery.isLoading ? "Loading…" : (script && scriptName(script)) || "—"}
            </h1>
            {script ? <Badge variant={statusVariant(lastRun)}>{lastRun ?? "—"}</Badge> : null}
            {script ? (
              <Badge variant={scriptEnabled(script) ? "positive" : "muted"}>
                {scriptEnabled(script) ? "enabled" : "disabled"}
              </Badge>
            ) : null}
          </div>
          <p className="font-mono text-xs text-muted-foreground">{id || "—"}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Run
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={stopMutation.isPending}
            onClick={() => stopMutation.mutate()}
          >
            {stopMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Square className="h-4 w-4" />
            )}
            Stop
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={deleteMutation.isPending}
            onClick={() => {
              if (window.confirm("Delete this script? This cannot be undone.")) {
                deleteMutation.mutate();
              }
            }}
          >
            {deleteMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </Button>
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

      {scriptQuery.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : scriptQuery.isError ? (
        <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {errMessage(scriptQuery.error, "Failed to load script")}
        </div>
      ) : script ? (
        <>
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Code</CardTitle>
                  <CardDescription>
                    Python source, run out-of-process with a minimal ctx object.
                  </CardDescription>
                </div>
                <Button
                  type="button"
                  size="sm"
                  disabled={!codeDirty || codeMutation.isPending}
                  onClick={() => codeMutation.mutate(code)}
                >
                  {codeMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  {codeDirty ? "Save code *" : "Saved"}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <CodeMirror
                value={code}
                height="400px"
                extensions={extensions}
                onChange={(value) => setCode(value)}
                className="overflow-hidden rounded-md border"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Schedule</CardTitle>
              <CardDescription>
                Cron expression for scheduled runs, plus the enabled toggle.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="grid gap-4 md:grid-cols-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!settingsMutation.isPending) settingsMutation.mutate();
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="script-name">Name</Label>
                  <Input
                    id="script-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="my-strategy"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="script-schedule">Schedule (cron)</Label>
                  <Input
                    id="script-schedule"
                    value={schedule}
                    onChange={(e) => setSchedule(e.target.value)}
                    placeholder="*/5 * * * *"
                    className="font-mono"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="script-enabled">Enabled</Label>
                  <div className="flex h-9 items-center gap-2">
                    <input
                      id="script-enabled"
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                      className="h-4 w-4 accent-primary"
                    />
                    <span className="text-sm text-muted-foreground">
                      {enabled ? "Runs on schedule" : "Paused"}
                    </span>
                  </div>
                </div>
                <div className="md:col-span-3">
                  <Button type="submit" size="sm" disabled={settingsMutation.isPending}>
                    {settingsMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Save settings
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Environment variables</CardTitle>
              <CardDescription>
                Encrypted per-script secrets. Values are write-only — the API never returns them,
                only the names of keys that are set.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {envBanner ? (
                <div
                  className={cn(
                    "rounded-md px-4 py-3 text-sm",
                    envBanner.type === "success"
                      ? "bg-positive/10 text-positive"
                      : "bg-destructive/10 text-destructive",
                  )}
                >
                  {envBanner.msg}
                </div>
              ) : null}

              {envQuery.isLoading ? (
                <Skeleton className="h-10 w-full" />
              ) : envQuery.isError ? (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {errMessage(envQuery.error, "Failed to load environment keys")}
                </div>
              ) : envKeys.length === 0 ? (
                <div className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
                  No environment variables set for this script.
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Set keys ({envKeys.length})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {envKeys.map((k) => (
                      <Badge key={k} variant="secondary" className="font-mono">
                        {k}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              <form
                className="grid gap-3 md:grid-cols-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  const key = envKey.trim();
                  if (!key || !envValue || envMutation.isPending) return;
                  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
                    setEnvBanner({
                      type: "error",
                      msg: "Key must match [A-Za-z_][A-Za-z0-9_]*.",
                    });
                    return;
                  }
                  envMutation.mutate({ key, value: envValue });
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="env-key">Key</Label>
                  <Input
                    id="env-key"
                    value={envKey}
                    onChange={(e) => setEnvKey(e.target.value)}
                    placeholder="API_TOKEN"
                    className="font-mono"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="env-value">Value (write-only)</Label>
                  <Input
                    id="env-value"
                    type="password"
                    value={envValue}
                    onChange={(e) => setEnvValue(e.target.value)}
                    placeholder="••••••••"
                    autoComplete="new-password"
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    type="submit"
                    size="sm"
                    disabled={!envKey.trim() || !envValue || envMutation.isPending}
                  >
                    {envMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Save variable
                  </Button>
                </div>
              </form>
              <p className="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-500">
                Saving overwrites the key in place. Blank the value field after saving — values
                are never displayed again.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Logs</CardTitle>
                  <CardDescription>
                    Captured stdout/stderr, polled every 3 s. Never fabricated — empty when the
                    backend has captured nothing.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Label htmlFor="log-tail" className="text-xs text-muted-foreground">
                    Tail
                  </Label>
                  <Input
                    id="log-tail"
                    type="number"
                    min={1}
                    value={tail}
                    onChange={(e) => setTail(e.target.value)}
                    className="h-8 w-24 font-mono"
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={logsQuery.isFetching}
                    onClick={() => logsQuery.refetch()}
                  >
                    <RefreshCw
                      className={cn("h-3.5 w-3.5", logsQuery.isFetching && "animate-spin")}
                    />
                    Refresh
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={visibleLines.length === 0}
                    onClick={() => setClearedLines(logLines)}
                  >
                    <Eraser className="h-3.5 w-3.5" />
                    Clear
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {logsQuery.isLoading ? (
                <Skeleton className="h-40 w-full" />
              ) : logsQuery.isError ? (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {errMessage(logsQuery.error, "Failed to load logs")}
                </div>
              ) : visibleLines.length === 0 ? (
                <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                  No log lines captured yet.
                </div>
              ) : (
                <>
                  <p className="mb-2 text-xs text-muted-foreground">
                    {visibleLines.length} line(s){clearedLines ? " (view cleared)" : ""}
                  </p>
                  <pre
                    ref={logBoxRef}
                    className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-3 font-mono text-xs"
                  >
                    {visibleText}
                  </pre>
                </>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
