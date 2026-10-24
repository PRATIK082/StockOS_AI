"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Terminal, Send, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTerminal } from "@/lib/terminal-store";
import {
  submitOrder,
  toggleTradebot,
  runAutopilot,
  fetchAutopilotState,
} from "@/lib/trading";
import { cn } from "@/lib/utils";

interface LogLine {
  kind: "info" | "ok" | "err";
  text: string;
}

const HELP = [
  "Commands:",
  "  help                         show this help",
  "  select <SYMBOL>              set active symbol",
  "  buy <SYMBOL> <QTY>           market buy",
  "  sell <SYMBOL> <QTY>          market sell",
  "  analyze <SYMBOL>             open AI workbench for symbol",
  "  refresh                      reload terminal snapshot",
  "  scan                         open scanner",
  "  backtest                     open backtest lab",
  "  autopilot run|monitor        run agent mission",
  "  bot on|off                   toggle TradeBot",
].join("\n");

export default function CommandBar() {
  const { symbol, setSymbol, refresh } = useTerminal();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<LogLine[]>([{ kind: "info", text: "Terminal ready. Press Ctrl+K or / to focus." }]);

  const push = useCallback((line: LogLine) => {
    setLog((prev) => [...prev.slice(-19), line]);
  }, []);

  const run = useCallback(
    async (raw: string) => {
      const cmd = raw.trim();
      if (!cmd) return;
      push({ kind: "info", text: `> ${cmd}` });
      const parts = cmd.split(/\s+/);
      const verb = parts[0].toLowerCase();
      setBusy(true);
      try {
        switch (verb) {
          case "help":
          case "?":
            push({ kind: "info", text: HELP });
            break;
          case "select":
          case "symbol": {
            const sym = parts[1]?.toUpperCase();
            if (!sym) throw new Error("usage: select <SYMBOL>");
            setSymbol(sym);
            push({ kind: "ok", text: `Active symbol set to ${sym}` });
            break;
          }
          case "buy":
          case "sell": {
            const sym = (parts[1] || symbol).toUpperCase();
            const qty = Number(parts[2]);
            if (!qty || qty <= 0) throw new Error("usage: buy|sell <SYMBOL> <QTY>");
            const side = verb === "buy" ? "BUY" : "SELL";
            const res = await submitOrder({ symbol: sym, side, quantity: qty, order_type: "MARKET" });
            push({ kind: "ok", text: `${side} ${qty} ${sym} -> ${res.status}` });
            refresh();
            break;
          }
          case "analyze": {
            const sym = (parts[1] || symbol).toUpperCase();
            setSymbol(sym);
            router.push("/trading/autopilot");
            push({ kind: "ok", text: `Opening AI workbench for ${sym}` });
            break;
          }
          case "refresh":
            refresh();
            push({ kind: "ok", text: "Terminal snapshot refreshed" });
            break;
          case "scan":
            router.push("/trading/scanner");
            push({ kind: "ok", text: "Opening scanner" });
            break;
          case "backtest":
            router.push("/trading/backtest");
            push({ kind: "ok", text: "Opening backtest lab" });
            break;
          case "autopilot": {
            const mode = parts[1]?.toLowerCase();
            if (mode === "run") {
              await runAutopilot(false);
              push({ kind: "ok", text: "Autonomous mission completed" });
            } else if (mode === "monitor") {
              await runAutopilot(true);
              push({ kind: "ok", text: "Monitor-only mission completed" });
            } else {
              const st = await fetchAutopilotState();
              push({ kind: "info", text: `Autopilot ${st.enabled ? "ON" : "OFF"} | last score ${st.last_review ? (st.last_review.score * 100).toFixed(0) + "%" : "n/a"}` });
            }
            refresh();
            break;
          }
          case "bot": {
            const state = parts[1]?.toLowerCase();
            if (state !== "on" && state !== "off") throw new Error("usage: bot on|off");
            await toggleTradebot(state === "on");
            push({ kind: "ok", text: `TradeBot ${state === "on" ? "enabled" : "disabled"}` });
            refresh();
            break;
          }
          default:
            throw new Error(`Unknown command '${verb}'. Type 'help'.`);
        }
      } catch (err) {
        push({ kind: "err", text: (err as Error).message || "Command failed" });
      } finally {
        setBusy(false);
        setValue("");
      }
    },
    [push, symbol, setSymbol, refresh, router],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Terminal className="h-4 w-4 text-primary" />
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Command Center</span>
        <span className="ml-auto text-[11px] text-muted-foreground">Ctrl+K or /</span>
      </div>
      <div className="flex items-center gap-2 p-2">
        <Input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void run(value);
            }
          }}
          placeholder="Type a command (help, buy NSE:RELIANCE 10, analyze TCS, autopilot run)…"
          className="h-9 text-sm"
          disabled={busy}
        />
        <Button size="sm" onClick={() => void run(value)} disabled={busy || !value.trim()}>
          <Send className="h-4 w-4" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => push({ kind: "info", text: HELP })}>
          <HelpCircle className="h-4 w-4" />
        </Button>
      </div>
      <div className="max-h-40 overflow-auto border-t bg-muted/30 px-3 py-2 font-mono text-[11px] leading-relaxed">
        {log.map((l, i) => (
          <div
            key={i}
            className={cn(
              "whitespace-pre-wrap",
              l.kind === "ok" && "text-positive",
              l.kind === "err" && "text-negative",
              l.kind === "info" && "text-muted-foreground",
            )}
          >
            {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}