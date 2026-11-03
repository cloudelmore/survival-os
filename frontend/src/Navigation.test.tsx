import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Navigation from "./Navigation";

const engine = vi.hoisted(() => ({
  center: vi.fn(() => ({ lat: 35.5, lon: -80.25, zoom: 9 })),
  show: vi.fn(),
  flyTo: vi.fn(),
  setData: vi.fn(),
  destroy: vi.fn(),
}));
const createMap = vi.hoisted(() => vi.fn());
vi.mock("./mapEngine", () => ({ createMap }));

const map = { id: "map-nc", title: "North Carolina", version: "20261101", kind: "base", bbox: [-84, 33, -75, 36], max_zoom: 15 };
let navigation = { waypoints: [{ id: 1, name: "Cabin", lat: 35, lon: -80, notes: "" }], routes: [] };
let maps = [map];
const calls: { url: string; method: string; body: string }[] = [];

beforeEach(() => {
  calls.length = 0;
  maps = [map];
  navigation = { waypoints: [{ id: 1, name: "Cabin", lat: 35, lon: -80, notes: "" }], routes: [] };
  engine.flyTo.mockClear();
  createMap.mockReset();
  createMap.mockImplementation((_box, _info, _overlays, onMove) => {
    onMove(engine.center());
    return engine;
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: String(init?.body ?? "") });
    const data = url === "/api/maps" ? { maps } : url === "/api/navigation" ? navigation
      : url === "/api/content/usb" ? { mounted: false, files: [] } : {};
    return new Response(JSON.stringify(data), { status: 200 });
  }));
});

it("offers the Content Manager when no map is installed", async () => {
  maps = [];
  render(<Navigation />);
  expect(await screen.findByText("NO MAP INSTALLED YET")).toBeTruthy();
  expect(createMap).not.toHaveBeenCalled();
});

it("shows the map position and flies to a waypoint", async () => {
  render(<Navigation />);
  expect(await screen.findByText("35.50000°N 80.25000°W")).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "Cabin" }));
  expect(engine.flyTo).toHaveBeenCalledWith(-80, 35);
});

it("marks the map center with a default name, so no keyboard is needed", async () => {
  render(<Navigation />);
  fireEvent.click(await screen.findByRole("button", { name: "MARK CENTER" }));
  await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
  const post = calls.find((call) => call.method === "POST");
  expect(post?.url).toBe("/api/navigation/waypoints");
  expect(JSON.parse(post?.body ?? "")).toEqual({ name: "Waypoint 2", lat: 35.5, lon: -80.25 });
});

it("needs a second press to delete", async () => {
  render(<Navigation />);
  fireEvent.click(await screen.findByRole("button", { name: "X" }));
  expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  fireEvent.click(await screen.findByRole("button", { name: "SURE?" }));
  await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
});

it("offers overlays as switches, never as map regions", async () => {
  maps = [map, { ...map, id: "terrain", title: "Terrain", kind: "terrain" },
    { ...map, id: "photos", title: "Photos", kind: "imagery" }];
  render(<Navigation />);
  fireEvent.click(await screen.findByRole("button", { name: "[ ] CONTOURS" }));
  expect(engine.show).toHaveBeenCalledWith("terrain", true);
  expect(await screen.findByRole("button", { name: "[X] CONTOURS" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "[ ] PHOTOS" }));
  expect(engine.show).toHaveBeenCalledWith("imagery", true);
  expect(screen.queryByRole("combobox")).toBeNull();
});
