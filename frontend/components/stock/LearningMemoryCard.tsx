"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Brain, Settings2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, getAuthToken } from "@/lib/api";

interface MemoryItem {
  key: string;
  value: unknown;
  kind?: string;
  scope?: string;
  created_at?: string;
  updated_at?: string;
}

type Dict = Record<string, unknown>;

function asObject(value: unknown): Dict | null {
  if (value != null && typeof value === "object" && !Array.isArray(value)) return value as Dict;
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value);
      if (parsed != null && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Dict;
    } catch {
      /* plain text, not JSON */
    }
  }
  return null;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
}

function fmtDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

function sideBadgeClass(side: string): string {
  const s = side.toUpperCase();
  if (s === "BUY" || s === "LONG") return "bg-positive/10 text-positive";
  if (s === "SELL" || s === "SHORT") return "bg-negative/10 text-negative";
  return "bg-muted text-muted-foreground";
}

/** Trade-journal entry: {symbol, side, rationale, pnl, outcome, tags[]} */
function JournalView({ data }: { data: Dict }) {
  const symbol = str(data.symbol) || "—";
  const side = str(data.side) || "HOLD";
  const outcome = str(data.outcome);
  const pnl = num(data.pnl);
  const rationale = str(data.rationale);
  const tags = Array.isArray(data.tags) ? data.tags.map(str).filter(Boolean) : [];
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold text-foreground">{symbol}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${sideBadgeClass(side)}`}>{side}</span>
        {outcome && (
          <Badge variant="outline" className="text-[10px]">
            {outcome}
          </Badge>
        )}
        {pnl !== null && (
          <span className={`text-[11px] font-medium ${pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-muted-foreground"}`}>
            {pnl > 0 ? "+" : ""}
            {pnl.toFixed(2)}
          </span>
        )}
      </div>
      {rationale && <p className="text-xs leading-relaxed text-muted-foreground">{rationale}</p>}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tags.map((t) => (
            <Badge key={t} variant="secondary" className="text-[10px]">
              {t}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

/** Autopilot self-review: {agent, mission, n_fills, n_rejects, n_entries, n_exits, realised_pnl, score, halt_recommended, notes[]} */
function SelfReviewView({ data }: { data: Dict }) {
  const mission = str(data.mission) || "mission";
  const stats: [string, unknown][] = [
    ["fills", data.n_fills ?? data.fills],
    ["rejected", data.n_rejects ?? data.rejects],
    ["entries", data.n_entries],
    ["exits", data.n_exits],
    ["P&L", data.realised_pnl ?? data.pnl],
    ["score", data.score],
  ];
  const notes = Array.isArray(data.notes) ? data.notes.map(str).filter(Boolean) : [];
  const halt = data.halt_recommended === true;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold text-foreground">Self-review · {mission}</span>
        {halt && (
          <span className="flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-500">
            <AlertTriangle className="h-3 w-3" /> halt recommended
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
        {stats.map(([label, v]) => (
          <span key={label}>
            {label} <span className="font-medium text-foreground">{str(v) === "" ? "—" : str(v)}</span>
          </span>
        ))}
      </div>
      {notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
          {notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Autopilot config snapshot — compact key/value grid, not an insight. */
function ConfigView({ data }: { data: Dict }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <Settings2 className="h-3.5 w-3.5 text-muted-foreground" /> Autopilot configuration
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        {entries.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="truncate text-muted-foreground">{k}</dt>
            <dd className="truncate font-medium text-foreground">
              {Array.isArray(v) ? (v.length === 0 ? "—" : v.map(str).join(", ")) : typeof v === "object" ? JSON.stringify(v) : str(v) === "" ? "—" : str(v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Free-form note: {note|text} or plain string. */
function NoteView({ data, raw }: { data: Dict | null; raw: unknown }) {
  const text = data ? str(data.note ?? data.text) : str(raw);
  return <p className="text-xs leading-relaxed text-muted-foreground">{text || "—"}</p>;
}

function itemTitle(key: string, data: Dict | null): string {
  if (key.startsWith("journal:")) {
    const symbol = data ? str(data.symbol) : "";
    return symbol && symbol !== "MISSION" ? `Journal · ${symbol}` : "Mission journal";
  }
  if (key === "autopilot:self_review") return "Autopilot review";
  if (key === "autopilot:config") return "Autopilot config";
  if (key.startsWith("note:")) return "Agent note";
  return key;
}

export default function LearningMemoryCard() {
  const [authenticated, setAuthenticated] = useState(false);
  useEffect(() => {
    setAuthenticated(Boolean(getAuthToken()));
  }, []);

  const { data } = useQuery({
    queryKey: ["memory", "all"],
    queryFn: () => api.get<MemoryItem[]>("/memory"),
    enabled: authenticated,
    retry: false,
  });

  const items = Array.isArray(data) ? data : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Brain className="h-4 w-4 text-primary" /> AI Learning Memory
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!authenticated && (
          <p className="text-sm text-muted-foreground">Sign in to persist agent insights and self-learning notes.</p>
        )}
        {authenticated && items.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No learned insights yet. Run the AI Trading Desk to seed memory.
          </p>
        )}
        {authenticated && items.length > 0 && (
          <ul className="max-h-96 space-y-2 overflow-auto">
            {items.slice(0, 8).map((m) => {
              const obj = asObject(m.value);
              const kind =
                m.key === "autopilot:self_review"
                  ? "review"
                  : m.key === "autopilot:config"
                    ? "config"
                    : m.key.startsWith("journal:")
                      ? "journal"
                      : "note";
              return (
                <li key={m.key} className="space-y-1.5 rounded-md border border-border bg-muted/30 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-medium text-foreground">{itemTitle(m.key, obj)}</p>
                    {fmtDate(m.updated_at) && (
                      <p className="shrink-0 text-[10px] text-muted-foreground">{fmtDate(m.updated_at)}</p>
                    )}
                  </div>
                  {kind === "journal" && obj ? (
                    <JournalView data={obj} />
                  ) : kind === "review" && obj ? (
                    <SelfReviewView data={obj} />
                  ) : kind === "config" && obj ? (
                    <ConfigView data={obj} />
                  ) : obj && (obj.note !== undefined || obj.text !== undefined) ? (
                    <NoteView data={obj} raw={null} />
                  ) : obj ? (
                    <pre className="whitespace-pre-wrap break-words text-[11px] text-muted-foreground">
                      {JSON.stringify(obj, null, 2)}
                    </pre>
                  ) : (
                    <NoteView data={null} raw={m.value} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {authenticated && items.length > 0 && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            {items.length} {items.length === 1 ? "entry" : "entries"} stored · feeds future runs
          </p>
        )}
      </CardContent>
    </Card>
  );
}
