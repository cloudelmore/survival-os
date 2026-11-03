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

export type Installed = {
  id: string; title: string; category: string; bytes: number; version: string;
  checksum_source: string;
};
export type ContentEntry = {
  id: string; title: string; publisher: string; format: string; category: string; summary: string;
  bytes: number | null; bytes_status: string; license: string | null; license_status: string;
  checksum_status: string; date: string | null; installed: Installed | null;
  update: { version: string; bytes: number } | null;
};
export type ContentJob = {
  id: number; action: string; target: string; state: string; phase: string; bytes_done: number;
  bytes_total: number; error: string | null;
};
export type ContentOverview = {
  entries: ContentEntry[];
  imported: Installed[];
  jobs: ContentJob[];
  storage: {
    usable: number; available: number; floor: number; headroom: number; used: number;
    warning: boolean;
    categories: { id: string; name: string; cap_bytes: number; used_bytes: number }[];
  };
};
export type KiwixBook = { id: string; title: string; category: string; name: string };
export type UsbFile = { path: string; bytes: number; format: string };
export type ContentAction = "install" | "update" | "remove" | "validate";

export const getContent = () => load<ContentOverview>("/api/content");
export const getKiwixBooks = () => load<{ books: KiwixBook[] }>("/api/content/kiwix");
export const getUsb = () => load<{ mounted: boolean; files: UsbFile[] }>("/api/content/usb");
export const contentAction = (action: ContentAction, id: string, pin: string) =>
  send("/api/content/action", { action, id, pin });
export const checkUpdates = (pin: string) => send("/api/content/check-updates", { pin });
export const cancelJob = (id: number) => send(`/api/content/jobs/${id}/cancel`, {});
export const usbAction = (action: "mount" | "unmount", pin: string) =>
  send(`/api/content/usb/${action}`, { pin });
export const importFile = (path: string, category: string, pin: string) =>
  send("/api/content/import", { path, category, pin });

export type MapInfo = {
  id: string; title: string; version: string; kind: "base" | "terrain" | "imagery"; bbox: number[];
  max_zoom: number;
};
export type Waypoint = { id: number; name: string; lat: number; lon: number; notes: string };
export type Route = { id: number; name: string; points: [number, number][] };
export type NavigationData = { waypoints: Waypoint[]; routes: Route[] };

async function remove(path: string): Promise<void> {
  const response = await fetch(path, { method: "DELETE" });
  if (!response.ok) throw new Error("Request failed");
}

export const getMaps = () => load<{ maps: MapInfo[] }>("/api/maps");
export const getNavigation = () => load<NavigationData>("/api/navigation");
export const addWaypoint = (name: string, lat: number, lon: number) =>
  send("/api/navigation/waypoints", { name, lat, lon });
export const deleteWaypoint = (id: number) => remove(`/api/navigation/waypoints/${id}`);
export const deleteRoute = (id: number) => remove(`/api/navigation/routes/${id}`);
export const getGpxFiles = () => load<{ files: string[] }>("/api/navigation/usb");
export const exportGpxToUsb = (pin: string) => send("/api/navigation/export-usb", { pin });
export async function importGpx(path: string): Promise<{ waypoints: number; routes: number }> {
  const response = await fetch("/api/navigation/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Import failed");
  return data;
}

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
