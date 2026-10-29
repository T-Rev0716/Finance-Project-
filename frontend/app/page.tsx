import Link from "next/link";
import type { ReactNode } from "react";

type Severity = "high" | "medium" | "info";

const SEVERITY_STYLES: Record<Severity, string> = {
  high: "bg-red-100 text-red-800 border-red-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  info: "bg-sky-100 text-sky-800 border-sky-200",
};

const NAV_LINKS = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#review-rules", label: "Review rules" },
  { href: "#review-brief", label: "Review brief" },
  { href: "#compliance", label: "Compliance" },
];

// Real output for the bundled data/samples/growth_concentrated.csv.
const PREVIEW_ITEMS: { severity: Severity; title: string; detail: string; rule: string }[] = [
  {
    severity: "high",
    title: "Concentration review: NVDA",
    detail: "24.0% of portfolio · review threshold 20.0%",
    rule: "concentration_single_holding",
  },
  {
    severity: "medium",
    title: "Sector concentration review: Technology",
    detail: "56.1% of portfolio · review threshold 35.0%",
    rule: "concentration_sector",
  },
  {
    severity: "info",
    title: "Tax-related review consideration: PYPL",
    detail: "$1,800 unrealized loss in a taxable account",
    rule: "tax_review_taxable_loss",
  },
];

const PRINCIPLES = [
  {
    icon: <ListCheckIcon />,
    title: "Deterministic by default",
    body: "The same portfolio always produces the same review items. No black-box scoring.",
  },
  {
    icon: <LensIcon />,
    title: "Traceable evidence",
    body: "Each item carries its rule ID, threshold, and the exact values that triggered it.",
  },
  {
    icon: <ShieldCheckIcon />,
    title: "Advisor-support language",
    body: "Findings are framed as considerations for review. A runtime guard blocks direct-advice wording.",
  },
  {
    icon: <DocumentIcon />,
    title: "Complete audit trail",
    body: "Analyses, briefs, and rejected uploads are recorded in an append-only audit log.",
  },
];

const STEPS = [
  {
    title: "Load a portfolio",
    body: "Upload a holdings CSV or start from a preloaded sample. Every row is validated (schema, numeric fields, asset classes, account types) before analysis runs.",
    detail: "CSV upload · 3 samples included",
  },
  {
    title: "Run the review rules",
    body: "Five deterministic rules check concentration, sector exposure, cash levels, risk-profile alignment, and taxable unrealized losses. Each one shows its threshold and evidence.",
    detail: "5 rules · every threshold visible",
  },
  {
    title: "Prepare the brief",
    body: "Generate a nine-section Client Portfolio Review Brief for the meeting, then export it as Markdown, HTML, or a print-ready PDF.",
    detail: "Markdown · HTML · PDF",
  },
];

const RULES: { name: string; trigger: string; severity: Severity; id: string }[] = [
  {
    name: "Single-holding concentration",
    trigger: "Any non-cash holding above 20% of the portfolio",
    severity: "high",
    id: "concentration_single_holding",
  },
  {
    name: "Sector concentration",
    trigger: "Any non-cash sector above 35% of the portfolio",
    severity: "medium",
    id: "concentration_sector",
  },
  {
    name: "Cash drag",
    trigger: "Cash above 10% of the portfolio",
    severity: "medium",
    id: "cash_drag",
  },
  {
    name: "Risk-profile mismatch",
    trigger: "Conservative profile with equity above 60%",
    severity: "high",
    id: "risk_tolerance_mismatch",
  },
  {
    name: "Tax-related review consideration",
    trigger: "Unrealized loss in a taxable account",
    severity: "info",
    id: "tax_review_taxable_loss",
  },
];

const BRIEF_SECTIONS = [
  "Executive Summary",
  "Portfolio Snapshot",
  "Key Review Items",
  "Advisor Talking Points",
  "Client Discussion Questions",
  "Follow-Up Items",
  "Evidence Table",
  "Data Assumptions",
  "Compliance Disclaimer",
];

const BRIEF_POINTS = [
  "Review items map one-to-one to the rules that fired",
  "Cached per analysis and regenerable on demand",
  "Saved-analyses history with brief status and one-click exports",
];

const COMPLIANCE_POINTS = [
  {
    icon: <ShieldCheckIcon />,
    title: "Guarded language",
    body: "Every generated review item and brief passes a banned-phrase check for direct-advice wording before it is stored or shown.",
  },
  {
    icon: <HashIcon />,
    title: "Source integrity",
    body: "Each upload is fingerprinted with SHA-256, and every finding links back to the file and rule it came from.",
  },
  {
    icon: <SparkleIcon />,
    title: "Optional AI drafting, tightly bounded",
    body: "A language model can optionally rewrite the narrative sections only. Its draft is validated against the analysis, and any failure falls back to the rule-based brief.",
  },
  {
    icon: <DatabaseIcon />,
    title: "Synthetic data in this release",
    body: "No client data, brokerage connections, or market-data feeds. The bundled sample portfolios are synthetic by design.",
  },
];

const SAMPLES = ["Concentrated growth account", "Conservative profile, high equity", "Retiree account with elevated cash"];

export default function Landing() {
  return (
    <div className="flex min-h-screen flex-col bg-white font-sans text-slate-900">
      <SiteHeader />
      <main className="flex-1">
        <Hero />
        <Principles />
        <HowItWorks />
        <ReviewRules />
        <ReviewBrief />
        <Compliance />
        <FinalCta />
      </main>
      <SiteFooter />
    </div>
  );
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6">
        <Link href="/" className="flex items-center gap-2.5" aria-label="AdvisorLens home">
          <LogoMark />
          <span className="text-[17px] font-semibold tracking-tight">AdvisorLens</span>
        </Link>
        <nav className="hidden items-center gap-8 text-sm text-slate-600 md:flex">
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="transition-colors hover:text-slate-900">
              {link.label}
            </a>
          ))}
        </nav>
        <Link
          href="/workspace"
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-slate-700"
        >
          Open workspace
        </Link>
      </div>
    </header>
  );
}

function Hero() {
  const gridMask = "radial-gradient(ellipse 80% 70% at 50% 0%, black 25%, transparent 100%)";
  return (
    <section className="relative overflow-hidden border-b border-slate-200">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to right, #eef2f6 1px, transparent 1px), linear-gradient(to bottom, #eef2f6 1px, transparent 1px)",
          backgroundSize: "56px 56px",
          maskImage: gridMask,
          WebkitMaskImage: gridMask,
        }}
      />
      <div className="relative mx-auto grid max-w-6xl grid-cols-1 items-center gap-14 px-6 pb-20 pt-16 md:pt-24 lg:grid-cols-[1.05fr_1fr] lg:gap-12">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Portfolio review support for financial advisors
          </p>
          <h1 className="mt-6 text-4xl font-semibold tracking-tight text-balance sm:text-5xl lg:text-[3.4rem] lg:leading-[1.05]">
            Portfolio review prep, grounded in evidence.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-600">
            AdvisorLens runs a client portfolio through transparent, rule-based checks, surfaces
            the items worth discussing, and drafts a client-ready review brief. Every finding is
            traced to a named rule, its threshold, and the source file.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <PrimaryButton href="/workspace">Try a sample portfolio</PrimaryButton>
            <a
              href="#how-it-works"
              className="rounded-md border border-slate-300 bg-white px-5 py-3 text-sm font-medium text-slate-800 shadow-sm transition-colors hover:bg-slate-50"
            >
              See how it works
            </a>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-500">
            {["No account needed", "Synthetic sample data", "Markdown, HTML & PDF export"].map((text) => (
              <li key={text} className="flex items-center gap-2">
                <CheckIcon className="h-4 w-4 text-emerald-600" />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <ProductPreview />
      </div>
    </section>
  );
}

function ProductPreview() {
  return (
    <div className="relative isolate">
      <div
        aria-hidden="true"
        className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-br from-emerald-100/70 via-slate-100 to-sky-100/70 blur-2xl"
      />
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl shadow-slate-900/10">
        <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
          <span className="ml-3 min-w-0 truncate font-mono text-xs text-slate-500">growth_concentrated.csv</span>
          <span className="ml-auto shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
            Analysis complete
          </span>
        </div>
        <div className="space-y-4 p-5">
          <div className="grid grid-cols-3 gap-3">
            <PreviewStat label="Total value" value="$90,000" />
            <PreviewStat label="Unrealized G/L" value="+$22,200" tone="text-emerald-700" />
            <PreviewStat label="Review items" value="3" />
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Advisor review items
            </p>
            <ul className="space-y-2.5">
              {PREVIEW_ITEMS.map((item) => (
                <li key={item.rule} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-start gap-2 sm:items-center">
                    <SeverityPill severity={item.severity} />
                    <span className="min-w-0 text-sm font-medium sm:truncate">{item.title}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <span className="text-xs text-slate-600">{item.detail}</span>
                    <code className="font-mono text-[11px] text-slate-400">{item.rule}</code>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-900 px-4 py-3 text-white">
            <div>
              <p className="text-sm font-medium">Client Portfolio Review Brief</p>
              <p className="text-xs text-slate-400">9 sections · grounded in this analysis</p>
            </div>
            <div className="flex gap-1.5">
              {["MD", "HTML", "PDF"].map((format) => (
                <span
                  key={format}
                  className="rounded border border-white/15 bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-slate-300"
                >
                  {format}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
      <p className="mt-4 text-center text-xs text-slate-400">
        Actual output for the bundled <span className="font-mono">growth_concentrated.csv</span> sample
      </p>
    </div>
  );
}

function Principles() {
  return (
    <section className="border-b border-slate-200 bg-slate-50/70">
      <div className="mx-auto grid max-w-6xl gap-10 px-6 py-14 sm:grid-cols-2 lg:grid-cols-4">
        {PRINCIPLES.map((item) => (
          <div key={item.title}>
            <IconBadge>{item.icon}</IconBadge>
            <h3 className="mt-4 font-semibold">{item.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{item.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-16 py-24">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHeading
          eyebrow="How it works"
          title="Three steps from holdings file to review brief."
          body="No setup, no connected accounts. Bring a CSV with one row per holding, or start from a sample portfolio."
        />
        <ol className="mt-14 grid gap-6 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              className="flex flex-col rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
            >
              <span className="font-mono text-sm font-medium text-emerald-700">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-3 text-lg font-semibold">{step.title}</h3>
              <p className="mt-2 flex-1 text-sm leading-relaxed text-slate-600">{step.body}</p>
              <p className="mt-6 border-t border-slate-100 pt-4 font-mono text-xs text-slate-400">
                {step.detail}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function ReviewRules() {
  return (
    <section id="review-rules" className="scroll-mt-16 border-y border-slate-200 bg-slate-50/70 py-24">
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-12 px-6 lg:grid-cols-[0.85fr_1.15fr] lg:gap-16">
        <div>
          <SectionHeading
            eyebrow="Review rules"
            title="Five review rules. Every threshold on the table."
            body="The rules are deliberately simple and fully visible, so an advisor or a compliance reviewer can see exactly why an item appeared and what evidence supports it."
          />
          <div className="mt-8 rounded-xl border border-emerald-200 bg-emerald-50/60 p-5">
            <p className="text-sm font-semibold text-emerald-900">Built-in compliance guardrail</p>
            <p className="mt-1.5 text-sm leading-relaxed text-emerald-900/80">
              Retirement accounts never receive tax-review language. This is enforced inside the
              rule, re-checked by the runtime guard, and covered by tests.
            </p>
          </div>
        </div>
        <ul className="divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          {RULES.map((rule) => (
            <li key={rule.id} className="grid gap-3 p-5 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-6">
              <div>
                <p className="font-medium">{rule.name}</p>
                <p className="mt-0.5 text-sm text-slate-600">{rule.trigger}</p>
                <code className="mt-2 inline-block font-mono text-xs text-slate-400">{rule.id}</code>
              </div>
              <div>
                <SeverityPill severity={rule.severity} />
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function ReviewBrief() {
  return (
    <section id="review-brief" className="scroll-mt-16 py-24">
      <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-14 px-6 lg:grid-cols-2 lg:gap-20">
        <div className="lg:order-2">
          <SectionHeading
            eyebrow="Client Portfolio Review Brief"
            title="A meeting-ready brief, built only from the analysis."
            body="The brief turns review items into talking points, discussion questions, and follow-ups without adding facts that aren't in the data. Every section is generated from the stored analysis record."
          />
          <ul className="mt-8 space-y-3">
            {BRIEF_POINTS.map((point) => (
              <li key={point} className="flex gap-3 text-sm text-slate-700">
                <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <div className="relative isolate lg:order-1">
          <div
            aria-hidden="true"
            className="absolute inset-x-6 -bottom-3 -z-10 h-full rounded-xl border border-slate-200 bg-slate-50"
          />
          <div className="rounded-xl border border-slate-200 bg-white p-7 shadow-lg shadow-slate-900/5">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 pb-5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Prepared for advisor review
                </p>
                <p className="mt-1 text-lg font-semibold">Client Portfolio Review Brief</p>
                <p className="mt-1 font-mono text-xs text-slate-500">growth_concentrated.csv · deterministic-v1</p>
              </div>
              <LogoMark className="h-7 w-7 shrink-0" />
            </div>
            <ol className="mt-4 divide-y divide-slate-100">
              {BRIEF_SECTIONS.map((section, i) => (
                <li key={section} className="flex items-center gap-4 py-2.5 text-sm">
                  <span className="w-5 font-mono text-xs text-slate-400">{i + 1}</span>
                  <span className="text-slate-700">{section}</span>
                </li>
              ))}
            </ol>
            <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-200 pt-5">
              {["Export Markdown", "Export HTML", "Export PDF"].map((label) => (
                <span
                  key={label}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700"
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Compliance() {
  return (
    <section id="compliance" className="scroll-mt-16 bg-slate-900 py-24 text-white">
      <div className="mx-auto max-w-6xl px-6">
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-emerald-400">Compliance</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            Compliance-conscious by design.
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-slate-300">
            AdvisorLens is an advisor-support tool, not a robo-advisor. It organizes what the data
            shows so the advisor can apply their own professional judgment.
          </p>
        </div>
        <div className="mt-14 grid gap-5 sm:grid-cols-2">
          {COMPLIANCE_POINTS.map((point) => (
            <div key={point.title} className="rounded-xl border border-white/10 bg-white/[0.04] p-6">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 text-emerald-300">
                {point.icon}
              </span>
              <h3 className="mt-4 font-semibold">{point.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{point.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="py-24">
      <div className="mx-auto max-w-3xl px-6 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          See it on a sample portfolio.
        </h2>
        <p className="mt-4 text-lg leading-relaxed text-balance text-slate-600">
          Three synthetic portfolios are preloaded, each built to show a different kind of review
          item.
        </p>
        <ul className="mt-6 flex flex-wrap justify-center gap-2">
          {SAMPLES.map((sample) => (
            <li
              key={sample}
              className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm text-slate-600"
            >
              {sample}
            </li>
          ))}
        </ul>
        <div className="mt-10">
          <PrimaryButton href="/workspace">Open the workspace</PrimaryButton>
        </div>
      </div>
    </section>
  );
}

function SiteFooter() {
  return (
    <footer className="border-t border-slate-200 bg-slate-50">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
          <div className="max-w-md">
            <div className="flex items-center gap-2.5">
              <LogoMark className="h-7 w-7" />
              <span className="font-semibold tracking-tight">AdvisorLens</span>
            </div>
            <p className="mt-4 text-sm leading-relaxed text-slate-500">
              An advisor-support tool. AdvisorLens uses synthetic sample data and deterministic
              review rules, and does not provide investment, tax, or legal advice.
            </p>
          </div>
          <nav className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-slate-600">
            <Link href="/workspace" className="hover:text-slate-900">
              Workspace
            </Link>
            {NAV_LINKS.map((link) => (
              <a key={link.href} href={link.href} className="hover:text-slate-900">
                {link.label}
              </a>
            ))}
          </nav>
        </div>
        <p className="mt-10 border-t border-slate-200 pt-6 text-xs text-slate-400">
          © {new Date().getFullYear()} AdvisorLens
        </p>
      </div>
    </footer>
  );
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <div className="max-w-2xl">
      <p className="text-sm font-semibold uppercase tracking-wider text-emerald-700">{eyebrow}</p>
      <h2 className="mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{title}</h2>
      <p className="mt-4 text-lg leading-relaxed text-slate-600">{body}</p>
    </div>
  );
}

function PrimaryButton({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-5 py-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-slate-700"
    >
      {children}
      <ArrowRightIcon />
    </Link>
  );
}

function PreviewStat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 text-base font-semibold sm:text-lg ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

function SeverityPill({ severity }: { severity: Severity }) {
  return (
    <span
      className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[severity]}`}
    >
      {severity}
    </span>
  );
}

function IconBadge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-800 shadow-sm">
      {children}
    </span>
  );
}

function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" className="fill-slate-900" />
      <circle cx="14.5" cy="14.5" r="6.75" fill="none" stroke="white" strokeWidth="2.5" />
      <circle cx="14.5" cy="14.5" r="2.25" className="fill-emerald-400" />
      <path d="M19.6 19.6L24 24" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

function Icon({ children, className = "h-5 w-5" }: { children: ReactNode; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <Icon className={className}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Icon>
  );
}

function ArrowRightIcon() {
  return (
    <Icon className="h-4 w-4">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Icon>
  );
}

function ListCheckIcon() {
  return (
    <Icon>
      <path d="M11 6h9M11 12h9M11 18h9" />
      <path d="M4 6l1.5 1.5L8 5M4 12l1.5 1.5L8 11M4 18l1.5 1.5L8 17" />
    </Icon>
  );
}

function LensIcon() {
  return (
    <Icon>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.4-4.4" />
    </Icon>
  );
}

function ShieldCheckIcon() {
  return (
    <Icon>
      <path d="M12 3l7 3v5c0 4.4-2.9 8.3-7 10-4.1-1.7-7-5.6-7-10V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  );
}

function DocumentIcon() {
  return (
    <Icon>
      <path d="M7 3h7l5 5v13H7z" />
      <path d="M14 3v5h5M10 13h6M10 17h6" />
    </Icon>
  );
}

function HashIcon() {
  return (
    <Icon>
      <path d="M9 4L7 20M17 4l-2 16M4.5 9h16M3.5 15h16" />
    </Icon>
  );
}

function SparkleIcon() {
  return (
    <Icon>
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
      <path d="M19 16v4M17 18h4" />
    </Icon>
  );
}

function DatabaseIcon() {
  return (
    <Icon>
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
      <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
    </Icon>
  );
}
