/** Minimal client for the NewNews public API (M5 Expo app). */

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
  topics: string[];
  created_at: string;
}

export function listReview(settings: Settings): Promise<{ count: number; items: ReviewItem[] }> {
  return request(settings, "/api/v1/review", { admin: true });
}

export interface AuditEntry {
  stage: string | null;
  event_type: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export function reviewDetail(
  settings: Settings,
  id: string,
): Promise<{ item: ReviewItem; audit: AuditEntry[] }> {
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
