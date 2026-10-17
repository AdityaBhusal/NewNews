/** Minimal client for the NewNews public API (M5 Expo app). */

import EventSource from "react-native-sse";

export interface Settings {
  baseUrl: string;
  clientKey: string;
  adminKey: string;
}

export const DEFAULT_SETTINGS: Settings = {
  baseUrl: "https://newnews-t54x.onrender.com",
  clientKey: "",
  adminKey: "",
};

async function request<T>(
  settings: Settings,
  path: string,
  options: { method?: string; body?: unknown; admin?: boolean } = {},
): Promise<T> {
  const key = options.admin ? settings.adminKey : settings.clientKey;
  const response = await fetch(settings.baseUrl + path, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.admin
        ? { "X-Admin-Key": key }
        : { Authorization: `Bearer ${key}` }),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${options.method ?? "GET"} ${path} → ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

export interface IngestResult {
  id: string;
  status: string;
  correlation_id: string;
  duplicate: boolean;
}

export function createItem(
  settings: Settings,
  input: { title?: string; body: string; source_key: string; source?: string },
): Promise<IngestResult> {
  return request(settings, "/api/v1/items", { method: "POST", body: input });
}

export interface MediaResult {
  id: string;
  kind: string;
  extraction_status: string;
  size_bytes: number;
}

export async function uploadMedia(
  settings: Settings,
  itemId: string,
  file: { uri: string; name: string; mimeType: string },
): Promise<MediaResult> {
  const form = new FormData();
  // React Native FormData file part.
  form.append("file", {
    uri: file.uri,
    name: file.name,
    type: file.mimeType,
  } as unknown as Blob);
  const response = await fetch(
    `${settings.baseUrl}/api/v1/items/${itemId}/media`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${settings.clientKey}` },
      body: form,
    },
  );
  if (!response.ok) {
    throw new Error(`POST media → ${response.status}: ${await response.text()}`);
  }
  return response.json() as Promise<MediaResult>;
}

export interface ReviewItem {
  id: string;
  status: string;
  title: string | null;
  body: string;
  language: string | null;
  summary: string | null;
  credibility_score: number | null;
  credibility_confidence: number | null;
  validation_status: string | null;
  validation_rationale: string | null;
  certainty_label: string;
  editorially_reviewed: boolean;
  reviewed_at: string | null;
  topics: string[];
  urgency: string;
  eligible_at: string | null;
  delivered_at: string | null;
  created_at: string;
}

export function listReview(settings: Settings): Promise<{ count: number; items: ReviewItem[] }> {
  return request(settings, "/api/v1/review", { admin: true });
}

export interface Delivery {
  delivery_id: number;
  item: ReviewItem;
}

export function listNews(settings: Settings, ack = true): Promise<{ count: number; items: Delivery[] }> {
  return request(settings, `/api/v1/news${ack ? "?ack=true" : ""}`);
}

export interface AuditEntry {
  stage: string | null;
  event_type: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface MediaAsset {
  id: string;
  kind: string;
  filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  extraction_status: string;
}

export function reviewDetail(
  settings: Settings,
  id: string,
): Promise<{ item: ReviewItem; audit: AuditEntry[]; media: MediaAsset[] }> {
  return request(settings, `/api/v1/review/${id}`, { admin: true });
}

export interface TrackEntry {
  item: ReviewItem;
  events: string[];
}

export function listTrackBoard(
  settings: Settings,
  limit = 200,
): Promise<{ count: number; items: TrackEntry[] }> {
  return request(settings, `/api/v1/track?limit=${limit}`, { admin: true });
}

export function approveItem(settings: Settings, id: string, note?: string): Promise<ReviewItem> {
  return request(settings, `/api/v1/review/${id}/approve`, {
    method: "POST",
    body: { note: note || null },
    admin: true,
  });
}

export function rejectItem(settings: Settings, id: string, reason: string): Promise<ReviewItem> {
  return request(settings, `/api/v1/review/${id}/reject`, {
    method: "POST",
    body: { reason },
    admin: true,
  });
}

/**
 * Live delivery stream (SSE). Unlike browsers, React Native can set headers,
 * so the client key travels as `Authorization: Bearer` — no query-key needed.
 * Calls `onNews` for every `news` event; returns a cleanup function.
 *
 * Auto-reconnects with backoff (1s → 2s → 4s … cap 30s) — a dropped frame
 * never leaves the screen silently dead; `onError` reports reconnect attempts.
 */
export function subscribeDeliveries(
  settings: Settings,
  onNews: (deliveryId: number, item?: ReviewItem) => void,
  onError?: (message: string) => void,
  onOpen?: () => void,
): () => void {
  return openStream({
    url: `${settings.baseUrl}/api/v1/events`,
    headers: { Authorization: `Bearer ${settings.clientKey}` },
    event: "news",
    onFrame: (data) => {
      const parsed = data as { delivery_id?: number; item?: ReviewItem };
      if (typeof parsed.delivery_id === "number") {
        onNews(parsed.delivery_id, parsed.item);
      }
    },
    onError,
    onOpen,
  });
}

/**
 * Live pipeline-board stream (admin): one `board` frame whenever ANY item
 * changes stage (audit watermark) — the Track screen refetches the board on
 * each frame. Auto-reconnects like subscribeDeliveries; admin key travels as
 * `X-Admin-Key` (RN's EventSource accepts headers).
 */
export function subscribeTrackBoard(
  settings: Settings,
  onBoard: (lastAuditId: number) => void,
  onError?: (message: string) => void,
  onOpen?: () => void,
): () => void {
  return openStream({
    url: `${settings.baseUrl}/api/v1/track/events`,
    headers: { "X-Admin-Key": settings.adminKey },
    event: "board",
    onFrame: (data) => {
      const parsed = data as { audit_count?: number };
      onBoard(typeof parsed.audit_count === "number" ? parsed.audit_count : 0);
    },
    onError,
    onOpen,
  });
}

interface StreamSpec {
  url: string;
  headers: Record<string, string>;
  event: string;
  onFrame: (data: unknown) => void;
  onError?: (message: string) => void;
  onOpen?: () => void;
}

/**
 * One SSE connection with automatic reconnection. RN's `EventSource` does not
 * reconnect on its own, and Render's proxy drops idle sockets — without this,
 * any blip silently killed the "live" view (the reload-forever symptom).
 */
function openStream(spec: StreamSpec): () => void {
  let stopped = false;
  let attempt = 0;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (stopped) return;
    source = new EventSource(spec.url, { headers: spec.headers });
    source.addEventListener("open", () => {
      attempt = 0;
      spec.onOpen?.();
    });
    source.addEventListener(spec.event as "message", (event) => {
      try {
        const raw = (event as unknown as { data?: unknown }).data;
        spec.onFrame(JSON.parse(typeof raw === "string" ? raw : "{}"));
      } catch {
        // Malformed frame: ignore, the stream stays open.
      }
    });
    source.addEventListener("error", (event) => {
      source?.close();
      if (stopped) return;
      attempt += 1;
      const delayMs = Math.min(1000 * 2 ** Math.min(attempt, 5), 30_000);
      const reason =
        event.type === "error" && event.message ? String(event.message) : "stream dropped";
      spec.onError?.(`${reason} — reconnecting in ${Math.round(delayMs / 1000)}s`);
      timer = setTimeout(connect, delayMs);
    });
  };

  connect();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    source?.removeAllEventListeners();
    source?.close();
  };
}
