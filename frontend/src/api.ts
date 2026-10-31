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
