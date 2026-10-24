"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { VibeAnswerEvent, VibeEvent, VibeStageEvent } from "@/lib/api";
import { getAuthToken } from "@/lib/api";

export const VIBE_API_ORIGIN = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type VibeStageStatus = "done" | "skipped" | "error";

export interface VibeStageState {
  status: VibeStageStatus;
  data: Record<string, any>;
}

export interface VibeRunState {
  plan: Array<{ key: string; label: string }>;
  stages: Record<string, VibeStageState>;
  active: string | null;
  answer: VibeAnswerEvent["data"] | null;
  error: string | null;
}

export function emptyVibeRun(): VibeRunState {
  return { plan: [], stages: {}, active: null, answer: null, error: null };
}

function nextActive(run: VibeRunState): string | null {
  for (const p of run.plan) {
    if (p.key === "answer") {
      if (run.answer) continue;
      return p.key;
    }
    if (!run.stages[p.key]) return p.key;
  }
  return null;
}

export function applyVibeEvent(run: VibeRunState, ev: VibeEvent): VibeRunState {
  if (ev.type === "plan") {
    const next: VibeRunState = { ...run, plan: ev.plan };
    return { ...next, active: nextActive(next) };
  }
  if (ev.type === "stage") {
    const stage = ev as VibeStageEvent;
    const next: VibeRunState = { ...run, stages: { ...run.stages, [stage.key]: { status: stage.status, data: stage.data } } };
    return { ...next, active: nextActive(next) };
  }
  if (ev.type === "answer") {
    const next: VibeRunState = { ...run, answer: ev.data };
    return { ...next, active: nextActive(next) };
  }
  if (ev.type === "error") {
    return { ...run, error: ev.data.detail, active: null };
  }
  return run;
}

export interface VibeRunController {
  run: VibeRunState;
  streaming: boolean;
  start: (message: string) => Promise<VibeRunState>;
  cancel: () => void;
}

export function useVibeRun(): VibeRunController {
  const [run, setRun] = useState<VibeRunState>(emptyVibeRun);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const start = useCallback(async (message: string) => {
    abortRef.current?.abort();
    setRun(emptyVibeRun());
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let latest = emptyVibeRun();
    try {
      const res = await fetch(`${VIBE_API_ORIGIN}/api/chat/vibe`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
        },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`Vibe chat failed (${res.status})`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            let ev: VibeEvent;
            try {
              ev = JSON.parse(line.slice(6));
            } catch {
              continue;
            }
            setRun((r) => {
              const next = applyVibeEvent(r, ev);
              latest = next;
              return next;
            });
          }
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        latest = { ...latest, error: err?.message ?? "Stream error" };
        setRun(latest);
      }
    } finally {
      setStreaming(false);
    }
    return latest;
  }, []);

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  return { run, streaming, start, cancel };
}
