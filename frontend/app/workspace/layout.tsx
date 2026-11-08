import type { Metadata } from "next";

import AccessUnavailable from "@/components/AccessUnavailable";
import { requirePageSession } from "@/lib/server/page-access";

export const metadata: Metadata = {
  title: "Workspace",
};

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const access = await requirePageSession("/workspace");
  if (access !== "granted") return <AccessUnavailable reason={access} />;
  return children;
}
