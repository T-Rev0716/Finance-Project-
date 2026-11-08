"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";

export default function SignOutButton() {
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } finally {
      // The cookie is cleared even if the server could not record the sign-out. A full
      // navigation (not a client route change) drops workspace data held in memory.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?signedOut=1");
    }
  }

  return (
    <button
      type="button"
      onClick={signOut}
      disabled={busy}
      className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
    >
      {busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
