import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

it("shows backend health", async () => {
  vi.stubGlobal("fetch", async () => new Response('{"status":"ok","version":"1.2.3"}'));
  render(<App />);
  expect(await screen.findByText("Backend ok, version 1.2.3")).toBeTruthy();
});

it("reports an unavailable backend", async () => {
  vi.stubGlobal("fetch", async () => new Response("", { status: 503 }));
  render(<App />);
  expect(await screen.findByRole("alert")).toBeTruthy();
});
