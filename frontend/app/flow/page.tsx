"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Plus, Trash2, Upload } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
// Shape-tolerant types. The backend is still being built, so every response is
// normalised through helpers below (wrappers: graphs|items|data|results).
// ---------------------------------------------------------------------------

interface FlowGraphSummary {
  id: string;
  name: string;
  enabled: boolean;
  schedule_cron: string | null;
  last_run: string | null;
  paper_only: boolean | null;
  updated_at: string | null;
}

type Banner = { type: "success" | "error"; msg: string } | null;

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function str(v: unknown): string | null {
  if (typeof v === "string" && v !== "") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return null;
}

function normalizeGraph(raw: unknown): FlowGraphSummary | null {
  const o = asRecord(raw);
  if (!o) return null;
  const id = str(o.id) ?? str(o.graph_id) ?? str(o.graphId);
  if (!id) return null;
  return {
    id,
    name: str(o.name) ?? str(o.title) ?? "—",
    enabled: o.enabled === true,
    schedule_cron:
      str(o.schedule_cron) ?? str(o.scheduleCron) ?? str(o.schedule) ?? str(o.cron) ?? null,
    last_run:
      str(o.last_run) ??
      str(o.lastRun) ??
      str(o.last_run_at) ??
      str(o.lastRunAt) ??
      null,
    paper_only: typeof o.paper_only === "boolean" ? o.paper_only : null,
    updated_at: str(o.updated_at) ?? str(o.updatedAt) ?? null,
  };
}

function normalizeList(raw: unknown): FlowGraphSummary[] {
  const out: FlowGraphSummary[] = [];
  const push = (v: unknown) => {
    const g = normalizeGraph(v);
    if (g) out.push(g);
  };
  if (Array.isArray(raw)) {
    raw.forEach(push);
    return out;
  }
  const o = asRecord(raw);
  if (!o) return [];
  for (const key of ["graphs", "items", "data", "results"]) {
    if (Array.isArray(o[key])) {
      (o[key] as unknown[]).forEach(push);
      return out;
    }
  }
  return [];
}

/** The created/updated record may be returned bare or wrapped ({graph|data|item}). */
function normalizeSingle(raw: unknown): FlowGraphSummary | null {
  const direct = normalizeGraph(raw);
  if (direct) return direct;
  const o = asRecord(raw);
  if (!o) return null;
  for (const key of ["graph", "data", "item", "result"]) {
    const inner = normalizeGraph(o[key]);
    if (inner) return inner;
  }
  return null;
}

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.message} (HTTP ${err.status})`;
  if (err instanceof Error) return err.message;
  return fallback;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FlowListPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [newName, setNewName] = useState("");
  const [banner, setBanner] = useState<Banner>(null);

  const graphsQuery = useQuery({
    queryKey: ["flow-graphs"],
    queryFn: () => api.get<unknown>("/flow/graphs"),
    retry: false,
  });
  const graphs = normalizeList(graphsQuery.data);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["flow-graphs"] });

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      api.post<unknown>("/flow/graphs", {
        name,
        definition: { nodes: [], edges: [] },
        graph: { nodes: [], edges: [] },
        enabled: false,
      }),
    onSuccess: (res) => {
      const g = normalizeSingle(res);
      setBanner({ type: "success", msg: g ? `Created “${g.name}”.` : "Graph created." });
      refresh();
      if (g) router.push(`/flow/${encodeURIComponent(g.id)}`);
    },
    onError: (err) => setBanner({ type: "error", msg: errText(err, "Failed to create graph.") }),
  });

  const toggleMutation = useMutation({
    mutationFn: (vars: { id: string; enabled: boolean }) =>
      api.patch<unknown>(`/flow/graphs/${encodeURIComponent(vars.id)}`, {
        enabled: vars.enabled,
      }),
    onSuccess: () => {
      refresh();
    },
    onError: (err) => setBanner({ type: "error", msg: errText(err, "Failed to update graph.") }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.del<unknown>(`/flow/graphs/${encodeURIComponent(id)}`),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Graph deleted." });
      refresh();
    },
    onError: (err) => setBanner({ type: "error", msg: errText(err, "Failed to delete graph.") }),
  });

  const importMutation = useMutation({
    mutationFn: (parsed: unknown) => api.post<unknown>("/flow/import", parsed),
    onSuccess: (res) => {
      const g = normalizeSingle(res);
      setBanner({
        type: "success",
        msg: g ? `Imported “${g.name}”.` : "Graph imported.",
      });
      refresh();
    },
    onError: (err) => setBanner({ type: "error", msg: errText(err, "Failed to import graph.") }),
  });

  const onImportFile = async (file: File | undefined) => {
    if (!file) return;
    setBanner(null);
    try {
      const text = await file.text();
      const parsed: unknown = JSON.parse(text);
      importMutation.mutate(parsed);
    } catch {
      setBanner({ type: "error", msg: "That file is not valid JSON." });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">Flow Strategies</h1>
          <p className="text-sm text-muted-foreground">
            Visual strategies: market data → indicators → conditions → orders / notifications.
            Graphs validate, dry-run, and execute on a schedule.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void onImportFile(e.target.files?.[0])}
          />
          <Button
            variant="outline"
            onClick={() => fileRef.current?.click()}
            disabled={importMutation.isPending}
          >
            {importMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Import
          </Button>
        </div>
      </div>

      {banner ? (
        <div
          className={cn(
            "rounded-md px-3 py-2 text-sm",
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
          <CardTitle>New graph</CardTitle>
          <CardDescription>
            Creates an empty canvas you can build in the visual editor.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              const name = newName.trim() || "Untitled strategy";
              setBanner(null);
              createMutation.mutate(name);
              setNewName("");
            }}
          >
            <div className="min-w-52 flex-1">
              <Label className="mb-1 block text-xs text-muted-foreground">Name</Label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Untitled strategy"
              />
            </div>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              New graph
            </Button>
          </form>
          {createMutation.isError ? (
            <div className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errText(createMutation.error, "Failed to create graph.")}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Saved graphs</CardTitle>
          <CardDescription>
            {graphsQuery.isLoading
              ? "Loading…"
              : `${graphs.length} graph(s). Toggle enable/disable in place; editing happens in the builder.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {graphsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading graphs…
            </div>
          ) : graphsQuery.isError ? (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errText(graphsQuery.error, "Failed to load graphs. Is the backend running?")}
            </div>
          ) : graphs.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              No flow graphs yet. Create one above or import a JSON backup.
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
                {graphs.map((g) => (
                  <TableRow key={g.id}>
                    <TableCell className="font-medium">
                      <Link
                        href={`/flow/${encodeURIComponent(g.id)}`}
                        className="underline-offset-4 hover:underline"
                      >
                        {g.name}
                      </Link>
                      {g.paper_only === false ? (
                        <Badge variant="negative" className="ml-2">
                          live
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <label className="flex cursor-pointer items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-current"
                          checked={g.enabled}
                          disabled={
                            toggleMutation.isPending && toggleMutation.variables?.id === g.id
                          }
                          onChange={(e) =>
                            toggleMutation.mutate({ id: g.id, enabled: e.target.checked })
                          }
                        />
                        {g.enabled ? (
                          <Badge variant="positive">on</Badge>
                        ) : (
                          <Badge variant="muted">off</Badge>
                        )}
                      </label>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {g.schedule_cron ?? "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {g.last_run ?? "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <Link href={`/flow/${encodeURIComponent(g.id)}`}>Open</Link>
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={deleteMutation.isPending}
                          onClick={() => {
                            const blob = new Blob(
                              [JSON.stringify(g, null, 2)],
                              { type: "application/json" },
                            );
                            void api
                              .get<unknown>(`/flow/export/${encodeURIComponent(g.id)}`)
                              .then((data) => {
                                const url = URL.createObjectURL(
                                  new Blob([JSON.stringify(data, null, 2)], {
                                    type: "application/json",
                                  }),
                                );
                                const a = document.createElement("a");
                                a.href = url;
                                a.download = `flow-${g.id}.json`;
                                a.click();
                                URL.revokeObjectURL(url);
                              })
                              .catch(() => {
                                // Fall back to the row snapshot when the backend has
                                // no export endpoint yet.
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement("a");
                                a.href = url;
                                a.download = `flow-${g.id}.json`;
                                a.click();
                                URL.revokeObjectURL(url);
                              });
                          }}
                        >
                          <Download className="mr-1 h-3.5 w-3.5" />
                          Export
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={deleteMutation.isPending}
                          onClick={() => {
                            if (window.confirm(`Delete “${g.name}”? This cannot be undone.`)) {
                              deleteMutation.mutate(g.id);
                            }
                          }}
                        >
                          <Trash2 className="mr-1 h-3.5 w-3.5" />
                          Delete
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {deleteMutation.isError ? (
            <div className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errText(deleteMutation.error, "Failed to delete graph.")}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
