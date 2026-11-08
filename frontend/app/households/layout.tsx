import type { Metadata } from "next";

import AccessUnavailable from "@/components/AccessUnavailable";
import { requirePageSession } from "@/lib/server/page-access";

export const metadata: Metadata = {
  title: "Households",
};

export default async function HouseholdsLayout({ children }: { children: React.ReactNode }) {
  const access = await requirePageSession("/households");
  if (access !== "granted") return <AccessUnavailable reason={access} />;
  return children;
}
