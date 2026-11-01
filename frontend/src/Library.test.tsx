import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { markTerms } from "./highlight";

const STATUS = {
  documents: 2, passages: 9, pages_total: 12, pages_done: 12, pending: 0, failed: [], no_text: [],
  formats: {}, categories: {}, indexer: { state: "idle", detail: "" },
};
const RESULT = {
  document_id: 7, title: "Field Manual", format: "epub", category: "medical_survival",
  path: "x.epub", page: 2, label: "Fire", pages_total: 3, hits: ["tinder"],
  snippet: [{ text: "Keep ", hit: false }, { text: "tinder", hit: true }, { text: " dry", hit: false }],
};
let requests: string[];

const json = (value: unknown) => new Response(JSON.stringify(value));

beforeEach(() => {
  requests = [];
  window.location.hash = "/library-search";
  vi.stubGlobal("fetch", async (path: string) => {
    requests.push(path);
    if (path.startsWith("/api/library/status")) return json(STATUS);
    if (path.startsWith("/api/library/search")) {
      return json({ results: path.includes("nothing") ? [] : [RESULT],
        total: path.includes("nothing") ? 0 : 1, more: false });
    }
    if (path.includes("/view")) {
      return json({ kind: "html", html: `<p>page ${new URL(path, "http://x").searchParams.get("page")}: tinder and Tinder</p>` });
    }
    return json({ id: 7, title: "Field Manual", format: "epub", category: "x", pages_total: 3 });
  });
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const search = async (text: string) => {
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Search the library"), { target: { value: text } });
  fireEvent.submit(screen.getByRole("search"));
};

it("shows a highlighted snippet that links to the location", async () => {
  await search("tinder");
  const hit = await screen.findByText("tinder");
  expect(hit.tagName).toBe("MARK");
  expect(hit.closest("a")?.getAttribute("href")).toBe("#/viewer/7?page=2&hl=tinder");
  expect(screen.getByText(/EPUB · Fire/)).toBeTruthy();
});

it("passes filters to the search and keeps the query in the address", async () => {
  await search("tinder");
  await screen.findByText("tinder");
  fireEvent.change(screen.getByLabelText("Format"), { target: { value: "pdf" } });
  await waitFor(() => expect(requests.some((path) => path.includes("format=pdf"))).toBe(true));
  expect(window.location.hash).toContain("q=tinder");
});

it("says so when nothing matches", async () => {
  await search("nothing");
  expect(await screen.findByText("NO MATCHES")).toBeTruthy();
});

it("states that encyclopedias are searched separately", async () => {
  render(<App />);
  expect(await screen.findByText(/Encyclopedias have their own search/)).toBeTruthy();
});

it("opens at the location, marks hits and turns pages", async () => {
  window.location.hash = "/viewer/7?page=2&hl=tinder";
  render(<App />);
  expect(await screen.findByText("2/3")).toBeTruthy();
  await waitFor(() => expect(document.querySelectorAll("mark")).toHaveLength(2));
  expect(document.querySelector("mark.current")?.textContent).toBe("tinder");
  fireEvent.click(screen.getByLabelText("Next match"));
  expect(document.querySelector("mark.current")?.textContent).toBe("Tinder");
  fireEvent.keyDown(window, { key: "ArrowRight" });
  await screen.findByText("3/3");
  await waitFor(() => expect(requests).toContain("/api/library/documents/7/view?page=3"));
});

it("marks whole words only, without treating terms as patterns", () => {
  const root = document.createElement("div");
  root.innerHTML = "<p>water watershed a.b axb</p>";
  expect(markTerms(root, ["water", "a.b"]).map((mark) => mark.textContent)).toEqual(["water", "a.b"]);
  expect(root.textContent).toBe("water watershed a.b axb");
});
