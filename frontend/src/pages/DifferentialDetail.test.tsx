// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DifferentialDetail } from "./DifferentialDetail";

const failed = {
  id: 1,
  sample_id: 1,
  executor: "simulated",
  baseline_conditions: { internet: true },
  status: "failed",
  created_by: null,
  created_at: "2026-10-28T12:00:00Z",
  finished_at: "2026-10-28T12:00:05Z",
  error_message: "Baseline run failed. The other runs were not compared.",
  findings: [],
};

vi.mock("../api", () => ({
  api: {
    get: vi.fn((path: string) =>
      path.startsWith("/differential/") ? Promise.resolve(failed) : Promise.resolve({ id: 1, filename: "s.bin" })
    ),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/differential/1"]}>
      <Routes>
        <Route path="/differential/:id" element={<DifferentialDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("DifferentialDetail failure panel", () => {
  afterEach(() => cleanup());

  it("shows the sanitized failure message in an error panel", async () => {
    const { container } = renderPage();

    expect(await screen.findByText("Analysis failed")).toBeTruthy();
    expect(await screen.findByText(/Baseline run failed\. The other runs were not compared\./)).toBeTruthy();
    const text = container.textContent ?? "";
    expect(text).not.toContain("/Users/");
    expect(text).not.toContain("scripted");
  });
});

describe("DifferentialDetail without a failure", () => {
  afterEach(() => cleanup());

  it("does not show the failure panel for a completed analysis", async () => {
    const { api } = await import("../api");
    vi.mocked(api.get).mockImplementationOnce(() =>
      Promise.resolve({ ...failed, status: "completed", error_message: null })
    );
    renderPage();

    await screen.findByText("No changes recorded");
    expect(screen.queryByText("Analysis failed")).toBeNull();
  });
});
