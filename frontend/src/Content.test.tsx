import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";

const ENTRY = {
  id: "water", title: "Water Library", publisher: "Kiwix", format: "zim",
  category: "medical_survival", summary: "Water treatment", bytes: 2e7, bytes_status: "verified",
  license: null, license_status: "unverified", checksum_status: "verified", date: "2024-08-29",
  installed: null, update: null,
};
const OVERVIEW = {
  entries: [ENTRY],
  imported: [],
  jobs: [{ id: 1, action: "install", target: "other", state: "running", phase: "downloading",
    bytes_done: 5e6, bytes_total: 2e7, error: null }],
  storage: {
    usable: 974e9, available: 960e9, floor: 146e9, headroom: 814e9, used: 14e9, warning: false,
    categories: [{ id: "os_apps", name: "OS, applications, system files", cap_bytes: 45e9, used_bytes: 9e9 }],
  },
};
let posts: { path: string; body: string }[];
let reply: Response;

beforeEach(() => {
  posts = [];
  reply = new Response("{}", { status: 202 });
  vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") { posts.push({ path, body: init.body as string }); return reply; }
    if (path === "/api/content") return new Response(JSON.stringify(OVERVIEW));
    if (path === "/api/content/usb") return new Response(JSON.stringify({ mounted: false, files: [] }));
    if (path === "/api/content/kiwix") {
      return new Response(JSON.stringify({ books: [
        { id: "a", title: "Water Library", category: "medical_survival", name: "water_2024" },
        { id: "b", title: "Ham Radio", category: "radio", name: "ham_2026" },
      ] }));
    }
    return new Response("{}");
  });
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const openManager = () => {
  window.location.hash = "/content-manager";
  render(<App />);
};

it("shows usage by category and job progress", async () => {
  openManager();
  expect(await screen.findByText("OS, applications, system files")).toBeTruthy();
  expect(screen.getByText(/814.00 GB can still be installed/)).toBeTruthy();
  expect(screen.getByText(/downloading 25%/)).toBeTruthy();
});

it("asks for the PIN before installing", async () => {
  openManager();
  fireEvent.click(await screen.findByText("INSTALL"));
  expect(posts).toEqual([]);
  fireEvent.change(screen.getByLabelText("Enter admin PIN"), { target: { value: "1234" } });
  fireEvent.click(screen.getByText("OK"));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(JSON.parse(posts[0].body)).toEqual({ action: "install", id: "water", pin: "1234" });
});

it("shows why the storage rules refused", async () => {
  reply = new Response(JSON.stringify({ detail: "Needs 2 GB above the 15% free floor" }), { status: 507 });
  openManager();
  fireEvent.click(await screen.findByText("INSTALL"));
  fireEvent.change(screen.getByLabelText("Enter admin PIN"), { target: { value: "1234" } });
  fireEvent.click(screen.getByText("OK"));
  expect(await screen.findByText(/15% free floor/)).toBeTruthy();
});

it("lists only the section's collections and opens them in the Kiwix origin", async () => {
  window.location.hash = "/communications";
  render(<App />);
  const link = await screen.findByText("Ham Radio");
  expect(screen.queryByText("Water Library")).toBeNull();
  fireEvent.click(link);
  window.location.hash = "/kiwix?book=ham_2026";
  cleanup();
  render(<App />);
  expect(screen.getByTitle("Kiwix").getAttribute("src")).toMatch(/:8083\/content\/ham_2026$/);
});

it("closes Kiwix to where it was opened from", async () => {
  window.location.hash = "/kiwix?book=ham_2026&from=communications";
  render(<App />);
  fireEvent.click(screen.getByText("CLOSE"));
  expect(window.location.hash).toBe("#/communications");
});

it("hands a library search to Kiwix", async () => {
  window.location.hash = "/kiwix?q=water";
  render(<App />);
  expect(screen.getByTitle("Kiwix").getAttribute("src")).toMatch(/:8083\/search\?pattern=water$/);
});
