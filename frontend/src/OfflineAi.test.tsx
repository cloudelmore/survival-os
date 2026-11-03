import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OfflineAi } from "./OfflineAi";

const source = { number: 1, document_id: 7, title: "Knots", page: 3, label: null, text: "A bowline holds." };
let status = { runtime_installed: true, model_installed: true, ready: true };
let events: object[] = [];

beforeEach(() => {
  status = { runtime_installed: true, model_installed: true, ready: true };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/ai/status") return new Response(JSON.stringify(status));
    return new Response(events.map((event) => `${JSON.stringify(event)}\n`).join(""));
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ask = async () => {
  render(<OfflineAi />);
  fireEvent.change(screen.getByRole("textbox", { name: "Question" }), { target: { value: "bowline?" } });
  fireEvent.click(screen.getByRole("button", { name: "ASK" }));
};

it("offers install when the AI is absent", async () => {
  status = { runtime_installed: false, model_installed: false, ready: false };
  render(<OfflineAi />);
  expect((await screen.findByRole("link", { name: "Open the Content Manager" })).getAttribute("href"))
    .toBe("#/content-manager");
});

it("needs a press to start the AI, which is off", async () => {
  status = { ...status, ready: false };
  render(<OfflineAi />);
  expect(await screen.findByRole("button", { name: "START AI" })).toBeTruthy();
});

it("links citations to the passage in the viewer", async () => {
  events = [{ type: "sources", mode: "answer", sources: [source] },
    { type: "text", text: "It holds " }, { type: "text", text: "[1]." }, { type: "done" }];
  await ask();
  expect((await screen.findByRole("link", { name: "[1]" })).getAttribute("href"))
    .toBe("#/viewer/7?page=3&hl=");
});

it("shows sources, without an answer, on a restricted topic", async () => {
  events = [{ type: "sources", mode: "restricted", sources: [source] }, { type: "done" }];
  await ask();
  expect(await screen.findByText(/THE AI DOES NOT ANSWER THESE/)).toBeTruthy();
  expect(screen.getByText("A bowline holds.")).toBeTruthy();
});

it("takes a written answer back off the screen when it is withheld", async () => {
  events = [{ type: "sources", mode: "answer", sources: [source] }, { type: "text", text: "Unsourced." },
    { type: "withheld", reason: "uncited" }, { type: "done" }];
  await ask();
  expect(await screen.findByText(/COULD NOT BE TRACED/)).toBeTruthy();
  await waitFor(() => expect(screen.queryByText("Unsourced.")).toBeNull());
});
