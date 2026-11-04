"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowLeft,
  Download,
  FlaskConical,
  Loader2,
  Play,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
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
// Shape-tolerant contract helpers (backend is built in parallel — accept key
// variants everywhere and render "—" for anything missing).
// ---------------------------------------------------------------------------

const NODE_TYPES = ["market_data", "indicator", "condition", "order", "notification"] as const;
type NodeTypeName = (typeof NODE_TYPES)[number];

interface BackendNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
}

interface BackendEdge {
  from: string;
  to: string;
}

interface FlowNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  params: Record<string, unknown>;
}

type CanvasNode = Node<FlowNodeData>;
type CanvasEdge = Edge;

interface Finding {
  severity: string;
  message: string;
  node: string | null;
}

interface StepResult {
  step: string;
  status: string;
  detail: string | null;
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

function paramText(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "";
  }
}

function firstArray(o: Record<string, unknown>, keys: string[]): unknown[] {
  for (const k of keys) {
    if (Array.isArray(o[k])) return o[k] as unknown[];
  }
  return [];
}

function normalizeBackendNode(raw: unknown, fallbackId: string): BackendNode | null {
  const o = asRecord(raw);
  if (!o) return null;
  const id = str(o.id) ?? str(o.node_id) ?? str(o.nodeId) ?? fallbackId;
  const type =
    str(o.type) ?? str(o.node_type) ?? str(o.nodeType) ?? str(o.kind) ?? "market_data";
  const params =
    asRecord(o.params) ?? asRecord(o.config) ?? asRecord(o.data) ?? asRecord(o.props) ?? {};
  const pos = asRecord(o.position) ?? null;
  const x =
    typeof o.x === "number"
      ? o.x
      : pos && typeof pos.x === "number"
        ? (pos.x as number)
        : null;
  const y =
    typeof o.y === "number"
      ? o.y
      : pos && typeof pos.y === "number"
        ? (pos.y as number)
        : null;
  return { id, type, params, ...(x != null && y != null ? { x, y } : {}) } as BackendNode & {
    x?: number;
    y?: number;
  };
}

function normalizeBackendEdge(raw: unknown): BackendEdge | null {
  const o = asRecord(raw);
  if (!o) return null;
  const from = str(o.from) ?? str(o.source) ?? str(o.src) ?? str(o.from_id);
  const to = str(o.to) ?? str(o.target) ?? str(o.dst) ?? str(o.to_id);
  if (!from || !to) return null;
  return { from, to };
}

function toCanvasNode(n: BackendNode, index: number): CanvasNode {
  const extra = n as BackendNode & { x?: number; y?: number };
  return {
    id: n.id,
    type: "default",
    position: {
      x: typeof extra.x === "number" ? extra.x : 60 + (index % 3) * 240,
      y: typeof extra.y === "number" ? extra.y : 60 + Math.floor(index / 3) * 150,
    },
    data: {
      label: `${n.type} · ${n.id}`,
      nodeType: n.type,
      params: { ...n.params },
    },
  };
}

function toBackendNodes(nodes: CanvasNode[]): BackendNode[] {
  return nodes.map((n) => ({
    id: n.id,
    type: typeof n.data?.nodeType === "string" ? n.data.nodeType : "market_data",
    params: { ...(n.data?.params ?? {}) },
  }));
}

function toBackendEdges(edges: CanvasEdge[]): BackendEdge[] {
  return edges
    .filter((e) => e.source && e.target)
    .map((e) => ({ from: e.source, to: e.target }));
}

function normalizeFindings(raw: unknown): Finding[] {
  const arr = Array.isArray(raw) ? raw : firstArray(asRecord(raw) ?? {}, [
    "findings",
    "errors",
    "issues",
    "results",
    "violations",
    "problems",
  ]);
  const out: Finding[] = [];
  for (const item of arr) {
    if (typeof item === "string") {
      out.push({ severity: "error", message: item, node: null });
      continue;
    }
    const o = asRecord(item);
    if (!o) continue;
    out.push({
      severity:
        str(o.severity) ?? str(o.level) ?? str(o.kind) ?? str(o.type) ?? "error",
      message:
        str(o.message) ?? str(o.detail) ?? str(o.text) ?? str(o.error) ?? JSON.stringify(o),
      node: str(o.node_id) ?? str(o.nodeId) ?? str(o.node) ?? null,
    });
  }
  return out;
}

function normalizeSteps(raw: unknown): StepResult[] {
  const arr = Array.isArray(raw) ? raw : firstArray(asRecord(raw) ?? {}, [
    "step_results",
    "stepResults",
    "steps",
    "results",
    "data",
  ]);
  const out: StepResult[] = [];
  for (const item of arr) {
    const o = asRecord(item);
    if (!o) {
      if (typeof item === "string") out.push({ step: "—", status: "—", detail: item });
      continue;
    }
    const detailRaw =
      o.detail ?? o.message ?? o.output ?? o.value ?? o.result ?? o.data ?? null;
    out.push({
      step:
        str(o.step) ??
        str(o.node_id) ??
        str(o.nodeId) ??
        str(o.node) ??
        str(o.name) ??
        str(o.id) ??
        "—",
      status:
        str(o.status) ?? str(o.state) ?? str(o.result) ?? (o.ok === true ? "ok" : o.ok === false ? "failed" : "—"),
      detail:
        detailRaw == null
          ? null
          : typeof detailRaw === "string"
            ? detailRaw
            : (() => {
                try {
                  return JSON.stringify(detailRaw);
                } catch {
                  return "—";
                }
              })(),
    });
  }
  return out;
}

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.message} (HTTP ${err.status})`;
  if (err instanceof Error) return err.message;
  return fallback;
}

// ---------------------------------------------------------------------------
// Per-node-type property fields (stored into node params; unknown keys kept).
// ---------------------------------------------------------------------------

interface FieldSpec {
  key: string;
  label: string;
  kind: "text" | "number" | "select";
  placeholder?: string;
  options?: string[];
}

const PARAM_FIELDS: Record<string, FieldSpec[]> = {
  market_data: [
    { key: "symbol", label: "Symbol", kind: "text", placeholder: "RELIANCE" },
    { key: "interval", label: "Interval", kind: "select", options: ["1m", "5m", "15m", "1h", "1d", "1wk"] },
    { key: "period", label: "Period", kind: "select", options: ["1mo", "3mo", "6mo", "1y", "2y", "5y"] },
  ],
  indicator: [
    { key: "indicator", label: "Indicator", kind: "select", options: ["sma", "ema", "rsi", "macd", "bollinger", "atr", "stochastic"] },
    { key: "window", label: "Window / period", kind: "number", placeholder: "14" },
    { key: "symbol", label: "Symbol (blank = upstream)", kind: "text", placeholder: "AAPL" },
  ],
  condition: [
    { key: "left", label: "Left operand", kind: "text", placeholder: "rsi_14" },
    { key: "operator", label: "Operator", kind: "select", options: [">", "<", ">=", "<=", "==", "!=", "crosses_above", "crosses_below"] },
    { key: "right", label: "Right operand", kind: "text", placeholder: "70" },
  ],
  order: [
    { key: "symbol", label: "Symbol", kind: "text", placeholder: "RELIANCE" },
    { key: "side", label: "Side", kind: "select", options: ["BUY", "SELL"] },
    { key: "quantity", label: "Quantity", kind: "number", placeholder: "1" },
    { key: "order_type", label: "Order type", kind: "select", options: ["MARKET", "LIMIT"] },
    { key: "price", label: "Limit price (LIMIT only)", kind: "number", placeholder: "" },
  ],
  notification: [
    { key: "channel", label: "Channel", kind: "select", options: ["ui", "telegram", "email"] },
    { key: "message", label: "Message", kind: "text", placeholder: "RSI crossed above 70" },
  ],
};

const TYPE_HINTS: Record<string, string> = {
  market_data: "Pulls OHLCV candles for a symbol via the market-data service.",
  indicator: "Runs an indicator function (SMA/EMA/RSI/MACD/…) over upstream data.",
  condition: "Pure expression over a whitelisted operator set — no user code is evaluated.",
  order: "Places orders through the orders service (paper broker default; live needs approval).",
  notification: "Writes to the alert hook when present, else logs.",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FlowBuilderPage() {
  const params = useParams();
  const id = decodeURIComponent((params.id as string) || "");
  const queryClient = useQueryClient();
  const idRef = useRef(0);

  const [name, setName] = useState("");
  const [schedule, setSchedule] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [paperOnly, setPaperOnly] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [banner, setBanner] = useState<Banner>(null);
  const hydratedFor = useRef<string | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>([]);

  const detailQuery = useQuery({
    queryKey: ["flow-graph", id],
    queryFn: () => api.get<unknown>(`/flow/graphs/${encodeURIComponent(id)}`),
    retry: false,
    enabled: id.length > 0,
  });

  // Hydrate local editor state from the fetched record (once per graph id).
  useEffect(() => {
    if (!detailQuery.data || hydratedFor.current === id) return;
    const root = asRecord(detailQuery.data) ?? {};
    const rec = asRecord(root.graph) ?? asRecord(root.data) ?? asRecord(root.item) ?? root;
    setName(str(rec.name) ?? str(rec.title) ?? "Untitled strategy");
    setSchedule(
      str(rec.schedule_cron) ?? str(rec.scheduleCron) ?? str(rec.schedule) ?? str(rec.cron) ?? "",
    );
    setEnabled(rec.enabled === true);
    setPaperOnly(rec.paper_only !== false);

    const def =
      asRecord(rec.definition) ??
      asRecord(rec.graph) ??
      (Array.isArray(rec.nodes) ? rec : null) ??
      {};
    const rawNodes = firstArray(def, ["nodes", "items"]);
    const rawEdges = firstArray(def, ["edges", "links"]);
    const bn = rawNodes
      .map((n, i) => normalizeBackendNode(n, `n${i + 1}`))
      .filter((n): n is BackendNode => n !== null);
    const be = rawEdges
      .map(normalizeBackendEdge)
      .filter((e): e is BackendEdge => e !== null);
    setNodes(bn.map((n, i) => toCanvasNode(n, i)));
    setEdges(
      be.map((e, i) => ({
        id: `e${i + 1}`,
        source: e.from,
        target: e.to,
      })),
    );
    idRef.current = bn.length;
    hydratedFor.current = id;
  }, [detailQuery.data, id, setNodes, setEdges]);

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge(c, eds)),
    [setEdges],
  );

  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  const inlineGraph = useCallback(
    () => ({ nodes: toBackendNodes(nodes), edges: toBackendEdges(edges) }),
    [nodes, edges],
  );

  const saveMutation = useMutation({
    mutationFn: () =>
      api.patch<unknown>(`/flow/graphs/${encodeURIComponent(id)}`, {
        name: name.trim() || "Untitled strategy",
        definition: inlineGraph(),
        graph: inlineGraph(),
        schedule_cron: schedule.trim() || null,
        schedule: schedule.trim() || null,
        enabled,
        paper_only: paperOnly,
      }),
    onSuccess: () => {
      setBanner({ type: "success", msg: "Graph saved." });
      queryClient.invalidateQueries({ queryKey: ["flow-graph", id] });
      queryClient.invalidateQueries({ queryKey: ["flow-graphs"] });
    },
    onError: (err) => setBanner({ type: "error", msg: errText(err, "Failed to save graph.") }),
  });

  const validateMutation = useMutation({
    mutationFn: () =>
      api.post<unknown>("/flow/validate", {
        graph_id: id,
        graph: inlineGraph(),
        inline_graph: inlineGraph(),
      }),
  });

  const dryRunMutation = useMutation({
    mutationFn: () =>
      api.post<unknown>("/flow/run", {
        graph_id: id,
        graph: inlineGraph(),
        inline_graph: inlineGraph(),
        mode: "dry_run",
      }),
  });

  const addNode = (t: NodeTypeName) => {
    idRef.current += 1;
    const nid = `n${Date.now().toString(36)}${idRef.current}`;
    const defaults: Record<string, Record<string, unknown>> = {
      market_data: { symbol: "", interval: "1d", period: "6mo" },
      indicator: { indicator: "sma", window: 14, symbol: "" },
      condition: { left: "", operator: ">", right: "" },
      order: { symbol: "", side: "BUY", quantity: 1, order_type: "MARKET", price: "" },
      notification: { channel: "ui", message: "" },
    };
    const canvas: CanvasNode = {
      id: nid,
      type: "default",
      position: { x: 60 + (nodes.length % 3) * 240, y: 60 + Math.floor(nodes.length / 3) * 150 },
      data: { label: `${t} · ${nid}`, nodeType: t, params: { ...(defaults[t] ?? {}) } },
    };
    setNodes((ns) => [...ns, canvas]);
    setSelectedId(nid);
  };

  const updateParam = (nodeId: string, key: string, value: string, kind: FieldSpec["kind"]) => {
    setNodes((ns) =>
      ns.map((n) => {
        if (n.id !== nodeId) return n;
        const next = { ...(n.data.params ?? {}) };
        if (value === "") {
          delete next[key];
        } else if (kind === "number") {
          const num = Number(value);
          next[key] = Number.isFinite(num) ? num : value;
        } else {
          next[key] = value;
        }
        return { ...n, data: { ...n.data, params: next } };
      }),
    );
  };

  const updateNodeType = (nodeId: string, t: string) => {
    setNodes((ns) =>
      ns.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, nodeType: t, label: `${t} · ${n.id}` } }
          : n,
      ),
    );
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    setNodes((ns) => ns.filter((n) => n.id !== selectedId));
    setEdges((es) => es.filter((e) => e.source !== selectedId && e.target !== selectedId));
    setSelectedId(null);
  };

  const exportGraph = () => {
    void api
      .get<unknown>(`/flow/export/${encodeURIComponent(id)}`)
      .then((data) => {
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = `flow-${id}.json`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((err: unknown) => {
        // Fall back to the current canvas when the backend has no export yet.
        if (err instanceof ApiError && err.status === 404) {
          const url = URL.createObjectURL(
            new Blob([JSON.stringify({ name, definition: inlineGraph() }, null, 2)], {
              type: "application/json",
            }),
          );
          const a = document.createElement("a");
          a.href = url;
          a.download = `flow-${id}.json`;
          a.click();
          URL.revokeObjectURL(url);
          return;
        }
        setBanner({ type: "error", msg: errText(err, "Failed to export graph.") });
      });
  };

  const findings = validateMutation.data ? normalizeFindings(validateMutation.data) : null;
  const steps = dryRunMutation.data ? normalizeSteps(dryRunMutation.data) : null;
  const fields = selected
    ? (PARAM_FIELDS[selected.data.nodeType] ?? PARAM_FIELDS.market_data ?? [])
    : [];

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" asChild>
            <Link href="/flow">
              <ArrowLeft className="mr-1 h-4 w-4" /> Back
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold">Flow builder</h1>
            <p className="font-mono text-xs text-muted-foreground">{id || "—"}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            disabled={validateMutation.isPending}
            onClick={() => validateMutation.mutate()}
          >
            {validateMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ShieldCheck className="mr-2 h-4 w-4" />
            )}
            Validate
          </Button>
          <Button
            variant="outline"
            disabled={dryRunMutation.isPending}
            onClick={() => dryRunMutation.mutate()}
          >
            {dryRunMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <FlaskConical className="mr-2 h-4 w-4" />
            )}
            Dry-run
          </Button>
          <Button variant="outline" onClick={exportGraph}>
            <Download className="mr-2 h-4 w-4" />
            Export
          </Button>
          <Button disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Save
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

      {detailQuery.isError ? (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {errText(detailQuery.error, "Failed to load graph.")}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[220px_1fr_300px]">
        {/* Palette */}
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Palette</CardTitle>
            <CardDescription>Click to add a node, then drag to connect.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {NODE_TYPES.map((t) => (
              <Button
                key={t}
                variant="outline"
                size="sm"
                className="w-full justify-start"
                onClick={() => addNode(t)}
              >
                <Plus className="mr-2 h-3.5 w-3.5" />
                {t}
              </Button>
            ))}
            <p className="pt-1 text-[11px] text-muted-foreground">
              DAG only in v1 — cycles are rejected by validation.
            </p>
          </CardContent>
        </Card>

        {/* Canvas */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Canvas{" "}
              <span className="text-xs font-normal text-muted-foreground">
                {nodes.length} node(s) · {edges.length} edge(s)
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[560px] w-full rounded-md border border-border">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={(_, node) => setSelectedId((node as CanvasNode).id)}
                onPaneClick={() => setSelectedId(null)}
                deleteKeyCode={["Backspace", "Delete"]}
                fitView
              >
                <Background />
                <Controls />
                <MiniMap />
              </ReactFlow>
            </div>
          </CardContent>
        </Card>

        {/* Property panel + settings */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Properties</CardTitle>
              <CardDescription>
                {selected ? `Node ${selected.id}` : "Select a node on the canvas."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {!selected ? (
                <p className="text-sm text-muted-foreground">
                  Click a node to edit its parameters.
                </p>
              ) : (
                <>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">Node type</Label>
                    <select
                      className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                      value={selected.data.nodeType}
                      onChange={(e) => updateNodeType(selected.id, e.target.value)}
                    >
                      {NODE_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                      {!NODE_TYPES.includes(selected.data.nodeType as NodeTypeName) ? (
                        <option value={selected.data.nodeType}>
                          {selected.data.nodeType} (unknown)
                        </option>
                      ) : null}
                    </select>
                  </div>
                  {TYPE_HINTS[selected.data.nodeType] ? (
                    <p className="text-[11px] text-muted-foreground">
                      {TYPE_HINTS[selected.data.nodeType]}
                    </p>
                  ) : (
                    <div className="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-500">
                      Unknown node type — validation will reject it.
                    </div>
                  )}
                  {fields.map((f) =>
                    f.kind === "select" ? (
                      <div key={f.key}>
                        <Label className="mb-1 block text-xs text-muted-foreground">
                          {f.label}
                        </Label>
                        <select
                          className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
                          value={paramText(selected.data.params[f.key])}
                          onChange={(e) =>
                            updateParam(selected.id, f.key, e.target.value, f.kind)
                          }
                        >
                          <option value="">—</option>
                          {(f.options ?? []).map((o) => (
                            <option key={o} value={o}>
                              {o}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <div key={f.key}>
                        <Label className="mb-1 block text-xs text-muted-foreground">
                          {f.label}
                        </Label>
                        <Input
                          type={f.kind === "number" ? "number" : "text"}
                          step={f.kind === "number" ? "any" : undefined}
                          placeholder={f.placeholder}
                          value={paramText(selected.data.params[f.key])}
                          onChange={(e) =>
                            updateParam(selected.id, f.key, e.target.value, f.kind)
                          }
                        />
                      </div>
                    ),
                  )}
                  <Button variant="destructive" size="sm" onClick={deleteSelected}>
                    <Trash2 className="mr-2 h-3.5 w-3.5" />
                    Delete node
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Graph settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label className="mb-1 block text-xs text-muted-foreground">Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <Label className="mb-1 block text-xs text-muted-foreground">
                  Schedule (cron, blank = manual)
                </Label>
                <Input
                  value={schedule}
                  onChange={(e) => setSchedule(e.target.value)}
                  placeholder="0 9 * * 1-5"
                  className="font-mono text-xs"
                />
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-current"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                Enabled
                {enabled ? (
                  <Badge variant="positive">on</Badge>
                ) : (
                  <Badge variant="muted">off</Badge>
                )}
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-current"
                  checked={paperOnly}
                  onChange={(e) => setPaperOnly(e.target.checked)}
                />
                Paper-only
              </label>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Validate findings */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" /> Validation findings
          </CardTitle>
          <CardDescription>
            Runs against the current canvas (unsaved edits included).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {validateMutation.isPending ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Validating…
            </div>
          ) : validateMutation.isError ? (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errText(validateMutation.error, "Validation failed.")}
            </div>
          ) : !findings ? (
            <p className="text-sm text-muted-foreground">
              Press Validate to check for unknown node types, dangling edges, cycles and
              missing parameters.
            </p>
          ) : findings.length === 0 ? (
            <div className="rounded-md bg-positive/10 px-3 py-2 text-sm text-positive">
              No findings — the graph looks valid.
            </div>
          ) : (
            <ul className="space-y-2">
              {findings.map((f, i) => {
                const sev = f.severity.toLowerCase();
                const isErr = sev.includes("error") || sev.includes("fail") || sev.includes("invalid");
                const isWarn = sev.includes("warn");
                return (
                  <li key={i} className="flex flex-wrap items-start gap-2 rounded-md border px-3 py-2 text-sm">
                    {isErr ? (
                      <Badge variant="negative">{f.severity}</Badge>
                    ) : isWarn ? (
                      <Badge variant="outline" className="border-amber-500/40 text-amber-600 dark:text-amber-500">
                        {f.severity}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">{f.severity}</Badge>
                    )}
                    {f.node ? (
                      <span className="font-mono text-xs text-muted-foreground">{f.node}</span>
                    ) : null}
                    <span>{f.message}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Dry-run results */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Play className="h-4 w-4" /> Dry-run step results
          </CardTitle>
          <CardDescription>
            Executes market-data, indicator and condition nodes without placing orders.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {dryRunMutation.isPending ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Running dry-run…
            </div>
          ) : dryRunMutation.isError ? (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errText(dryRunMutation.error, "Dry-run failed.")}
            </div>
          ) : !steps ? (
            <p className="text-sm text-muted-foreground">
              Press Dry-run to execute the current canvas in dry_run mode.
            </p>
          ) : steps.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              The run returned no step results.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Step</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {steps.map((s, i) => {
                  const st = s.status.toLowerCase();
                  const ok = st.includes("ok") || st.includes("pass") || st.includes("success");
                  const bad =
                    st.includes("fail") || st.includes("error") || st.includes("reject");
                  return (
                    <TableRow key={i}>
                      <TableCell className="font-mono text-xs">{s.step}</TableCell>
                      <TableCell>
                        {ok ? (
                          <Badge variant="positive">{s.status}</Badge>
                        ) : bad ? (
                          <Badge variant="negative">{s.status}</Badge>
                        ) : (
                          <Badge variant="muted">{s.status}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="max-w-xl truncate text-sm text-muted-foreground">
                        {s.detail ?? "—"}
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
