"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";

// Sign-out only counts once the server has revoked the session. Until then the cookie
// stays in place (so revocation can be retried) and the page says so plainly.
function failureMessage(status: number): string {
  if (status === 502) return "The server could not record the sign-out right now. Try again in a moment.";
  if (status === 403) return "The sign-out request failed a security check. Reload the page, then sign out again.";
  return `Sign-out failed (error ${status}). Try again in a moment.`;
}

export default function SignOutButton() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signOut() {
    setBusy(true);
    setError(null);
    let response: Response;
    try {
      response = await apiFetch("/auth/logout", { method: "POST" });
    } catch (failure) {
      setError(
        failure instanceof TypeError
          ? "Sign-out did not reach the server. Check your connection, then try again."
          : failure instanceof Error
            ? failure.message
            : "Sign-out could not be completed. Try again in a moment.",
      );
      setBusy(false);
      return;
    }
    if (response.status === 204) {
      // A full navigation (not a client route change) drops workspace data held in memory.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?signedOut=1");
      return;
    }
    setError(failureMessage(response.status));
    setBusy(false);
  }

  return (
    <>
      <button
        type="button"
        onClick={signOut}
        disabled={busy}
        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
      >
        {busy ? "Signing out…" : "Sign out"}
      </button>
      {error && (
        <div className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md rounded-lg border border-red-200 bg-white p-4 text-sm shadow-lg">
          <div role="alert">
            <p className="font-semibold text-red-800">You are still signed in.</p>
            <p className="mt-1 leading-relaxed text-slate-700">{error}</p>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={signOut}
              disabled={busy}
              className="rounded-md bg-slate-900 px-3 py-1.5 font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {busy ? "Signing out…" : "Try sign-out again"}
            </button>
            <button
              type="button"
              onClick={() => setError(null)}
              className="rounded-md border border-slate-300 px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-100"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </>
  );
}
