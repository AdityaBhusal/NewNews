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
 */
export function subscribeDeliveries(
  settings: Settings,
  onNews: (deliveryId: number) => void,
  onError?: (message: string) => void,
): () => void {
  const source = new EventSource(`${settings.baseUrl}/api/v1/events`, {
    headers: { Authorization: `Bearer ${settings.clientKey}` },
  });
  // Runtime dispatches our custom `news` frames; the library's types only know
  // the built-in names, so the cast stays at this boundary (value is "news").
  source.addEventListener("news" as "message", (event) => {
    try {
      const raw = (event as unknown as { data?: unknown }).data;
      const data = JSON.parse(typeof raw === "string" ? raw : "{}") as {
        delivery_id?: number;
      };
      if (typeof data.delivery_id === "number") onNews(data.delivery_id);
    } catch {
      // Malformed frame: ignore, the stream stays open.
    }
  });
  source.addEventListener("error", (event) => {
    onError?.(
      event.type === "error" && event.message ? String(event.message) : "stream error",
    );
  });
  return () => {
    source.removeAllEventListeners();
    source.close();
  };
}
