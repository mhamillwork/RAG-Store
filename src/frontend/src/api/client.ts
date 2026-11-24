export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "rag-store-token";

export function getToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

async function parse(response: Response): Promise<unknown> {
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const message = body?.error?.message || response.statusText;
    throw new ApiError(response.status, message);
  }
  return body;
}

export async function api(path: string, init: RequestInit = {}): Promise<unknown> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  return parse(response);
}

export function login(username: string, password: string) {
  return api("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }) as Promise<{ access_token: string }>;
}

export function me() {
  return api("/api/v1/users/me") as Promise<{ id: string; username: string; role: string; quota: Record<string, number> }>;
}

export function collections(scope?: string) {
  const query = scope ? `?scope=${encodeURIComponent(scope)}` : "";
  return api(`/api/v1/collections${query}`) as Promise<{ collections: Collection[] }>;
}

export function createCollection(name: string, scope: string, description: string) {
  return api("/api/v1/collections", { method: "POST", body: JSON.stringify({ name, scope, description }) });
}

export function listing(collectionId: string, path: string) {
  return api(`/api/v1/collections/${collectionId}/listing?path=${encodeURIComponent(path)}`) as Promise<Listing>;
}

export function createFolder(collectionId: string, path: string) {
  return api(`/api/v1/collections/${collectionId}/folders`, { method: "POST", body: JSON.stringify({ path }) });
}

export async function uploadFile(scope: string, collection: string, file: File, relativePath: string) {
  const data = new FormData();
  data.set("scope", scope);
  data.set("collection", collection);
  data.set("relative_path", relativePath);
  data.set("file", file, file.name);
  return api("/api/v1/documents/upload", { method: "POST", body: data });
}

export function documentDetail(id: string) {
  return api(`/api/v1/documents/${id}`) as Promise<DocumentDetail>;
}

export function documentText(id: string) {
  return fetch(`/api/v1/documents/${id}/text`, { headers: { Authorization: `Bearer ${getToken()}` } }).then(async (response) => {
    if (!response.ok) throw new ApiError(response.status, await response.text());
    return response.text();
  });
}

export function documentTables(id: string) {
  return api(`/api/v1/documents/${id}/tables`) as Promise<{ tables: TablePreview[] }>;
}

export function jobs(state?: string) {
  const query = state ? `?state=${encodeURIComponent(state)}` : "";
  return api(`/api/v1/jobs${query}`) as Promise<{ jobs: Job[] }>;
}

export function retryJob(id: string) {
  return api(`/api/v1/jobs/${id}/retry`, { method: "POST" });
}

export function reindex(id: string) {
  return api(`/api/v1/documents/${id}/reindex`, { method: "POST" });
}

export function reprocess(id: string, ocrMode: string) {
  return api(`/api/v1/documents/${id}/reprocess`, { method: "POST", body: JSON.stringify({ ocr_mode: ocrMode }) });
}

export function removeDocument(id: string) {
  return api(`/api/v1/documents/${id}`, { method: "DELETE" });
}

export function renameDocument(id: string, filename: string) {
  return api(`/api/v1/documents/${id}`, { method: "PATCH", body: JSON.stringify({ filename }) });
}

export function moveDocument(id: string, collectionId: string) {
  return api(`/api/v1/documents/${id}`, { method: "PATCH", body: JSON.stringify({ collection_id: collectionId }) });
}

export function search(body: Record<string, unknown>) {
  return api("/api/v1/search", { method: "POST", body: JSON.stringify(body) }) as Promise<SearchResponse>;
}

export function systemStatus() {
  return api("/api/v1/admin/system-status");
}

export function adminUsers() {
  return api("/api/v1/admin/users") as Promise<{ users: Array<Record<string, string>> }>;
}

export function audit() {
  return api("/api/v1/admin/audit") as Promise<{ events: Array<Record<string, string>> }>;
}

export interface Collection {
  id: string;
  name: string;
  scope: string;
  description: string;
  is_default: boolean;
}

export interface Listing {
  path: string;
  folders: Array<{ id: string; name: string; path: string }>;
  documents: Array<Record<string, unknown>>;
}

export interface Job {
  id: string;
  document_id: string | null;
  state: string;
  job_type: string;
  progress: Record<string, unknown>;
  last_error: string;
  attempt_count: number;
}

export interface DocumentDetail {
  id: string;
  filename: string;
  file_type: string;
  scope: string;
  relative_path: string;
  lifecycle_state: string;
  ingestion_state: string | null;
  progress: Record<string, unknown>;
  chunk_count: number;
  version: Record<string, unknown> | null;
  conversion: Record<string, unknown> | null;
}

export interface TablePreview {
  id: string;
  caption: string;
  page_number: number | null;
  content: { headers?: string[]; rows?: string[][] };
}

export interface SearchResponse {
  mode: string;
  scope: string;
  degraded: boolean;
  degradation_reasons: string[];
  rerank_applied: boolean;
  hits: Array<Record<string, unknown>>;
}
