import type { PageAccess } from "@/lib/server/page-access";

export default function AccessUnavailable({ reason }: { reason: Exclude<PageAccess, "granted"> }) {
  return (
    <main className="mx-auto max-w-xl px-6 py-24 font-sans text-slate-800">
      <h1 className="text-2xl font-semibold">Workspace unavailable</h1>
      <p role="alert" className="mt-3 text-slate-600">
        {reason === "misconfigured"
          ? "Access protection is not configured on this server, so the workspace stays closed. An administrator needs to set the security configuration."
          : "The analysis service could not confirm your session. Try again shortly."}
      </p>
    </main>
  );
}
