import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { SECTIONS } from "./sections";

const STATUS = {
  cpu_percent: 12.5,
  memory: { total_bytes: 8e9, available_bytes: 7e9 },
  temperature_c: 51.2,
  uptime_seconds: 3700,
  storage: { usable_bytes: 974e9, available_bytes: 968e9, used_bytes: 6e9, floor_bytes: 146e9 },
  power: {
    input_volts: 5.13,
    supply_current_ma: 5000,
    throttling: { now: [], since_boot: ["under_voltage"] },
  },
  services: { "survival-api": "active", "survival-kiosk": "inactive" },
};

let requests: { path: string; body?: string }[];
let admin: { pin_set: boolean; actions_enabled: boolean };
let actionResponse: Response;

beforeEach(() => {
  window.location.hash = "";
  requests = [];
  admin = { pin_set: true, actions_enabled: true };
  actionResponse = new Response("{}", { status: 202 });
  vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
    requests.push({ path, body: init?.body as string });
    if (path === "/api/status") return new Response(JSON.stringify(STATUS));
    if (path === "/api/admin/state") return new Response(JSON.stringify(admin));
    if (path === "/api/admin/pin") return new Response(null, { status: 204 });
    if (path === "/api/content/kiwix") return new Response(JSON.stringify({ books: [] }));
    return actionResponse;
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const key = (name: string) => fireEvent.keyDown(window, { key: name });
const heading = (name: string) => screen.findByRole("heading", { name });
const tick = () => new Promise((resolve) => setTimeout(resolve, 20));

it("lists all ten sections and focuses the first", () => {
  render(<App />);
  const menu = within(screen.getByRole("navigation"));
  expect(menu.getAllByRole("button")).toHaveLength(10);
  for (const section of SECTIONS) expect(menu.getByText(section.title)).toBeTruthy();
  expect(document.activeElement?.textContent).toContain("Knowledge");
});

it("opens sections with number keys, with 0 as the tenth", async () => {
  render(<App />);
  key("2");
  expect(await heading("Medical")).toBeTruthy();
  key("Escape");
  expect(await heading("SURVIVAL OS")).toBeTruthy();
  key("0");
  expect(await heading("System Status")).toBeTruthy();
});

it("moves through the menu with arrow keys", () => {
  render(<App />);
  key("ArrowDown");
  expect(document.activeElement?.textContent).toContain("Medical");
  key("ArrowRight");
  expect(document.activeElement?.textContent).toContain("Offline AI");
  key("ArrowLeft");
  key("ArrowUp");
  key("ArrowUp");
  expect(document.activeElement?.textContent).toContain("Knowledge");
});

it("returns focus to the section the user came from", async () => {
  render(<App />);
  key("3");
  await heading("Navigation");
  key("Escape");
  await heading("SURVIVAL OS");
  expect(document.activeElement?.textContent).toContain("Navigation");
});

it("says plainly when a section has no content", async () => {
  render(<App />);
  key("1");
  await heading("Knowledge");
  expect(await screen.findByText("NOTHING INSTALLED HERE YET")).toBeTruthy();
});

it("shows real telemetry and no battery", async () => {
  render(<App />);
  key("0");
  expect(await screen.findByText("51.2 C")).toBeTruthy();
  expect(screen.getByText("5.13 V")).toBeTruthy();
  expect(screen.getByText("Under-voltage")).toBeTruthy();
  expect(document.body.textContent?.toLowerCase()).not.toContain("battery");
});

it("shows missing telemetry as not available", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({
    ...STATUS,
    temperature_c: null,
    storage: null,
    power: { input_volts: null, supply_current_ma: null, throttling: null },
  })));
  render(<App />);
  key("0");
  await screen.findByText("Uptime");
  expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(5);
});

it("reports an unavailable backend", async () => {
  vi.stubGlobal("fetch", async () => new Response("", { status: 503 }));
  render(<App />);
  key("0");
  expect(await screen.findByRole("alert")).toBeTruthy();
});

async function openPin(label: string) {
  render(<App />);
  key("p");
  fireEvent.click(await screen.findByRole("button", { name: label }));
  await tick();
  await screen.findByRole("button", { name: "Confirm" });
}

const tap = (...keys: string[]) =>
  keys.forEach((name) => fireEvent.click(screen.getByRole("button", { name })));

it("needs a PIN of at least four digits, entered by touch", async () => {
  await openPin("Reboot");
  tap("1", "2", "3");
  expect((screen.getByRole("button", { name: "Confirm" }) as HTMLButtonElement).disabled).toBe(true);
  tap("4");
  expect((screen.getByRole("button", { name: "Confirm" }) as HTMLButtonElement).disabled).toBe(false);
  tap("Confirm");
  expect(await screen.findByRole("status")).toBeTruthy();
  expect(requests.at(-1)).toEqual({
    path: "/api/system/action",
    body: JSON.stringify({ action: "reboot", pin: "1234" }),
  });
});

it("sets the PIN on first use, then runs the action", async () => {
  admin.pin_set = false;
  await openPin("Maintenance mode");
  expect(screen.getByText(/Choose an admin PIN/)).toBeTruthy();
  tap("9", "8", "7", "6", "Confirm");
  await screen.findByRole("status");
  expect(requests.map((item) => item.path).slice(-2)).toEqual(["/api/admin/pin", "/api/system/action"]);
});

it("shows a refused PIN and clears the entry", async () => {
  actionResponse = new Response('{"detail":"Wrong PIN"}', { status: 403 });
  await openPin("Shut down");
  tap("1", "1", "1", "1", "Confirm");
  expect((await screen.findByRole("alert")).textContent).toBe("Wrong PIN");
  expect((screen.getByLabelText(/admin PIN/) as HTMLInputElement).value).toBe("");
});

it("ignores number keys while the dialog is open", async () => {
  await openPin("Reboot");
  key("3");
  expect(screen.queryByRole("heading", { name: "Navigation" })).toBeNull();
});
