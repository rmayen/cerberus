import { ApiError } from "../api";

/**
 * What a failed session check (GET /auth/me) means:
 * - "rejected": the server says the session is invalid or forbidden. Clear it.
 * - "unreachable": no response arrived (network down, server stopped). Keep the token,
 *   but do not treat the user as signed in until a later check succeeds.
 * - "error": the server answered with another error. Keep the token and show the message.
 */
export type SessionFailure = "rejected" | "unreachable" | "error";

export function classifySessionFailure(err: unknown): SessionFailure {
  if (err instanceof ApiError) {
    return err.status === 401 || err.status === 403 ? "rejected" : "error";
  }
  return "unreachable";
}

export const SESSION_MESSAGES = {
  rejected: "Your session has ended. Sign in again.",
  unreachable: "The server could not be reached. Check that the API is running, then sign in again.",
} as const;
