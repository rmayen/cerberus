// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

const POLL_MS = 2000;

function analysis(status: string, extra: Record<string, unknown> = {}) {
  return { ...failed, status, error_message: null, findings: [], ...extra };
}

/** Advance one poll interval at a time, so React commits each re-read before the next timer. */
async function advancePolls(count: number): Promise<void> {
  for (let i = 0; i < count; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
  }
}

async function detailReads(): Promise<number> {
  const { api } = await import("../api");
  return vi.mocked(api.get).mock.calls.filter(([path]) => String(path).startsWith("/differential/")).length;
}

describe("DifferentialDetail polling", () => {
  beforeEach(async () => {
    const { api } = await import("../api");
    vi.mocked(api.get).mockClear();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("re-reads a queued analysis through running until it completes, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = await import("../api");
    const sequence = [analysis("pending"), analysis("running")];
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (!path.startsWith("/differential/")) return Promise.resolve({ id: 1, filename: "s.bin" });
      return Promise.resolve(sequence.length ? sequence.shift() : analysis("completed"));
    });

    renderPage();
    expect(await screen.findByText("Analysis queued")).toBeTruthy();

    await advancePolls(4);
    expect(await screen.findByText("No changes recorded")).toBeTruthy();
    const settled = await detailReads();
    await advancePolls(5);
    expect(await detailReads()).toBe(settled); // terminal: no further reads
  });

  it("stops polling when the page unmounts", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = await import("../api");
    vi.mocked(api.get).mockImplementation((path: string) =>
      Promise.resolve(path.startsWith("/differential/") ? analysis("pending") : { id: 1, filename: "s.bin" })
    );

    const view = renderPage();
    expect(await screen.findByText("Analysis queued")).toBeTruthy();
    await advancePolls(1);
    view.unmount();
    const atUnmount = await detailReads();
    await advancePolls(5);
    expect(await detailReads()).toBe(atUnmount);
  });

  it("stops polling after an authentication failure", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = await import("../api");
    let reads = 0;
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (!path.startsWith("/differential/")) return Promise.resolve({ id: 1, filename: "s.bin" });
      reads += 1;
      if (reads === 1) return Promise.resolve(analysis("pending"));
      return Promise.reject(Object.assign(new Error("Your session is no longer valid. Sign in again."), { status: 401 }));
    });

    renderPage();
    expect(await screen.findByText("Analysis queued")).toBeTruthy();
    await advancePolls(1); // the re-read is rejected as an expired session
    expect(await screen.findByText(/no longer valid/)).toBeTruthy();
    const atFailure = await detailReads();
    await advancePolls(5);
    expect(await detailReads()).toBe(atFailure);
  });

  it("does not poll a finished analysis", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = await import("../api");
    vi.mocked(api.get).mockImplementation((path: string) =>
      Promise.resolve(path.startsWith("/differential/") ? analysis("failed") : { id: 1, filename: "s.bin" })
    );

    renderPage();
    expect(await screen.findByText("Analysis failed")).toBeTruthy();
    await advancePolls(5);
    expect(await detailReads()).toBe(1);
  });
});

describe("DifferentialDetail state copy", () => {
  afterEach(() => cleanup());

  it("says a cancelled analysis made no comparison, not that nothing changed", async () => {
    const { api } = await import("../api");
    vi.mocked(api.get).mockImplementationOnce(() => Promise.resolve(analysis("cancelled", { error_message: "cancelled before start" })));
    renderPage();

    expect(await screen.findByText("Analysis cancelled")).toBeTruthy();
    expect(screen.getByText("No comparison made")).toBeTruthy();
    expect(screen.queryByText("No changes recorded")).toBeNull();
  });
});
