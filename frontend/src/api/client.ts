// A small typed fetch wrapper: adds the X-PaperTrail header on state-changing requests
// and turns the backend's error shape into an ApiError (BUILD_PLAN §9, §10).
import type { components } from "./types";

export type Schemas = components["schemas"];
export type DocumentOut = Schemas["DocumentOut"];
export type DocumentDetail = Schemas["DocumentDetailOut"];
export type Item = Schemas["ItemOut"];
export type ItemsPayload = Schemas["ItemsOut"];
export type ReviewIn = Schemas["ReviewIn"];
export type ItemChanges = Schemas["ItemChanges"];
export type RunSummary = Schemas["RunSummary"];
export type AppSettings = Schemas["SettingsOut"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (MUTATING.has(method)) headers.set("X-PaperTrail", "1");
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, method, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "network", "PaperTrail isn't running. Start it with `papertrail serve`.");
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "internal_error",
      error?.message ?? "Something went wrong. Details are in the log.",
    );
  }
  return body as T;
}

export const api = {
  listDocuments: () => request<DocumentOut[]>("/documents"),
  getDocument: (id: string) => request<DocumentDetail>(`/documents/${encodeURIComponent(id)}`),
  getItems: (id: string) => request<ItemsPayload>(`/documents/${encodeURIComponent(id)}/items`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentOut>("/documents", { method: "POST", body: form });
  },
  review: (itemId: string, body: ReviewIn) =>
    request<Item>(`/items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  reprocess: (id: string) =>
    request<DocumentOut>(`/documents/${encodeURIComponent(id)}/reprocess`, { method: "POST" }),
  remove: (id: string) =>
    request<void>(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getSettings: () => request<AppSettings>("/settings"),
  putSetting: (key: string, value: string) =>
    request<AppSettings>(`/settings/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  fileUrl: (id: string) => `/api/documents/${encodeURIComponent(id)}/file`,
  calendarUrl: (id: string) => `/api/documents/${encodeURIComponent(id)}/calendar.ics`,
};
