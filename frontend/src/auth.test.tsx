// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./auth";
import { getToken, type User } from "./api";

const analyst = { id: "1", username: "analyst", role: "analyst" } as unknown as User;

function Probe() {
  const { user, loading, notice, logout } = useAuth();
  const state = loading ? "loading" : user ? `signed-in:${user.username}` : "signed-out";
  return (
    <div>
      <p data-testid="state">{state}</p>
      <p data-testid="notice">{notice ?? ""}</p>
      <button onClick={logout}>sign out</button>
    </div>
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function renderAuth() {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

function goOnline() {
  return act(async () => {
    window.dispatchEvent(new Event("online"));
  });
}

/** Minimal in-memory Storage. Node's experimental global localStorage shadows jsdom's, so it is not used. */
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => Array.from(items.keys())[index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  };
}

describe("AuthProvider session restore", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
    localStorage.setItem("cerberus_token", "token-1");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps the token but stays signed out when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("signed-out"));
    expect(screen.getByTestId("notice").textContent).toMatch(/could not be reached/);
    expect(getToken()).toBe("token-1");
  });

  it("restores the session on reconnect only after /auth/me succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(200, analyst));
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("signed-out"));
    await goOnline();

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("signed-in:analyst"));
    expect(screen.getByTestId("notice").textContent).toBe("");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stays signed out when the server is still unreachable after reconnect", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("signed-out"));
    await goOnline();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("state").textContent).toBe("signed-out");
    expect(screen.getByTestId("notice").textContent).toMatch(/could not be reached/);
    expect(getToken()).toBe("token-1");
  });

  it("clears the token when the server rejects the session with 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Invalid token" })));
    renderAuth();

    // The 401 also fires the expiry event, which discards this check, so the expiry notice is shown.
    await waitFor(() => expect(screen.getByTestId("notice").textContent).toBe("Your session has expired. Sign in again."));
    expect(screen.getByTestId("state").textContent).toBe("signed-out");
    expect(getToken()).toBeNull();
  });

  it("clears the token when the server rejects the session with 403", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(403, { detail: "Forbidden" })));
    renderAuth();

    await waitFor(() => expect(screen.getByTestId("notice").textContent).toBe("Your session has ended. Sign in again."));
    expect(getToken()).toBeNull();
  });

  it("does not re-check on reconnect after the session was rejected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Invalid token" }));
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();

    await waitFor(() => expect(getToken()).toBeNull());
    await goOnline();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("state").textContent).toBe("signed-out");
  });

  it("does not restore a session that resolves after logout", async () => {
    const pending = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(pending.promise));
    renderAuth();

    fireEvent.click(screen.getByRole("button", { name: "sign out" }));
    await act(async () => {
      pending.resolve(jsonResponse(200, analyst));
    });

    expect(screen.getByTestId("state").textContent).toBe("signed-out");
    expect(screen.getByTestId("notice").textContent).toBe("You have signed out.");
    expect(getToken()).toBeNull();
  });
});

describe("AuthProvider retry while online", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("localStorage", memoryStorage());
    localStorage.setItem("cerberus_token", "token-1");
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("revalidates when the API comes back, without any offline or online event", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(200, analyst));
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("state").textContent).toBe("signed-out");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("state").textContent).toBe("signed-in:analyst");
  });

  it("backs off between retries while the API stays down", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_999);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("state").textContent).toBe("signed-out");
    expect(getToken()).toBe("token-1");
  });

  it("stops retrying after logout", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    renderAuth();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "sign out" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("notice").textContent).toBe("You have signed out.");
  });
});
