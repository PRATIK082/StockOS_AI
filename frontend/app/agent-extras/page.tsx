"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, Mic, Paperclip, Search, Sparkles, Trash2 } from "lucide-react";
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
import { API_BASE, ApiError, api, getAuthToken } from "@/lib/api";

/* -------------------------------------------------------------------------- */
/*  API shapes (verified against backend/app/api/routers/agent_extras.py)     */
/* -------------------------------------------------------------------------- */

/** POST /voice/transcribe -> { text, language, duration_s, model } */
interface TranscribeResponse {
  text?: unknown;
  transcript?: unknown;
  language?: unknown;
  duration_s?: unknown;
  model?: unknown;
}

/**
 * POST /agent/attachments -> Attachment.to_dict() + text_preview (+ note).
 * NOTE: the backend has NO mime / uploaded_at keys — Attachment.to_dict()
 * returns { id, filename, kind, size, text_chars }. Both are rendered with
 * shape-tolerant fallbacks below.
 */
interface AttachmentItem {
  id: string;
  filename?: unknown;
  name?: unknown;
  size?: unknown;
  mime?: unknown;
  kind?: unknown;
  uploaded_at?: unknown;
  created_at?: unknown;
  text_preview?: unknown;
  text?: unknown;
  note?: unknown;
}

interface AttachmentUploadResponse extends AttachmentItem {
  text_preview?: unknown;
  note?: unknown;
}

interface AttachmentListResponse {
  attachments?: unknown;
}

/** GET /agent/websearch -> { query, results: [{ title, url, snippet }], note } */
interface WebHit {
  title?: unknown;
  url?: unknown;
  link?: unknown;
  snippet?: unknown;
  description?: unknown;
}

interface WebSearchResponse {
  query?: unknown;
  results?: unknown;
  note?: unknown;
}

/** GET /agent/skills -> { selection, skills: [{ name, title, chars }] } (no bodies). */
interface SkillItem {
  name?: unknown;
  title?: unknown;
  description?: unknown;
  chars?: unknown;
}

interface SkillsResponse {
  selection?: unknown;
  skills?: unknown;
}

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                    */
/* -------------------------------------------------------------------------- */

function errMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

function errStatus(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null;
}

function asText(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function str(v: unknown, fallback = "—"): string {
  if (typeof v === "string" && v) return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

function formatBytes(v: unknown): string {
  if (typeof v !== "number" || !Number.isFinite(v) || v < 0) return "—";
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
  return `${(v / (1024 * 1024)).toFixed(2)} MB`;
}

function normalizeAttachments(raw: unknown): AttachmentItem[] {
  const list = Array.isArray(raw) ? raw : [];
  return list.filter(
    (a): a is AttachmentItem => !!a && typeof a === "object" && typeof (a as { id?: unknown }).id === "string",
  ) as AttachmentItem[];
}

function normalizeHits(raw: unknown): WebHit[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((h): h is WebHit => !!h && typeof h === "object") as WebHit[];
}

function normalizeSkills(raw: unknown): SkillItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((s): s is SkillItem => !!s && typeof s === "object") as SkillItem[];
}

function mimeFallback(item: AttachmentItem): string {
  const direct = asText(item.mime);
  if (direct) return direct;
  const kind = asText(item.kind);
  if (kind) return kind;
  const name = asText(item.filename) || asText(item.name);
  const dot = name.lastIndexOf(".");
  if (dot >= 0 && dot < name.length - 1) return name.slice(dot + 1).toLowerCase();
  return "—";
}

/** Raw multipart upload (the JSON api helper cannot send FormData). */
async function uploadMultipart<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const token = getAuthToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
  } catch {
    throw new ApiError(`Cannot reach backend at ${API_BASE} - is it running?`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function AgentExtrasPage() {
  const queryClient = useQueryClient();

  /* ------------------------------ voice STT ----------------------------- */

  const [sttFile, setSttFile] = useState<File | null>(null);

  const sttMutation = useMutation({
    mutationFn: (file: File) => uploadMultipart<TranscribeResponse>("/voice/transcribe", file),
  });

  const sttStatus = errStatus(sttMutation.error);
  const sttErrorMsg =
    sttStatus === 501
      ? `Voice transcription is disabled on the backend. ${errMessage(sttMutation.error, "")}`.trim()
      : sttStatus === 422
        ? `Unsupported file type — pick an audio file. ${errMessage(sttMutation.error, "")}`.trim()
        : sttMutation.error
          ? errMessage(sttMutation.error, "Transcription failed")
          : null;
  const sttText = asText(sttMutation.data?.text) || asText(sttMutation.data?.transcript);
  const sttLanguage = asText(sttMutation.data?.language);

  /* ----------------------------- attachments ---------------------------- */

  const [attFile, setAttFile] = useState<File | null>(null);
  const [attPreviews, setAttPreviews] = useState<Record<string, string>>({});

  const attachmentsQuery = useQuery<AttachmentListResponse>({
    queryKey: ["agent-attachments"],
    queryFn: () => api.get<AttachmentListResponse>("/agent/attachments"),
    retry: false,
  });

  const attachments = normalizeAttachments(attachmentsQuery.data?.attachments);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadMultipart<AttachmentUploadResponse>("/agent/attachments", file),
    onSuccess: (res) => {
      const preview = asText(res?.text_preview);
      if (res?.id && preview) {
        setAttPreviews((prev) => ({ ...prev, [res.id as string]: preview }));
      }
      setAttFile(null);
      queryClient.invalidateQueries({ queryKey: ["agent-attachments"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.del<{ deleted?: string }>(`/agent/attachments/${encodeURIComponent(id)}`),
    onSuccess: (_res, id) => {
      setAttPreviews((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["agent-attachments"] });
    },
  });

  const uploadStatus = errStatus(uploadMutation.error);
  const uploadErrorMsg =
    uploadStatus === 501
      ? `Attachments are disabled on the backend. ${errMessage(uploadMutation.error, "")}`.trim()
      : uploadStatus === 422
        ? `Unsupported file type. ${errMessage(uploadMutation.error, "")}`.trim()
        : uploadMutation.error
          ? errMessage(uploadMutation.error, "Upload failed")
          : null;

  /* ------------------------------ web search ---------------------------- */

  const [searchInput, setSearchInput] = useState("");

  const searchMutation = useMutation({
    mutationFn: (q: string) =>
      api.get<WebSearchResponse>(`/agent/websearch?q=${encodeURIComponent(q)}`),
  });

  const searchStatus = errStatus(searchMutation.error);
  const searchErrorMsg =
    searchStatus === 501
      ? `Web search is disabled on the backend. ${errMessage(searchMutation.error, "")}`.trim()
      : searchStatus === 502
        ? `Web search upstream failed. ${errMessage(searchMutation.error, "")}`.trim()
        : searchMutation.error
          ? errMessage(searchMutation.error, "Web search failed")
          : null;
  const searchHits = normalizeHits(searchMutation.data?.results);
  const searchNote = asText(searchMutation.data?.note);

  /* -------------------------------- skills ------------------------------ */

  const [copiedName, setCopiedName] = useState<string | null>(null);

  const skillsQuery = useQuery<SkillsResponse>({
    queryKey: ["agent-skills"],
    queryFn: () => api.get<SkillsResponse>("/agent/skills"),
    retry: false,
  });

  const skills = normalizeSkills(skillsQuery.data?.skills);
  const skillsSelection = asText(skillsQuery.data?.selection);

  async function copySkillName(name: string) {
    try {
      await navigator.clipboard.writeText(name);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = name;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopiedName(name);
  }

  /* --------------------------------- render ----------------------------- */

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Agent Extras</h1>
        <p className="text-sm text-muted-foreground">
          Voice transcription, file attachments, web search and skill packs for the chat agent.
        </p>
      </div>

      {/* ------------------------------- voice STT -------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mic className="h-4 w-4" />
            Voice Transcription
          </CardTitle>
          <CardDescription>
            Upload an audio file to transcribe it with the backend speech-to-text engine.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="flex flex-wrap items-end gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (sttFile) sttMutation.mutate(sttFile);
            }}
          >
            <div className="min-w-64 flex-1 space-y-2">
              <Label htmlFor="stt-file">Audio file</Label>
              <Input
                id="stt-file"
                type="file"
                accept="audio/*,.mp3,.wav,.m4a,.ogg,.oga,.flac,.webm,.mp4"
                onChange={(e) => {
                  setSttFile(e.target.files?.[0] ?? null);
                  sttMutation.reset();
                }}
              />
            </div>
            <Button type="submit" disabled={!sttFile || sttMutation.isPending}>
              {sttMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
              Transcribe
            </Button>
          </form>

          {sttErrorMsg ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">{sttErrorMsg}</div>
          ) : null}

          {sttMutation.data ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Transcript</span>
                {sttLanguage ? <Badge variant="secondary">language: {sttLanguage}</Badge> : null}
                {asText(sttMutation.data?.model) ? (
                  <Badge variant="outline">{asText(sttMutation.data?.model)}</Badge>
                ) : null}
              </div>
              {sttText ? (
                <p className="whitespace-pre-wrap rounded-md border px-4 py-3 text-sm">{sttText}</p>
              ) : (
                <p className="text-sm text-muted-foreground">The backend returned an empty transcript.</p>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ----------------------------- attachments -------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Paperclip className="h-4 w-4" />
            Attachments
          </CardTitle>
          <CardDescription>
            Files the chat agent can reference. Only text files (.txt/.md/.csv/.json) are readable by the
            agent — images and PDFs are stored only.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="flex flex-wrap items-end gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (attFile) uploadMutation.mutate(attFile);
            }}
          >
            <div className="min-w-64 flex-1 space-y-2">
              <Label htmlFor="att-file">File</Label>
              <Input
                id="att-file"
                type="file"
                onChange={(e) => {
                  setAttFile(e.target.files?.[0] ?? null);
                  uploadMutation.reset();
                }}
              />
            </div>
            <Button type="submit" disabled={!attFile || uploadMutation.isPending}>
              {uploadMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
              Upload
            </Button>
          </form>

          {uploadErrorMsg ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">{uploadErrorMsg}</div>
          ) : null}

          {uploadMutation.isSuccess && uploadMutation.data ? (
            <div className="rounded-md bg-positive/10 px-4 py-3 text-sm text-positive">
              Uploaded “{str(uploadMutation.data.filename ?? uploadMutation.data.name, "file")}”.
              {asText(uploadMutation.data.note) ? ` ${asText(uploadMutation.data.note)}` : ""}
            </div>
          ) : null}

          {deleteMutation.isError ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(deleteMutation.error, "Failed to delete attachment")}
            </div>
          ) : null}

          {attachmentsQuery.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : attachmentsQuery.isError ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(attachmentsQuery.error, "Failed to load attachments")}
            </div>
          ) : attachments.length === 0 ? (
            <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
              No attachments yet. Upload a file above to make it available to the agent.
            </div>
          ) : (
            <div className="space-y-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Filename</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Mime</TableHead>
                    <TableHead>Uploaded</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {attachments.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-mono text-xs">{item.id}</TableCell>
                      <TableCell className="max-w-48 truncate">
                        {str(item.filename ?? item.name)}
                      </TableCell>
                      <TableCell>{formatBytes(item.size)}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">{mimeFallback(item)}</Badge>
                      </TableCell>
                      <TableCell>{str(item.uploaded_at ?? item.created_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          disabled={deleteMutation.isPending && deleteMutation.variables === item.id}
                          onClick={() => deleteMutation.mutate(item.id)}
                        >
                          {deleteMutation.isPending && deleteMutation.variables === item.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                          Delete
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {attachments.map((item) => {
                const preview =
                  attPreviews[item.id] || asText(item.text_preview) || asText(item.text);
                const kind = asText(item.kind);
                if (preview) {
                  return (
                    <div key={`${item.id}-preview`} className="space-y-1">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Preview — {str(item.filename ?? item.name)}
                      </p>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">
                        {preview.slice(0, 2000)}
                      </pre>
                    </div>
                  );
                }
                if (kind && kind !== "text") {
                  return (
                    <p key={`${item.id}-preview`} className="text-xs text-muted-foreground">
                      “{str(item.filename ?? item.name)}” ({kind}) is stored only — only text files are
                      readable by the agent.
                    </p>
                  );
                }
                return null;
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ------------------------------ web search -------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            Web Search
          </CardTitle>
          <CardDescription>Search the web through the backend search provider.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="flex flex-wrap items-end gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              const q = searchInput.trim();
              if (q) searchMutation.mutate(q);
            }}
          >
            <div className="min-w-64 flex-1 space-y-2">
              <Label htmlFor="websearch-q">Query</Label>
              <Input
                id="websearch-q"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="e.g. RBI repo rate decision"
              />
            </div>
            <Button type="submit" disabled={!searchInput.trim() || searchMutation.isPending}>
              {searchMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Search
            </Button>
          </form>

          {searchErrorMsg ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">{searchErrorMsg}</div>
          ) : null}

          {searchMutation.data ? (
            <div className="space-y-2">
              {searchNote ? <p className="text-xs text-muted-foreground">{searchNote}</p> : null}
              {searchHits.length === 0 ? (
                <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                  No results for this query. Try rephrasing.
                </div>
              ) : (
                <ul className="space-y-2">
                  {searchHits.map((hit, index) => {
                    const url = asText(hit.url) || asText(hit.link);
                    const title = asText(hit.title) || url || `Result ${index + 1}`;
                    const snippet = asText(hit.snippet) || asText(hit.description);
                    return (
                      <li key={`${url || title}-${index}`} className="rounded-md border px-3 py-2">
                        {url ? (
                          <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm font-medium text-primary underline underline-offset-2"
                          >
                            {title}
                          </a>
                        ) : (
                          <p className="text-sm font-medium">{title}</p>
                        )}
                        {snippet ? <p className="mt-1 text-xs text-muted-foreground">{snippet}</p> : null}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* -------------------------------- skills ---------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" />
            Skills
          </CardTitle>
          <CardDescription>
            Skill packs the chat agent can apply. Copy a name and mention it in chat to use it.
            {skillsSelection ? ` Backend selection: ${skillsSelection}.` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {skillsQuery.isLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : skillsQuery.isError ? (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {errMessage(skillsQuery.error, "Failed to load skills")}
            </div>
          ) : skills.length === 0 ? (
            <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
              No skills available on the backend.
            </div>
          ) : (
            <ul className="space-y-2">
              {skills.map((skill, index) => {
                const name = asText(skill.name) || `skill-${index + 1}`;
                const description = asText(skill.description) || asText(skill.title);
                return (
                  <li
                    key={`${name}-${index}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2"
                  >
                    <div className="min-w-0">
                      <span className="font-mono text-sm">{name}</span>
                      {description ? (
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">{description}</p>
                      ) : null}
                    </div>
                    <Button type="button" size="sm" variant="outline" onClick={() => copySkillName(name)}>
                      {copiedName === name ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                      {copiedName === name ? "Copied" : "Copy name"}
                    </Button>
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
