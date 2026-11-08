import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import LoginForm from "@/components/LoginForm";
import { pageSessionState } from "@/lib/server/page-access";

export const metadata: Metadata = { title: "Sign in" };

const PROTECTED = ["/workspace", "/households"];

// Only return to this site's own protected pages after sign-in (no open redirects).
function safeNext(value: string | string[] | undefined): string {
  const next = typeof value === "string" ? value : "";
  return PROTECTED.some((p) => next === p || next.startsWith(`${p}?`)) ? next : "/workspace";
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const next = safeNext(params.next);
  // Skip the form only for a session the API confirms; a signed-out cookie stays here.
  const state = await pageSessionState();
  if (state === "granted" && params.signedOut === undefined) redirect(next);
  const configured = state !== "misconfigured";

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 font-sans text-slate-900">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <Link href="/" className="text-sm font-semibold tracking-tight text-slate-900">
          AdvisorLens
        </Link>
        <h1 className="mt-4 text-xl font-semibold">Sign in to the demo workspace</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          This is a shared demonstration workspace with fictional data. Everyone who signs in with the demo
          password sees and edits the same analyses, households and reports.
        </p>
        {params.signedOut !== undefined && (
          <p role="status" className="mt-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
            You have been signed out.
          </p>
        )}
        {configured ? (
          <LoginForm next={next} />
        ) : (
          <p role="alert" className="mt-6 rounded-md bg-red-50 p-3 text-sm text-red-800">
            Access protection is not configured on this server, so sign-in is disabled.
          </p>
        )}
      </div>
    </main>
  );
}
