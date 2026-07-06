"""Client Portfolio Review Brief generation.

Phase 2 ships a deterministic generator: every sentence is templated from
the stored analysis record (summary, flags, evidence, audit metadata) and
nothing else. No findings are invented and no new recommendations are added.

Pluggable design: `GENERATORS` maps a generator name to a callable taking
the stored analysis record and returning the sections dict. A future LLM
generator can be registered here (grounded on the same record and passed
through the same compliance guard) without changing callers. No external
API keys are required in Phase 2.
"""

from datetime import datetime, timezone

from . import ENGINE_VERSION, compliance

DEFAULT_GENERATOR = "deterministic-v1"

BRIEF_DISCLAIMER = (
    "Prepared for advisor review using synthetic data and deterministic rules only. "
    "Every review item in this brief maps to a rule ID and evidence from the uploaded "
    "file. This document is advisor-support material and is not tax, legal, or "
    "investment advice."
)

SECTION_ORDER = [
    "executive_summary",
    "portfolio_snapshot",
    "key_review_items",
    "advisor_talking_points",
    "client_discussion_questions",
    "follow_up_items",
    "evidence_table",
    "data_assumptions",
    "compliance_disclaimer",
]

SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "portfolio_snapshot": "Portfolio Snapshot",
    "key_review_items": "Key Review Items",
    "advisor_talking_points": "Advisor Talking Points",
    "client_discussion_questions": "Client Discussion Questions",
    "follow_up_items": "Follow-Up Items",
    "evidence_table": "Evidence Table",
    "data_assumptions": "Data Assumptions",
    "compliance_disclaimer": "Compliance Disclaimer",
}


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _talking_point(flag: dict) -> str:
    ev = flag["evidence"]
    rule_id = flag["rule_id"]
    if rule_id == "concentration_single_holding":
        return (
            f"Review position sizing for {ev['security_name']} ({ev['ticker']}), which represents "
            f"{ev['weight_pct']}% of portfolio value against the 20% review threshold."
        )
    if rule_id == "concentration_sector":
        return (
            f"Evaluate diversification across sectors: {ev['sector']} represents "
            f"{ev['weight_pct']}% of portfolio value against the 35% review threshold."
        )
    if rule_id == "cash_drag":
        return (
            f"Discuss whether the cash allocation of {ev['weight_pct']}% "
            f"({_money(ev['cash_market_value'])}) aligns with the client's goals and timeline."
        )
    if rule_id == "risk_tolerance_mismatch":
        return (
            f"Review whether the {ev['equity_weight_pct']}% equity allocation remains consistent "
            f"with the client's stated {ev['risk_tolerance']} risk tolerance."
        )
    if rule_id == "tax_review_taxable_loss":
        return (
            f"Consider a tax-related review of {ev['security_name']} ({ev['ticker']}) in the "
            f"{ev['account_type']} account, which shows an unrealized loss of "
            f"{_money(abs(ev['unrealized_gain_loss']))}."
        )
    return f"Review the item flagged by rule {rule_id}."


_DISCUSSION_QUESTIONS = {
    "concentration_single_holding": (
        "How comfortable are you with the portion of the portfolio held in a single position?"
    ),
    "concentration_sector": (
        "How do you feel about the portfolio's current level of exposure to a single sector?"
    ),
    "cash_drag": "Do you have near-term cash needs or planned expenses we should account for?",
    "risk_tolerance_mismatch": (
        "Has anything changed in your circumstances that we should reflect in your risk profile?"
    ),
    "tax_review_taxable_loss": (
        "Would you like to include your tax professional in a review of the taxable account positions?"
    ),
}

_FOLLOW_UPS = {
    "concentration_single_holding": "Schedule a position-sizing review for the concentrated holding(s).",
    "concentration_sector": "Prepare a sector diversification comparison for the next meeting.",
    "cash_drag": "Confirm the client's target cash reserve and timeline.",
    "risk_tolerance_mismatch": "Revisit and re-document the client's risk tolerance questionnaire.",
    "tax_review_taxable_loss": (
        "Coordinate with the client's tax professional before any changes to taxable positions."
    ),
}

_SEVERITY_LABEL = {"high": "high", "medium": "medium", "info": "informational"}


def _deterministic_brief(analysis: dict) -> dict:
    summary = analysis["summary"]
    flags = analysis["flags"]

    by_severity: dict[str, int] = {}
    for flag in flags:
        by_severity[flag["severity"]] = by_severity.get(flag["severity"], 0) + 1
    severity_text = ", ".join(
        f"{count} {_SEVERITY_LABEL[sev]}" for sev, count in sorted(by_severity.items(), key=lambda x: x[0])
    )

    gain = summary["total_unrealized_gain_loss"]
    executive_summary = [
        (
            f"This brief was prepared for advisor review of portfolio file "
            f"'{analysis['source_name']}' (analysis #{analysis['id']}, engine "
            f"v{analysis['engine_version']}). Total portfolio value is "
            f"{_money(summary['total_market_value'])} across {summary['holdings_count']} holdings, "
            f"with an unrealized {'gain' if gain >= 0 else 'loss'} of {_money(abs(gain))}."
        ),
        (
            f"The client's stated risk tolerance is {analysis['risk_tolerance']} and the stated "
            f"goal is {analysis['client_goal']}."
        ),
        (
            f"Deterministic review rules identified {len(flags)} review item(s) ({severity_text}). "
            "Each item maps to a rule ID and evidence in the Evidence Table."
            if flags
            else "No deterministic review thresholds were exceeded for this portfolio."
        ),
    ]

    portfolio_snapshot = {
        "total_market_value": summary["total_market_value"],
        "total_cost_basis": summary["total_cost_basis"],
        "total_unrealized_gain_loss": summary["total_unrealized_gain_loss"],
        "holdings_count": summary["holdings_count"],
        "risk_tolerance": analysis["risk_tolerance"],
        "client_goal": analysis["client_goal"],
        "asset_allocation": summary["asset_allocation"],
        "sector_allocation": summary["sector_allocation"],
        "top_holdings": summary["top_holdings"],
    }

    key_review_items = [
        {
            "rule_id": f["rule_id"],
            "severity": f["severity"],
            "title": f["title"],
            "message": f["message"],
        }
        for f in flags
    ]

    fired_rule_ids = []
    for f in flags:
        if f["rule_id"] not in fired_rule_ids:
            fired_rule_ids.append(f["rule_id"])

    talking_points = [_talking_point(f) for f in flags] or [
        "Review the portfolio snapshot with the client and confirm it still reflects their goals."
    ]

    questions = [_DISCUSSION_QUESTIONS[rid] for rid in fired_rule_ids if rid in _DISCUSSION_QUESTIONS]
    questions.append("Have your goals or time horizon changed since our last review?")

    follow_ups = [_FOLLOW_UPS[rid] for rid in fired_rule_ids if rid in _FOLLOW_UPS]
    follow_ups.append("Document today's discussion and any decisions in the client file.")

    evidence_table = [
        {
            "rule_id": f["rule_id"],
            "severity": f["severity"],
            "threshold": f["threshold"],
            "evidence": f["evidence"],
        }
        for f in flags
    ]

    data_assumptions = [
        "Synthetic sample data only; no real client data, brokerage connections, or market data feeds.",
        f"All figures come solely from the uploaded file (SHA-256 {analysis['file_sha256']}).",
        f"Analysis was computed at {analysis['created_at']} with engine v{analysis['engine_version']}.",
        "Percentages are computed against total portfolio market value as reported in the file.",
        "Review thresholds: single holding > 20%, sector > 35%, cash > 10%, "
        "Conservative profile equity > 60%, unrealized loss in a taxable account.",
        "Tax review considerations are limited to taxable accounts; retirement accounts are "
        "excluded by a compliance guardrail.",
    ]

    return {
        "executive_summary": executive_summary,
        "portfolio_snapshot": portfolio_snapshot,
        "key_review_items": key_review_items,
        "advisor_talking_points": talking_points,
        "client_discussion_questions": questions,
        "follow_up_items": follow_ups,
        "evidence_table": evidence_table,
        "data_assumptions": data_assumptions,
        "compliance_disclaimer": BRIEF_DISCLAIMER,
    }


GENERATORS = {
    "deterministic-v1": _deterministic_brief,
    # A future LLM-backed generator plugs in here, e.g. "llm-v1": _llm_brief.
}


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk_strings(v)


def generate_brief(analysis: dict, generator: str = DEFAULT_GENERATOR) -> dict:
    """Build a brief from a stored analysis record and compliance-check every string."""
    sections = GENERATORS[generator](analysis)
    for text in _walk_strings(sections):
        compliance.assert_compliant_text(text, context="brief")
    return {
        "analysis_id": analysis["id"],
        "source_name": analysis["source_name"],
        "generator": generator,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }


# --- Rendering -------------------------------------------------------------


def _flatten_evidence(evidence: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in evidence.items())


def brief_to_markdown(brief: dict) -> str:
    s = brief["sections"]
    snap = s["portfolio_snapshot"]
    lines: list[str] = [
        "# Client Portfolio Review Brief",
        "",
        f"*Source file: {brief['source_name']} · analysis #{brief['analysis_id']} · "
        f"generated {brief['generated_at']} · generator {brief['generator']} · "
        f"engine v{brief['engine_version']}*",
        "",
        f"## {SECTION_TITLES['executive_summary']}",
        "",
        *s["executive_summary"],
        "",
        f"## {SECTION_TITLES['portfolio_snapshot']}",
        "",
        f"- Total market value: {_money(snap['total_market_value'])}",
        f"- Total cost basis: {_money(snap['total_cost_basis'])}",
        f"- Unrealized gain/loss: {_money(snap['total_unrealized_gain_loss'])}",
        f"- Holdings: {snap['holdings_count']}",
        f"- Risk tolerance: {snap['risk_tolerance']} · Goal: {snap['client_goal']}",
        "",
        "### Asset allocation",
        "",
        "| Asset class | Value | Weight |",
        "|---|---:|---:|",
        *[
            f"| {a['name']} | {_money(a['market_value'])} | {a['weight_pct']}% |"
            for a in snap["asset_allocation"]
        ],
        "",
        "### Sector allocation",
        "",
        "| Sector | Value | Weight |",
        "|---|---:|---:|",
        *[
            f"| {a['name']} | {_money(a['market_value'])} | {a['weight_pct']}% |"
            for a in snap["sector_allocation"]
        ],
        "",
        "### Top holdings",
        "",
        "| Ticker | Name | Value | Weight | Unrealized G/L |",
        "|---|---|---:|---:|---:|",
        *[
            f"| {h['ticker']} | {h['security_name']} | {_money(h['market_value'])} | "
            f"{h['weight_pct']}% | {_money(h['unrealized_gain_loss'])} |"
            for h in snap["top_holdings"]
        ],
        "",
        f"## {SECTION_TITLES['key_review_items']}",
        "",
    ]
    if s["key_review_items"]:
        for item in s["key_review_items"]:
            lines += [
                f"### [{item['severity'].upper()}] {item['title']} (`{item['rule_id']}`)",
                "",
                item["message"],
                "",
            ]
    else:
        lines += ["No review thresholds were exceeded for this portfolio.", ""]

    for key in ("advisor_talking_points", "client_discussion_questions", "follow_up_items"):
        lines += [f"## {SECTION_TITLES[key]}", ""]
        lines += [f"- {entry}" for entry in s[key]]
        lines += [""]

    lines += [f"## {SECTION_TITLES['evidence_table']}", ""]
    if s["evidence_table"]:
        lines += [
            "| Rule ID | Severity | Threshold | Evidence |",
            "|---|---|---|---|",
            *[
                f"| `{row['rule_id']}` | {row['severity']} | {row['threshold']} | "
                f"{_flatten_evidence(row['evidence'])} |"
                for row in s["evidence_table"]
            ],
            "",
        ]
    else:
        lines += ["No rules fired; there is no evidence to report.", ""]

    lines += [f"## {SECTION_TITLES['data_assumptions']}", ""]
    lines += [f"- {entry}" for entry in s["data_assumptions"]]
    lines += [
        "",
        f"## {SECTION_TITLES['compliance_disclaimer']}",
        "",
        s["compliance_disclaimer"],
        "",
    ]
    return "\n".join(lines)


_HTML_STYLE = """
  body { font-family: Georgia, 'Times New Roman', serif; color: #1a202c;
         max-width: 800px; margin: 2rem auto; padding: 0 1.5rem; line-height: 1.55; }
  h1 { font-size: 1.6rem; border-bottom: 2px solid #1a202c; padding-bottom: .4rem; }
  h2 { font-size: 1.15rem; margin-top: 1.8rem; border-bottom: 1px solid #cbd5e0;
       padding-bottom: .2rem; }
  h3 { font-size: 1rem; margin-top: 1.1rem; }
  table { border-collapse: collapse; width: 100%; margin: .6rem 0; font-size: .85rem; }
  th, td { border: 1px solid #cbd5e0; padding: .35rem .5rem; text-align: left; }
  th { background: #f7fafc; }
  .meta { color: #718096; font-size: .8rem; }
  .severity-high { color: #9b2c2c; font-weight: bold; }
  .severity-medium { color: #975a16; font-weight: bold; }
  .severity-info { color: #2b6cb0; font-weight: bold; }
  .disclaimer { border: 1px solid #cbd5e0; background: #f7fafc; padding: .8rem;
                font-size: .85rem; margin-top: 1rem; }
  code { background: #edf2f7; padding: 0 .25rem; font-size: .85em; }
  @media print { body { margin: 0; max-width: none; } h2 { page-break-after: avoid; } }
"""


def _esc(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _html_alloc_table(rows: list[dict], label: str) -> str:
    body = "".join(
        f"<tr><td>{_esc(r['name'])}</td><td>{_money(r['market_value'])}</td>"
        f"<td>{r['weight_pct']}%</td></tr>"
        for r in rows
    )
    return (
        f"<h3>{_esc(label)}</h3><table><tr><th>Name</th><th>Value</th><th>Weight</th></tr>"
        f"{body}</table>"
    )


def brief_to_html(brief: dict) -> str:
    s = brief["sections"]
    snap = s["portfolio_snapshot"]

    parts: list[str] = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>Client Portfolio Review Brief — {_esc(brief['source_name'])}</title>",
        f"<style>{_HTML_STYLE}</style></head><body>",
        "<h1>Client Portfolio Review Brief</h1>",
        f"<p class='meta'>Source file: {_esc(brief['source_name'])} · analysis "
        f"#{brief['analysis_id']} · generated {_esc(brief['generated_at'])} · generator "
        f"{_esc(brief['generator'])} · engine v{_esc(brief['engine_version'])}</p>",
        f"<h2>{SECTION_TITLES['executive_summary']}</h2>",
        *[f"<p>{_esc(p)}</p>" for p in s["executive_summary"]],
        f"<h2>{SECTION_TITLES['portfolio_snapshot']}</h2>",
        "<ul>",
        f"<li>Total market value: {_money(snap['total_market_value'])}</li>",
        f"<li>Total cost basis: {_money(snap['total_cost_basis'])}</li>",
        f"<li>Unrealized gain/loss: {_money(snap['total_unrealized_gain_loss'])}</li>",
        f"<li>Holdings: {snap['holdings_count']}</li>",
        f"<li>Risk tolerance: {_esc(snap['risk_tolerance'])} · Goal: {_esc(snap['client_goal'])}</li>",
        "</ul>",
        _html_alloc_table(snap["asset_allocation"], "Asset allocation"),
        _html_alloc_table(snap["sector_allocation"], "Sector allocation"),
        "<h3>Top holdings</h3><table><tr><th>Ticker</th><th>Name</th><th>Value</th>"
        "<th>Weight</th><th>Unrealized G/L</th></tr>",
        *[
            f"<tr><td>{_esc(h['ticker'])}</td><td>{_esc(h['security_name'])}</td>"
            f"<td>{_money(h['market_value'])}</td><td>{h['weight_pct']}%</td>"
            f"<td>{_money(h['unrealized_gain_loss'])}</td></tr>"
            for h in snap["top_holdings"]
        ],
        "</table>",
        f"<h2>{SECTION_TITLES['key_review_items']}</h2>",
    ]
    if s["key_review_items"]:
        for item in s["key_review_items"]:
            parts += [
                f"<h3><span class='severity-{_esc(item['severity'])}'>"
                f"[{_esc(item['severity'].upper())}]</span> {_esc(item['title'])} "
                f"<code>{_esc(item['rule_id'])}</code></h3>",
                f"<p>{_esc(item['message'])}</p>",
            ]
    else:
        parts.append("<p>No review thresholds were exceeded for this portfolio.</p>")

    for key in ("advisor_talking_points", "client_discussion_questions", "follow_up_items"):
        parts.append(f"<h2>{SECTION_TITLES[key]}</h2><ul>")
        parts += [f"<li>{_esc(entry)}</li>" for entry in s[key]]
        parts.append("</ul>")

    parts.append(f"<h2>{SECTION_TITLES['evidence_table']}</h2>")
    if s["evidence_table"]:
        parts.append(
            "<table><tr><th>Rule ID</th><th>Severity</th><th>Threshold</th><th>Evidence</th></tr>"
        )
        parts += [
            f"<tr><td><code>{_esc(row['rule_id'])}</code></td><td>{_esc(row['severity'])}</td>"
            f"<td>{_esc(row['threshold'])}</td><td>{_esc(_flatten_evidence(row['evidence']))}</td></tr>"
            for row in s["evidence_table"]
        ]
        parts.append("</table>")
    else:
        parts.append("<p>No rules fired; there is no evidence to report.</p>")

    parts.append(f"<h2>{SECTION_TITLES['data_assumptions']}</h2><ul>")
    parts += [f"<li>{_esc(entry)}</li>" for entry in s["data_assumptions"]]
    parts += [
        "</ul>",
        f"<h2>{SECTION_TITLES['compliance_disclaimer']}</h2>",
        f"<p class='disclaimer'>{_esc(s['compliance_disclaimer'])}</p>",
        "</body></html>",
    ]
    return "".join(parts)
