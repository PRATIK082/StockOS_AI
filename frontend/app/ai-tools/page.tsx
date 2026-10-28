"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Boxes,
  Cable,
  Check,
  Loader2,
  Plug,
  RefreshCw,
  Server,
  TrendingDown,
  TrendingUp,
  Unplug,
  Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, fmt } from "@/lib/api";
import { SymbolSearch } from "@/components/stock/symbol-search";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  API shapes (verified against the live backend)                            */
/* -------------------------------------------------------------------------- */

/** GET /llm/registry -> { default_provider, providers: [{ provider, models }] } */
interface LlmProvider {
  provider: string;
  models?: string[];
  label?: string | null;
  is_local?: boolean;
  needs_key?: boolean;
  needs_base_url?: boolean;
  key_env?: string | null;
  default_deep?: string;
  default_quick?: string;
  hint?: string;
}

interface LlmRegistryResponse {
  default_provider: string;
  providers: LlmProvider[];
}

/** GET /mcp/clients -> { clients: ["name", ...] } (list of registered names). */
interface McpClientsResponse {
  clients: Array<string | { name?: string }>;
}

/** POST /mcp/clients/{stdio,sse} -> { name, transport, tools: string[] } */
interface McpConnectResponse {
  name: string;
  transport: string;
  tools?: Array<string | McpTool>;
}

/** GET /mcp/clients/{name}/tools -> { name, tools: [{ name, description, inputSchema }] } */
interface McpTool {
  name: string;
  description?: string;
  inputSchema?: unknown;
}

interface McpToolsResponse {
  name: string;
  tools?: Array<string | McpTool>;
}

/** POST /mcp/clients/{name}/call/{tool} -> { name, tool, result } */
interface McpCallResponse {
  name: string;
  tool: string;
  result: unknown;
}

/** GET /chart-markup?symbol=... -> agent chart-markup payload */
interface ChartMarker {
  time?: string;
  type?: string;
  reason?: string;
  price?: number;
}

interface ChartLevel {
  price?: number;
  type?: string;
  index?: number;
}

interface ChartMarkupResponse {
  symbol?: string | null;
  interval?: string;
  period?: string;
  candle_count?: number;
  markers?: ChartMarker[];
  levels?: ChartLevel[];
  trend?: string;
  last_close?: number;
  error?: string;
}

/** GET /brokers/plugins -> { plugins: [...] } */
interface BrokerPlugin {
  name: string;
  display_name?: string;
  broker_type?: string;
  module?: string;
  class?: string;
  supported_exchanges?: string[];
  capabilities?: string[];
  auth_required?: boolean;
}

interface BrokerPluginsResponse {
  plugins?: BrokerPlugin[];
}

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                    */
/* -------------------------------------------------------------------------- */

const INTERVALS = ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"];
const PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y"];

type Banner = { type: "success" | "error"; msg: string } | null;

function errMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

function errStatus(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null;
}

/** Normalise the many shapes a "tool" can take (string name or MCP tool dict). */
function normalizeTool(raw: unknown): McpTool | null {
  if (typeof raw === "string") return raw.trim() ? { name: raw } : null;
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const name = typeof obj.name === "string" ? obj.name : "";
    if (!name) return null;
    return {
      name,
      description: typeof obj.description === "string" ? obj.description : undefined,
      inputSchema: obj.inputSchema,
    };
  }
  return null;
}

function normalizeTools(raw: unknown): McpTool[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizeTool).filter((t): t is McpTool => t !== null);
}

/** The client registry currently returns plain names; stay tolerant of dicts. */
function normalizeClientNames(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const names: string[] = [];
  for (const item of raw) {
    if (typeof item === "string" && item.trim()) {
      names.push(item);
    } else if (item && typeof item === "object") {
      const name = (item as { name?: unknown }).name;
      if (typeof name === "string" && name.trim()) names.push(name);
    }
  }
  return names;
}

/** Merge the live-detected provider list with the static provider metadata. */
function mergeProviders(live: LlmProvider[], meta: LlmProvider[]): LlmProvider[] {
  const byId = new Map<string, LlmProvider>();
  for (const p of live) {
    byId.set(p.provider, { provider: p.provider, models: Array.isArray(p.models) ? p.models : [] });
  }
  for (const p of meta) {
    const prev = byId.get(p.provider);
    const liveModels = prev?.models ?? [];
    const metaModels = Array.isArray(p.models) ? p.models : [];
    byId.set(p.provider, {
      provider: p.provider,
      models: liveModels.length > 0 ? liveModels : metaModels,
      label: p.label ?? null,
      is_local: p.is_local ?? false,
      needs_key: p.needs_key ?? false,
      needs_base_url: p.needs_base_url ?? false,
      key_env: p.key_env ?? null,
      default_deep: p.default_deep ?? "",
      default_quick: p.default_quick ?? "",
      hint: p.hint ?? "",
    });
  }
  return Array.from(byId.values());
}

interface ClientView {
  tools: McpTool[];
  toolsLoaded: boolean;
  toolsLoading: boolean;
  toolsError: string | null;
  selectedTool: string;
  argsText: string;
  result: string | null;
  resultError: string | null;
  calling: boolean;
}

const EMPTY_CLIENT: ClientView = {
  tools: [],
  toolsLoaded: false,
  toolsLoading: false,
  toolsError: null,
  selectedTool: "",
  argsText: "{}",
  result: null,
  resultError: null,
  calling: false,
};

function patchClient(
  state: Record<string, ClientView>,
  name: string,
  patch: Partial<ClientView>,
): Record<string, ClientView> {
  const prev = state[name] ?? EMPTY_CLIENT;
  return { ...state, [name]: { ...prev, ...patch } };
}

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function AiToolsPage() {
  const queryClient = useQueryClient();

  /* ------------------------------ model registry ------------------------ */

  const registryQuery = useQuery<LlmRegistryResponse>({
    queryKey: ["llm-registry"],
    queryFn: () => api.get<LlmRegistryResponse>("/llm/registry"),
    retry: false,
  });

  const metaQuery = useQuery<LlmRegistryResponse>({
    queryKey: ["trading-model-registry"],
    queryFn: () => api.get<LlmRegistryResponse>("/trading/model-registry"),
    retry: false,
  });

  const defaultProvider = registryQuery.data?.default_provider ?? metaQuery.data?.default_provider ?? "";

  const providers = useMemo(() => {
    const live = registryQuery.data?.providers ?? [];
    const meta = metaQuery.data?.providers ?? [];
    if (live.length === 0 && meta.length === 0) return [];
    return mergeProviders(live, meta);
  }, [registryQuery.data, metaQuery.data]);

  /* -------------------------------- mcp clients ------------------------- */

  const clientsQuery = useQuery<McpClientsResponse>({
    queryKey: ["mcp-clients"],
    queryFn: () => api.get<McpClientsResponse>("/mcp/clients"),
    retry: false,
  });

  const clientNames = useMemo(
    () => normalizeClientNames(clientsQuery.data?.clients),
    [clientsQuery.data],
  );

  const [connectForm, setConnectForm] = useState({
    transport: "stdio" as "stdio" | "sse",
    name: "",
    command: "",
    args: "",
    url: "",
    timeout: "30",
  });
  const [connectBanner, setConnectBanner] = useState<Banner>(null);
  const [lastConnect, setLastConnect] = useState<McpConnectResponse | null>(null);
  const [clientState, setClientState] = useState<Record<string, ClientView>>({});

  const connectMutation = useMutation({
    mutationFn: async (form: typeof connectForm) => {
      const timeout = Number(form.timeout) > 0 ? Number(form.timeout) : 30;
      if (form.transport === "stdio") {
        const args = form.args.trim() ? form.args.trim().split(/\s+/) : undefined;
        return api.post<McpConnectResponse>("/mcp/clients/stdio", {
          name: form.name.trim(),
          command: form.command.trim(),
          ...(args ? { args } : {}),
          timeout,
        });
      }
      return api.post<McpConnectResponse>("/mcp/clients/sse", {
        name: form.name.trim(),
        url: form.url.trim(),
        timeout,
      });
    },
    onSuccess: (res) => {
      setLastConnect(res);
      setConnectBanner({
        type: "success",
        msg: `Connected "${res.name}" over ${res.transport} — ${normalizeTools(res.tools).length} tool(s) discovered.`,
      });
      setClientState((prev) =>
        patchClient(prev, res.name, {
          tools: normalizeTools(res.tools),
          toolsLoaded: true,
          toolsError: null,
          selectedTool: normalizeTools(res.tools)[0]?.name ?? "",
        }),
      );
      setConnectForm((prev) => ({ ...prev, name: "", command: "", args: "", url: "" }));
      queryClient.invalidateQueries({ queryKey: ["mcp-clients"] });
    },
    onError: (error) => {
      setLastConnect(null);
      const status = errStatus(error);
      const prefix = status === 502 ? "MCP server unreachable: " : status === 404 ? "Unknown client: " : "";
      setConnectBanner({ type: "error", msg: prefix + errMessage(error, "Failed to connect MCP server") });
    },
  });

  const toolsMutation = useMutation({
    mutationFn: (name: string) =>
      api.get<McpToolsResponse>(`/mcp/clients/${encodeURIComponent(name)}/tools`),
    onMutate: (name) => {
      setClientState((prev) => patchClient(prev, name, { toolsLoading: true, toolsError: null }));
    },
    onSuccess: (res, name) => {
      const tools = normalizeTools(res?.tools);
      setClientState((prev) =>
        patchClient(prev, name, {
          tools,
          toolsLoaded: true,
          toolsLoading: false,
          toolsError: null,
          selectedTool: prev[name]?.selectedTool || tools[0]?.name || "",
        }),
      );
    },
    onError: (error, name) => {
      const status = errStatus(error);
      const prefix = status === 404 ? "MCP client not found. " : "";
      setClientState((prev) =>
        patchClient(prev, name, {
          toolsLoading: false,
          toolsError: prefix + errMessage(error, "Failed to list tools"),
        }),
      );
    },
  });

  const callMutation = useMutation({
    mutationFn: async (vars: { name: string; tool: string; argsText: string }) => {
      let parsed: Record<string, unknown> = {};
      const raw = vars.argsText.trim();
      if (raw) {
        let asObject: unknown;
        try {
          asObject = JSON.parse(raw);
        } catch {
          throw new Error("Tool arguments must be valid JSON, e.g. {\"symbol\": \"AAPL\"}");
        }
        if (asObject && typeof asObject === "object" && !Array.isArray(asObject)) {
          parsed = asObject as Record<string, unknown>;
        } else {
          throw new Error("Tool arguments must be a JSON object, e.g. {\"symbol\": \"AAPL\"}");
        }
      }
      const res = await api.post<McpCallResponse>(
        `/mcp/clients/${encodeURIComponent(vars.name)}/call/${encodeURIComponent(vars.tool)}`,
        { arguments: parsed },
      );
      return res;
    },
    onMutate: (vars) => {
      setClientState((prev) =>
        patchClient(prev, vars.name, { calling: true, resultError: null, result: null }),
      );
    },
    onSuccess: (res, vars) => {
      setClientState((prev) =>
        patchClient(prev, vars.name, {
          calling: false,
          resultError: null,
          result: JSON.stringify(res?.result ?? null, null, 2),
        }),
      );
    },
    onError: (error, vars) => {
      const status = errStatus(error);
      const prefix = status === 404 ? "MCP client not found. " : status === 502 ? "Tool call failed. " : "";
      setClientState((prev) =>
        patchClient(prev, vars.name, {
          calling: false,
          resultError: prefix + errMessage(error, "Tool call failed"),
        }),
      );
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: (name: string) => api.del<void>(`/mcp/clients/${encodeURIComponent(name)}`),
    onSuccess: (_res, name) => {
      setClientState((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["mcp-clients"] });
    },
    onError: (error) => {
      const status = errStatus(error);
      const prefix = status === 404 ? "MCP client not found. " : "";
      setConnectBanner({ type: "error", msg: prefix + errMessage(error, "Failed to disconnect") });
    },
  });

  /* ------------------------------- chart markup ------------------------- */

  const [markupForm, setMarkupForm] = useState({
    symbol: "AAPL",
    interval: "1d",
    period: "3mo",
    provider: "",
  });

  const markupMutation = useMutation({
    mutationFn: async (form: typeof markupForm) => {
      const params = new URLSearchParams();
      params.set("symbol", form.symbol.trim());
      params.set("interval", form.interval);
      params.set("period", form.period);
      if (form.provider.trim()) params.set("provider", form.provider.trim());
      return api.get<ChartMarkupResponse>(`/chart-markup?${params.toString()}`);
    },
  });

  /* ----------------------------- broker plugins ------------------------- */

  const pluginsQuery = useQuery<BrokerPluginsResponse>({
    queryKey: ["broker-plugins"],
    queryFn: () => api.get<BrokerPluginsResponse>("/brokers/plugins"),
    retry: false,
  });

  const plugins = pluginsQuery.data?.plugins ?? [];

  /* --------------------------------- render ----------------------------- */

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">AI &amp; Integrations</h1>
        <p className="text-sm text-muted-foreground">
          LLM providers and models, Model Context Protocol clients, chart markup and broker plugins.
        </p>
      </div>

      <Tabs defaultValue="models">
        <TabsList>
          <TabsTrigger value="models">Model Registry</TabsTrigger>
          <TabsTrigger value="mcp">MCP Clients</TabsTrigger>
          <TabsTrigger value="markup">Chart Markup</TabsTrigger>
        </TabsList>

        {/* ------------------------------ models ---------------------------- */}
        <TabsContent value="models" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Server className="h-4 w-4" />
                Model Registry
              </CardTitle>
              <CardDescription>
                Providers exposed by the LLM gateway and the models detected on this machine.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 rounded-md border px-4 py-3 text-sm">
                <span className="text-muted-foreground">Default provider</span>
                {defaultProvider ? (
                  <Badge variant="positive">{defaultProvider}</Badge>
                ) : (
                  <span className="text-muted-foreground">unknown</span>
                )}
                <span className="ml-auto text-xs text-muted-foreground">
                  Read-only — the default provider is a backend setting (llm_default_provider) and cannot be
                  changed from the UI.
                </span>
              </div>

              {registryQuery.isLoading || metaQuery.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              ) : registryQuery.isError ? (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {errMessage(registryQuery.error, "Failed to load the model registry")}
                </div>
              ) : providers.length === 0 ? (
                <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                  No providers reported by the backend.
                </div>
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  {providers.map((provider) => {
                    const models = provider.models ?? [];
                    const isDefault = provider.provider === defaultProvider;
                    return (
                      <Card key={provider.provider} className="shadow-none">
                        <CardHeader className="pb-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <CardTitle className="text-base">{provider.label || provider.provider}</CardTitle>
                            <Badge variant="outline">{provider.provider}</Badge>
                            {isDefault ? <Badge variant="positive">default</Badge> : null}
                            {provider.is_local ? <Badge variant="muted">local</Badge> : null}
                            {provider.needs_key ? <Badge variant="secondary">key required</Badge> : null}
                            {provider.needs_base_url ? <Badge variant="secondary">base url required</Badge> : null}
                          </div>
                          {provider.hint ? (
                            <CardDescription className="mt-1">{provider.hint}</CardDescription>
                          ) : null}
                        </CardHeader>
                        <CardContent className="space-y-3">
                          <div>
                            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                              Models
                            </p>
                            {models.length === 0 ? (
                              <p className="text-sm text-muted-foreground">
                                No models detected — this provider may be a local runtime that is not running.
                              </p>
                            ) : (
                              <div className="flex flex-wrap gap-1.5">
                                {models.map((model) => (
                                  <Badge key={model} variant="secondary" className="font-mono">
                                    {model}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>

                          {provider.default_deep || provider.default_quick ? (
                            <div className="text-xs text-muted-foreground">
                              {provider.default_deep ? (
                                <div>
                                  <span className="font-medium">Deep:</span>{" "}
                                  <span className="font-mono">{provider.default_deep}</span>
                                </div>
                              ) : null}
                              {provider.default_quick ? (
                                <div>
                                  <span className="font-medium">Quick:</span>{" "}
                                  <span className="font-mono">{provider.default_quick}</span>
                                </div>
                              ) : null}
                            </div>
                          ) : null}

                          {provider.needs_key && provider.key_env ? (
                            <p className="text-xs text-muted-foreground">
                              Set <span className="font-mono">{provider.key_env}</span> in the backend environment.
                            </p>
                          ) : null}
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ------------------------------- mcp ------------------------------ */}
        <TabsContent value="mcp" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plug className="h-4 w-4" />
                Connect an MCP Server
              </CardTitle>
              <CardDescription>
                Speak the Model Context Protocol over stdio (subprocess) or SSE (HTTP stream).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {connectBanner ? (
                <div
                  className={cn(
                    "rounded-md px-4 py-3 text-sm",
                    connectBanner.type === "success"
                      ? "bg-positive/10 text-positive"
                      : "bg-destructive/10 text-destructive",
                  )}
                >
                  {connectBanner.msg}
                </div>
              ) : null}

              <form
                className="grid gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  setLastConnect(null);
                  connectMutation.mutate(connectForm);
                }}
              >
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Transport</Label>
                    <Select
                      value={connectForm.transport}
                      onValueChange={(v) =>
                        setConnectForm((prev) => ({ ...prev, transport: v as "stdio" | "sse" }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select transport" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="stdio">stdio (local subprocess)</SelectItem>
                        <SelectItem value="sse">SSE (remote HTTP endpoint)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="mcp-name">Client name</Label>
                    <Input
                      id="mcp-name"
                      value={connectForm.name}
                      onChange={(e) => setConnectForm((prev) => ({ ...prev, name: e.target.value }))}
                      placeholder="filesystem"
                      required
                    />
                  </div>

                  {connectForm.transport === "stdio" ? (
                    <>
                      <div className="space-y-2">
                        <Label htmlFor="mcp-command">Command</Label>
                        <Input
                          id="mcp-command"
                          value={connectForm.command}
                          onChange={(e) => setConnectForm((prev) => ({ ...prev, command: e.target.value }))}
                          placeholder="npx"
                          className="font-mono"
                          required
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="mcp-args">Arguments (optional)</Label>
                        <Input
                          id="mcp-args"
                          value={connectForm.args}
                          onChange={(e) => setConnectForm((prev) => ({ ...prev, args: e.target.value }))}
                          placeholder="-y @modelcontextprotocol/server-filesystem /tmp"
                          className="font-mono"
                        />
                      </div>
                    </>
                  ) : (
                    <div className="space-y-2 md:col-span-2">
                      <Label htmlFor="mcp-url">Server URL</Label>
                      <Input
                        id="mcp-url"
                        value={connectForm.url}
                        onChange={(e) => setConnectForm((prev) => ({ ...prev, url: e.target.value }))}
                        placeholder="http://localhost:8931/sse"
                        className="font-mono"
                        required
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="mcp-timeout">Timeout (seconds)</Label>
                    <Input
                      id="mcp-timeout"
                      type="number"
                      min={1}
                      value={connectForm.timeout}
                      onChange={(e) => setConnectForm((prev) => ({ ...prev, timeout: e.target.value }))}
                    />
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button type="submit" disabled={connectMutation.isPending}>
                    {connectMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Cable className="h-4 w-4" />
                    )}
                    Connect
                  </Button>
                </div>
              </form>

              {lastConnect ? (
                <div className="rounded-md border px-4 py-3">
                  <p className="mb-2 text-sm font-medium">
                    Discovered tools for “{lastConnect.name}” ({lastConnect.transport})
                  </p>
                  {normalizeTools(lastConnect.tools).length === 0 ? (
                    <p className="text-sm text-muted-foreground">The server reported no tools.</p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {normalizeTools(lastConnect.tools).map((tool) => (
                        <Badge key={tool.name} variant="secondary" className="font-mono">
                          {tool.name}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Boxes className="h-4 w-4" />
                Connected Clients
              </CardTitle>
              <CardDescription>
                {clientsQuery.isLoading
                  ? "Loading clients…"
                  : `${clientNames.length} client(s) registered with the backend.`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {clientsQuery.isError ? (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {errMessage(clientsQuery.error, "Failed to load MCP clients")}
                </div>
              ) : null}

              {clientsQuery.isLoading ? (
                <Skeleton className="h-16 w-full" />
              ) : clientNames.length === 0 ? (
                <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                  No MCP clients connected yet. Connect one above to discover its tools.
                </div>
              ) : (
                <div className="space-y-4">
                  {clientNames.map((name) => {
                    const view = clientState[name] ?? EMPTY_CLIENT;
                    return (
                      <Card key={name} className="shadow-none">
                        <CardHeader className="pb-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <CardTitle className="text-base">{name}</CardTitle>
                            <div className="flex items-center gap-2">
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                onClick={() => toolsMutation.mutate(name)}
                                disabled={toolsMutation.isPending && toolsMutation.variables === name}
                              >
                                {toolsMutation.isPending && toolsMutation.variables === name ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <RefreshCw className="h-4 w-4" />
                                )}
                                List tools
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="destructive"
                                onClick={() => disconnectMutation.mutate(name)}
                                disabled={disconnectMutation.isPending}
                              >
                                {disconnectMutation.isPending &&
                                disconnectMutation.variables === name ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Unplug className="h-4 w-4" />
                                )}
                                Disconnect
                              </Button>
                            </div>
                          </div>
                        </CardHeader>

                        <CardContent className="space-y-4">
                          {view.toolsError ? (
                            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                              {view.toolsError}
                            </div>
                          ) : null}

                          {view.toolsLoaded ? (
                            view.tools.length === 0 ? (
                              <p className="text-sm text-muted-foreground">This client exposes no tools.</p>
                            ) : (
                              <div className="space-y-2">
                                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                  Tools
                                </p>
                                <ul className="space-y-2">
                                  {view.tools.map((tool) => (
                                    <li key={tool.name} className="rounded-md border px-3 py-2">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
                                        <span className="font-mono text-sm">{tool.name}</span>
                                      </div>
                                      {tool.description ? (
                                        <p className="mt-1 text-xs text-muted-foreground">{tool.description}</p>
                                      ) : null}
                                      {tool.inputSchema ? (
                                        <details className="mt-1">
                                          <summary className="cursor-pointer text-xs text-muted-foreground">
                                            input schema
                                          </summary>
                                          <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted/40 p-2 text-[11px]">
                                            {JSON.stringify(tool.inputSchema, null, 2)}
                                          </pre>
                                        </details>
                                      ) : null}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )
                          ) : null}

                          {view.tools.length > 0 ? (
                            <div className="space-y-3 rounded-md border px-3 py-3">
                              <p className="text-sm font-medium">Call a tool</p>
                              <div className="grid gap-3 md:grid-cols-2">
                                <div className="space-y-2">
                                  <Label>Tool</Label>
                                  <Select
                                    value={view.selectedTool}
                                    onValueChange={(v) =>
                                      setClientState((prev) =>
                                        patchClient(prev, name, { selectedTool: v, result: null, resultError: null }),
                                      )
                                    }
                                  >
                                    <SelectTrigger>
                                      <SelectValue placeholder="Select a tool" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {view.tools.map((tool) => (
                                        <SelectItem key={tool.name} value={tool.name}>
                                          {tool.name}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div className="space-y-2">
                                  <Label htmlFor={`args-${name}`}>Arguments (JSON)</Label>
                                  <Textarea
                                    id={`args-${name}`}
                                    value={view.argsText}
                                    onChange={(e) =>
                                      setClientState((prev) =>
                                        patchClient(prev, name, { argsText: e.target.value }),
                                      )
                                    }
                                    className="font-mono text-xs"
                                    rows={4}
                                    placeholder='{"symbol": "AAPL"}'
                                  />
                                </div>
                              </div>
                              <div className="flex justify-end">
                                <Button
                                  type="button"
                                  size="sm"
                                  disabled={!view.selectedTool || view.calling}
                                  onClick={() =>
                                    callMutation.mutate({
                                      name,
                                      tool: view.selectedTool,
                                      argsText: view.argsText,
                                    })
                                  }
                                >
                                  {view.calling ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Check className="h-4 w-4" />
                                  )}
                                  Call tool
                                </Button>
                              </div>

                              {view.resultError ? (
                                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                                  {view.resultError}
                                </div>
                              ) : null}

                              {view.result !== null ? (
                                <pre className="max-h-64 overflow-auto rounded bg-muted/40 p-3 text-xs">
                                  {view.result}
                                </pre>
                              ) : null}
                            </div>
                          ) : null}
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ------------------------------ markup ---------------------------- */}
        <TabsContent value="markup" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4" />
                Chart Markup
              </CardTitle>
              <CardDescription>
                Technical markers, support/resistance levels and trend derived from real price history.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <form
                className="grid gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  markupMutation.mutate(markupForm);
                }}
              >
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                  <div className="space-y-2">
                    <Label htmlFor="markup-symbol">Symbol</Label>
                    <SymbolSearch
                      value={markupForm.symbol}
                      onChange={(v) => setMarkupForm((prev) => ({ ...prev, symbol: v }))}
                      onSelect={(v) => setMarkupForm((prev) => ({ ...prev, symbol: v }))}
                      placeholder="Type to search, e.g. RELIANCE…"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Interval</Label>
                    <Select
                      value={markupForm.interval}
                      onValueChange={(v) => setMarkupForm((prev) => ({ ...prev, interval: v }))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select interval" />
                      </SelectTrigger>
                      <SelectContent>
                        {INTERVALS.map((i) => (
                          <SelectItem key={i} value={i}>
                            {i}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Period</Label>
                    <Select
                      value={markupForm.period}
                      onValueChange={(v) => setMarkupForm((prev) => ({ ...prev, period: v }))}
                    >
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
                  <div className="space-y-2">
                    <Label htmlFor="markup-provider">Provider (optional)</Label>
                    <Input
                      id="markup-provider"
                      value={markupForm.provider}
                      onChange={(e) => setMarkupForm((prev) => ({ ...prev, provider: e.target.value }))}
                      placeholder="yahoo"
                    />
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button type="submit" disabled={markupMutation.isPending || !markupForm.symbol.trim()}>
                    {markupMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <TrendingUp className="h-4 w-4" />
                    )}
                    Generate markup
                  </Button>
                </div>
              </form>

              {markupMutation.isError ? (
                <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <p className="font-medium">
                        {errStatus(markupMutation.error) === 502
                          ? "Market data provider failed"
                          : "Chart markup failed"}
                      </p>
                      <p className="mt-1 break-words">
                        {errMessage(markupMutation.error, "Unknown error")}
                      </p>
                    </div>
                  </div>
                </div>
              ) : null}

              {markupMutation.data ? (
                <div className="space-y-4">
                  {markupMutation.data.error ? (
                    <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
                      {markupMutation.data.error === "no data"
                        ? "No price history was returned for this symbol — try a different symbol, interval or period."
                        : markupMutation.data.error}
                    </div>
                  ) : null}

                  <div className="grid gap-3 md:grid-cols-4">
                    <div className="rounded-md border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Symbol</p>
                      <p className="text-sm font-medium">{markupMutation.data.symbol ?? "—"}</p>
                    </div>
                    <div className="rounded-md border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Candles</p>
                      <p className="text-sm font-medium">{markupMutation.data.candle_count ?? 0}</p>
                    </div>
                    <div className="rounded-md border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Last close</p>
                      <p className="text-sm font-medium">{fmt(markupMutation.data.last_close)}</p>
                    </div>
                    <div className="rounded-md border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Trend</p>
                      <div className="mt-0.5">
                        {markupMutation.data.trend === "up" ? (
                          <Badge variant="positive">
                            <TrendingUp className="mr-1 h-3 w-3" />
                            up
                          </Badge>
                        ) : markupMutation.data.trend === "down" ? (
                          <Badge variant="negative">
                            <TrendingDown className="mr-1 h-3 w-3" />
                            down
                          </Badge>
                        ) : (
                          <Badge variant="muted">{markupMutation.data.trend ?? "unknown"}</Badge>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Support / Resistance
                      </p>
                      {markupMutation.data.levels && markupMutation.data.levels.length > 0 ? (
                        <ul className="space-y-1.5">
                          {markupMutation.data.levels.map((level, index) => (
                            <li
                              key={`${level.type}-${level.index ?? index}-${level.price ?? index}`}
                              className="flex items-center justify-between rounded-md border px-3 py-2"
                            >
                              <Badge
                                variant={level.type === "support" ? "positive" : "negative"}
                              >
                                {level.type ?? "level"}
                              </Badge>
                              <span className="font-mono text-sm">{fmt(level.price)}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          No support or resistance levels detected for this window.
                        </p>
                      )}
                    </div>

                    <div className="space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Signal Markers
                      </p>
                      {markupMutation.data.markers && markupMutation.data.markers.length > 0 ? (
                        <ul className="space-y-1.5">
                          {markupMutation.data.markers.map((marker, index) => (
                            <li
                              key={`${marker.time ?? index}-${marker.type ?? "m"}-${index}`}
                              className="rounded-md border px-3 py-2"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <Badge
                                  variant={
                                    marker.type === "buy"
                                      ? "positive"
                                      : marker.type === "sell"
                                        ? "negative"
                                        : "muted"
                                  }
                                >
                                  {marker.type ?? "signal"}
                                </Badge>
                                <span className="font-mono text-sm">{fmt(marker.price)}</span>
                              </div>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {marker.reason ?? "—"}
                                {marker.time ? ` · ${marker.time}` : ""}
                              </p>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          No buy/sell crossovers detected for this window.
                        </p>
                      )}
                    </div>
                  </div>

                  <details className="rounded-md border px-3 py-2">
                    <summary className="cursor-pointer text-sm font-medium">Raw response</summary>
                    <pre className="mt-2 max-h-72 overflow-auto rounded bg-muted/40 p-3 text-xs">
                      {JSON.stringify(markupMutation.data, null, 2)}
                    </pre>
                  </details>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ---------------------------- broker plugins ------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            Broker Plugins
          </CardTitle>
          <CardDescription>
            Execution backends discovered by the broker plugin loader.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pluginsQuery.isLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : pluginsQuery.isError ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(pluginsQuery.error, "Failed to load broker plugins")}
            </div>
          ) : plugins.length === 0 ? (
            <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
              No broker plugins registered.
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {plugins.map((plugin) => (
                <Card key={plugin.name} className="shadow-none">
                  <CardHeader className="pb-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle className="text-base">
                        {plugin.display_name || plugin.name}
                      </CardTitle>
                      <Badge variant="outline">{plugin.name}</Badge>
                      {plugin.broker_type ? (
                        <Badge variant={plugin.broker_type === "live" ? "negative" : "muted"}>
                          {plugin.broker_type}
                        </Badge>
                      ) : null}
                      {plugin.auth_required ? <Badge variant="secondary">auth required</Badge> : null}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div>
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Exchanges
                      </p>
                      {plugin.supported_exchanges && plugin.supported_exchanges.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {plugin.supported_exchanges.map((exchange) => (
                            <Badge key={exchange} variant="secondary">
                              {exchange}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">None reported.</p>
                      )}
                    </div>

                    <div>
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Capabilities
                      </p>
                      {plugin.capabilities && plugin.capabilities.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {plugin.capabilities.map((capability) => (
                            <Badge key={capability} variant="outline">
                              {capability}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">None reported.</p>
                      )}
                    </div>

                    {plugin.module || plugin.class ? (
                      <p className="break-all text-xs text-muted-foreground">
                        {plugin.module ? <span className="font-mono">{plugin.module}</span> : null}
                        {plugin.module && plugin.class ? " · " : null}
                        {plugin.class ? <span className="font-mono">{plugin.class}</span> : null}
                      </p>
                    ) : null}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
