"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import AppShell from "@/components/layout/shell";
import VibeRunView from "@/components/stock/VibeRunView";
import { getAuthToken } from "@/lib/api";
import { emptyVibeRun, useVibeRun, type VibeRunState } from "@/lib/vibe";
import { Bot, Loader2, Send, Sparkles, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const SUGGESTIONS = [
  "What is the technical outlook for NSE:RELIANCE?",
  "Analyze NSE:BANKNIFTY",
  "Should I hold NSE:TCS?",
  "Explain the outlook for AAPL",
];

interface Msg {
  role: "user" | "assistant";
  content: string;
  runKey: number;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [attachmentsInput, setAttachmentsInput] = useState("");
  const [skillsInput, setSkillsInput] = useState("");
  const [websearch, setWebsearch] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [runs, setRuns] = useState<Record<number, VibeRunState>>({});
  const [activeKey, setActiveKey] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const keyRef = useRef(0);
  const { run, streaming, start } = useVibeRun();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, runs, run.plan, run.answer]);

  const parseCsv = (s: string) => s.split(",").map((t) => t.trim()).filter(Boolean);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;
    setInput("");
    const key = ++keyRef.current;
    setActiveKey(key);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed, runKey: 0 },
      { role: "assistant", content: "", runKey: key },
    ]);
    const allAttachmentIds = parseCsv(attachmentsInput);
    const attachment_ids = allAttachmentIds.slice(0, 5);
    const skills = parseCsv(skillsInput);
    const nextWarnings: string[] = [];
    if (allAttachmentIds.length > 5) nextWarnings.push("Only the first 5 attachment IDs were sent (max 5).");
    if (attachment_ids.length > 0 && !getAuthToken())
      nextWarnings.push("Sign in to use attachments; attachment_ids may be ignored for anonymous users.");
    setWarnings(nextWarnings);
    const final = await start(trimmed, {
      attachment_ids,
      skills: skills.length ? skills : undefined,
      websearch,
    });
    setRuns((prev) => ({ ...prev, [key]: final }));
    setActiveKey((k) => (k === key ? null : k));
  };

  return (
    <AppShell>
      <div className="mx-auto flex h-[calc(100vh-7rem)] max-w-5xl flex-col">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <Sparkles className="h-5 w-5 text-primary" /> Vibe Trading Chat
            </h1>
            <p className="text-sm text-muted-foreground">
              Ask about any stock — the pipeline streams live quote, technicals, options view and an AI prediction before the verdict.
            </p>
          </div>
        </div>

        <Card className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                <Bot className="h-10 w-10 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  Try a stock question — real data streams in, stage by stage, before the AI verdict.
                </p>
                <div className="grid w-full max-w-lg gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <Button key={s} variant="outline" size="sm" className="justify-start text-left" onClick={() => send(s)}>
                      {s}
                    </Button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => {
              const live = activeKey === m.runKey && streaming ? run : null;
              const snapshot = runs[m.runKey];
              return (
                <div key={i} className={`flex gap-3 ${m.role === "user" ? "flex-row-reverse" : ""}`}>
                  <div
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                      m.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground"
                    }`}
                  >
                    {m.role === "user" ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                  </div>
                  <div
                    className={`max-w-[88%] rounded-lg border px-4 py-2 ${
                      m.role === "user" ? "border-primary/20 bg-primary/5" : "w-full bg-card"
                    }`}
                  >
                    {m.role === "user" ? (
                      <p className="text-sm">{m.content}</p>
                    ) : (
                      <VibeRunView run={live ?? snapshot ?? emptyVibeRun()} />
                    )}
                  </div>
                </div>
              );
            })}

            {streaming && (
              <div className="flex items-center gap-2 pl-11 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> {run.active ? `Running: ${run.active}` : "Waiting for pipeline…"}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="space-y-2 border-t p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <Input
                  value={attachmentsInput}
                  onChange={(e) => setAttachmentsInput(e.target.value)}
                  placeholder="Attachment IDs (comma-separated, max 5)"
                  aria-label="Attachment IDs"
                />
                <p className="mt-1 text-xs text-muted-foreground">IDs of previously uploaded files.</p>
              </div>
              <div>
                <Input
                  value={skillsInput}
                  onChange={(e) => setSkillsInput(e.target.value)}
                  placeholder="Skills (comma-separated)"
                  aria-label="Skills"
                />
                <p className="mt-1 text-xs text-muted-foreground">Unknown skill names are ignored with a warning.</p>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={websearch} onChange={(e) => setWebsearch(e.target.checked)} />
              Web search
            </label>
            {warnings.length > 0 && (
              <ul className="space-y-1">
                {warnings.map((w) => (
                  <li key={w} className="text-xs text-yellow-600 dark:text-yellow-400">
                    {w}
                  </li>
                ))}
              </ul>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
              className="flex items-end gap-2"
            >
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(input);
                  }
                }}
                placeholder="Ask about any stock… (Enter to send, Shift+Enter for newline)"
                className="max-h-40"
                rows={1}
              />
              <Button type="submit" size="icon" disabled={!input.trim() || streaming} aria-label="Send">
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
