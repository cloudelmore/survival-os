export type Status = {
  cpu_percent: number | null;
  memory: { total_bytes: number; available_bytes: number } | null;
  temperature_c: number | null;
  uptime_seconds: number | null;
  storage: {
    usable_bytes: number;
    available_bytes: number;
    used_bytes: number;
    floor_bytes: number;
  } | null;
  power: {
    input_volts: number | null;
    supply_current_ma: number | null;
    throttling: { now: string[]; since_boot: string[] } | null;
  };
  services: Record<string, string>;
};

export type AdminState = { pin_set: boolean; actions_enabled: boolean };
export type Action = "shutdown" | "reboot" | "maintenance";

async function send(path: string, body: object): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : "Request failed");
  }
}

async function load<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

export const getStatus = () => load<Status>("/api/status");
export const getAdminState = () => load<AdminState>("/api/admin/state");
export const setPin = (pin: string) => send("/api/admin/pin", { pin });
export const runAction = (action: Action, pin: string) =>
  send("/api/system/action", { action, pin });

export type SnippetPart = { text: string; hit: boolean };
export type SearchResult = {
  document_id: number;
  title: string;
  format: string;
  category: string;
  path: string;
  page: number;
  label: string;
  pages_total: number;
  snippet: SnippetPart[];
  hits: string[];
};
export type SearchResponse = { results: SearchResult[]; total: number; more: boolean };
export type LibraryStatus = {
  documents: number;
  passages: number;
  pages_total: number;
  pages_done: number;
  pending: number;
  failed: { path: string; error: string }[];
  no_text: { path: string; pages_no_text: number }[];
  formats: Record<string, number>;
  categories: Record<string, number>;
  indexer: { state: string; detail: string };
};
export type LibraryDocument = {
  id: number;
  title: string;
  format: string;
  category: string;
  pages_total: number;
};
export type DocumentView =
  | { kind: "text"; text: string }
  | { kind: "html"; html: string }
  | { kind: "pdf" };

export const getLibraryStatus = () => load<LibraryStatus>("/api/library/status");
export const searchLibrary = (query: string, format: string, category: string, offset: number) => {
  const params = new URLSearchParams({ q: query, offset: String(offset) });
  if (format) params.set("format", format);
  if (category) params.set("category", category);
  return load<SearchResponse>(`/api/library/search?${params}`);
};
export const getDocument = (id: number) => load<LibraryDocument>(`/api/library/documents/${id}`);
export const getDocumentView = (id: number, page: number) =>
  load<DocumentView>(`/api/library/documents/${id}/view?page=${page}`);
export const rescanLibrary = () => send("/api/library/rescan", {});
