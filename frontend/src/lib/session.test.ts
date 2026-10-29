import { describe, expect, it, vi, afterEach } from "vitest";
import { ApiError, fetchText } from "../api";
import { classifySessionFailure } from "./session";

describe("classifySessionFailure", () => {
  it("treats 401 and 403 as a rejected session", () => {
    expect(classifySessionFailure(new ApiError(401, "x"))).toBe("rejected");
    expect(classifySessionFailure(new ApiError(403, "x"))).toBe("rejected");
  });

  it("treats other server errors as errors that keep the token", () => {
    expect(classifySessionFailure(new ApiError(500, "x"))).toBe("error");
    expect(classifySessionFailure(new ApiError(503, "x"))).toBe("error");
  });

  it("treats a failed request with no response as unreachable", () => {
    expect(classifySessionFailure(new TypeError("Failed to fetch"))).toBe("unreachable");
  });
});

describe("fetchText", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the body on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>report</html>", { status: 200 })));
    await expect(fetchText("/jobs/1/report")).resolves.toBe("<html>report</html>");
  });

  it("throws the server's detail on error and never returns the error body as content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Report unavailable" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(fetchText("/jobs/1/report")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Report unavailable",
    });
  });
});
