"""Advisor-approved client reports built from explicit selections.

Internal review notes and household details are never copied in automatically:
the advisor writes client-facing text and chooses which follow-ups and household
sections appear. Approval re-derives the report from current sources and only
saves it when it matches the previewed digest; the saved content and rendered
Markdown/HTML/PDF bytes cannot be updated or deleted afterwards (database
triggers). This is a synthetic-data demo, not an authentication layer.
"""
import hashlib
import json
from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import compliance, db, reviews
from .brief import _HTML_STYLE, _esc, _money
from .pdf_export import PdfRenderError, html_to_pdf_bytes

Format = Literal["markdown", "html", "pdf"]

STATUS_LABELS = {
    "open": "Open", "discussed": "Discussed", "follow_up": "Follow-up", "resolved": "Resolved",
}

REPORT_DISCLAIMER = (
    "Prepared for discussion with your advisor using synthetic demonstration data. Review "
    "items come from deterministic rules applied to the analyzed portfolio file; the summary, "
    "follow-ups and household details were written or selected and approved by the advisor. "
    "This report is not tax, legal, or investment advice."
)

_MEDIA = {
    "markdown": ("text/markdown; charset=utf-8", "md"),
    "html": ("text/html; charset=utf-8", "html"),
    "pdf": ("application/pdf", "pdf"),
}

_REPORT_STYLE = """
  .stamp { border: 1px solid #94a3b8; border-radius: 6px; padding: 8px 12px; font-size: 12px; color: #334155; }
  .stamp.draft { border-color: #b45309; color: #92400e; background: #fffbeb; }
  .scope { background: #f1f5f9; border-left: 4px solid #475569; padding: 10px 14px; }
"""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FollowUp(_Model):
    finding_id: str = Field(min_length=1, max_length=64)
    review_version: int = Field(ge=0, strict=True)
    client_text: str = Field(min_length=1, max_length=1000)


class HouseholdSelection(_Model):
    household_id: int = Field(ge=1, strict=True)
    version: int = Field(ge=1, strict=True)
    priorities: bool = Field(default=False, strict=True)
    goals: bool = Field(default=False, strict=True)
    accounts: bool = Field(default=False, strict=True)


class Draft(_Model):
    brief_id: int = Field(ge=1, strict=True)
    client_summary: str = Field(min_length=1, max_length=4000)
    follow_ups: list[FollowUp] = Field(default_factory=list, max_length=50)
    household: HouseholdSelection | None = None

    @model_validator(mode="after")
    def unique_follow_ups(self):
        ids = [f.finding_id for f in self.follow_ups]
        if len(ids) != len(set(ids)):
            raise ValueError("Each finding can be selected once.")
        return self


class Approval(_Model):
    draft: Draft
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportNotFound(Exception):
    pass


class ReportConflict(Exception):
    pass


class ReportInvalid(Exception):
    pass


def _attached_household(db_path, analysis_id: int) -> dict | None:
    with closing(db._connect(db_path)) as conn:
        row = conn.execute(
            """SELECT h.household_id, h.version, v.profile_json FROM analysis_households h
               JOIN household_versions v ON h.household_id = v.household_id AND h.version = v.version
               WHERE h.analysis_id = ?""",
            (analysis_id,),
        ).fetchone()
    if row is None:
        return None
    return {"household_id": row["household_id"], "version": row["version"],
            "profile": json.loads(row["profile_json"])}


def _default_summary(analysis: dict) -> str:
    summary = analysis["summary"]
    count = len(analysis["flags"])
    items = f"{count} item{'s' if count != 1 else ''} worth discussing" if count else "no items above the review thresholds"
    return (
        f"We reviewed the {summary['holdings_count']} holdings in the portfolio file "
        f"{analysis['source_name']}, with a total value of {_money(summary['total_market_value'])}. "
        f"The review identified {items}. The follow-ups below are the next steps we agreed on."
    )


def draft_defaults(db_path, analysis_id: int) -> dict:
    """Everything the advisor needs to start a draft. Internal notes are returned for the
    advisor's own screen only; nothing here enters a report unless explicitly selected."""
    analysis = db.get_analysis(db_path, analysis_id)
    if analysis is None:
        raise ReportNotFound("Analysis not found.")
    latest = db.get_latest_brief_record(db_path, analysis_id)
    household = _attached_household(db_path, analysis_id)
    return {
        "analysis_id": analysis_id,
        "brief_id": latest[0] if latest else None,
        "client_summary": _default_summary(analysis),
        "reviews": [
            {"finding_id": item["finding_id"], "title": item["flag"]["title"],
             "severity": item["flag"]["severity"], "status": item["status"],
             "version": item["version"], "internal_note": item["note"]}
            for item in reviews.get_reviews(db_path, analysis_id)["items"]
        ],
        "household": None if household is None else {
            "household_id": household["household_id"], "version": household["version"],
            "name": household["profile"]["name"], "as_of": household["profile"]["as_of"],
            "has_priorities": bool(household["profile"].get("priorities")),
            "goal_count": len(household["profile"].get("goals", [])),
            "account_count": len(household["profile"].get("accounts", [])),
        },
    }


def _check_language(text: str, label: str) -> None:
    violations = compliance.find_violations(text)
    if violations:
        raise ReportInvalid(
            f"{label} contains direct-advice wording ({', '.join(sorted(set(violations)))}). "
            "Rephrase it as a consideration for discussion."
        )


def _household_block(household: dict, selection: HouseholdSelection) -> dict:
    profile = household["profile"]
    names = {m["id"]: m["name"] for m in profile.get("members", [])}
    block = {
        "name": profile["name"], "as_of": profile["as_of"], "version": household["version"],
        "priorities": profile.get("priorities") or None if selection.priorities else None,
        "goals": None, "accounts": None,
    }
    if selection.goals:
        block["goals"] = [
            {"name": g["name"], "priority": g["priority"], "target_date": g.get("target_date"),
             "amount": g.get("amount")}
            for g in profile.get("goals", [])
        ]
    if selection.accounts:
        block["accounts"] = [
            {"name": a["name"], "account_type": a["account_type"],
             "owners": [names.get(o, o) for o in a["owner_ids"]],
             "balance": a.get("balance"), "as_of": a.get("as_of"), "evidence": a["evidence"]}
            for a in profile.get("accounts", [])
        ]
    return block


def build(db_path, analysis_id: int, draft: Draft) -> tuple[dict, dict]:
    """Derive report content and its source references from current records.

    Raises ReportConflict whenever a cited source (brief, review revision, household
    snapshot) is no longer the one the advisor saw, so nothing is silently substituted.
    """
    analysis = db.get_analysis(db_path, analysis_id)
    if analysis is None:
        raise ReportNotFound("Analysis not found.")
    latest = db.get_latest_brief_record(db_path, analysis_id)
    if latest is None:
        raise ReportConflict("Generate the review brief before preparing a client report.")
    brief_id, brief = latest
    if draft.brief_id != brief_id:
        raise ReportConflict("A newer review brief was generated for this analysis. Reload and preview the report again.")

    _check_language(draft.client_summary, "The client summary")
    current = {item["finding_id"]: item for item in reviews.get_reviews(db_path, analysis_id)["items"]}
    follow_ups, review_refs = [], []
    for selected in draft.follow_ups:
        item = current.get(selected.finding_id)
        if item is None:
            raise ReportNotFound("A selected finding does not belong to this analysis.")
        if item["version"] != selected.review_version:
            raise ReportConflict(
                f"The review for “{item['flag']['title']}” changed (now revision {item['version']}). "
                "Reload and preview the report again."
            )
        _check_language(selected.client_text, f"The follow-up for “{item['flag']['title']}”")
        follow_ups.append({
            "title": item["flag"]["title"], "severity": item["flag"]["severity"],
            "status": STATUS_LABELS[item["status"]], "client_text": selected.client_text,
        })
        review_refs.append({"finding_id": selected.finding_id, "version": item["version"],
                            "status": item["status"]})

    attached = _attached_household(db_path, analysis_id)
    household = None
    if draft.household is not None:
        if attached is None or (attached["household_id"], attached["version"]) != (
            draft.household.household_id, draft.household.version
        ):
            raise ReportConflict("The household snapshot attached to this analysis does not match your selection. Reload and preview again.")
        household = _household_block(attached, draft.household)

    sections = brief["sections"]
    snap = sections["portfolio_snapshot"]
    content = {
        "title": "Client Portfolio Review",
        "prepared_for": household["name"] if household else None,
        "client_summary": draft.client_summary,
        "portfolio": {
            "source_name": analysis["source_name"], "file_sha256": analysis["file_sha256"],
            "analysis_id": analysis_id, "engine_version": analysis["engine_version"],
            "analyzed_at": analysis["created_at"],
            "total_market_value": snap["total_market_value"],
            "total_unrealized_gain_loss": snap["total_unrealized_gain_loss"],
            "holdings_count": snap["holdings_count"], "risk_tolerance": snap["risk_tolerance"],
            "client_goal": snap["client_goal"], "asset_allocation": snap["asset_allocation"],
        },
        "review_items": [{k: i[k] for k in ("severity", "title", "message")} for i in sections["key_review_items"]],
        "follow_ups": follow_ups,
        "household": household,
        "scope_statement": (
            f"This report analyzes only the holdings in the portfolio file {analysis['source_name']} "
            f"(SHA-256 {analysis['file_sha256'][:12]}…). It does not establish that this file includes "
            "every account the household holds."
        ),
        "data_notes": sections["data_assumptions"],
        "disclaimer": REPORT_DISCLAIMER,
    }
    sources = {
        "analysis_id": analysis_id, "file_sha256": analysis["file_sha256"],
        "engine_version": analysis["engine_version"], "brief_id": brief_id,
        "brief_generator": brief["generator"],
        "household": None if household is None else {
            "household_id": draft.household.household_id, "version": draft.household.version},
        "reviews": review_refs,
    }
    return content, sources


def digest(content: dict, sources: dict) -> str:
    canonical = json.dumps({"content": content, "sources": sources}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


# --- Rendering ---------------------------------------------------------------

def _amount(value) -> str:
    return "Not established" if value is None else _money(float(value))


def _stamp_text(stamp: dict) -> str:
    if stamp["kind"] == "draft":
        return "DRAFT PREVIEW — not approved. Approval saves exactly this content."
    return (f"Approved client report #{stamp['report_id']} · approved {stamp['approved_at']} · "
            f"content SHA-256 {stamp['content_sha256'][:16]}…")


def render_markdown(content: dict, stamp: dict) -> str:
    p = content["portfolio"]
    lines = [f"# {content['title']}", ""]
    if content["prepared_for"]:
        lines += [f"Prepared for: {content['prepared_for']}", ""]
    lines += [f"> {_stamp_text(stamp)}", "", "## Summary", "", content["client_summary"], "",
              f"## Analyzed portfolio — {p['source_name']}", "",
              f"> {content['scope_statement']}", "",
              f"- Total value: {_money(p['total_market_value'])}",
              f"- Unrealized gain/loss: {_money(p['total_unrealized_gain_loss'])}",
              f"- Holdings: {p['holdings_count']}",
              f"- Stated risk tolerance: {p['risk_tolerance']} · Goal: {p['client_goal']}",
              f"- Analysis #{p['analysis_id']}, engine v{p['engine_version']}, analyzed {p['analyzed_at']}",
              "", "| Asset class | Value | Weight |", "|---|---|---|"]
    lines += [f"| {a['name']} | {_money(a['market_value'])} | {a['weight_pct']}% |" for a in p["asset_allocation"]]
    lines += ["", "## Review items", ""]
    lines += [f"- **[{i['severity'].upper()}] {i['title']}** — {i['message']}" for i in content["review_items"]] or [
        "- No review thresholds were exceeded for this portfolio."]
    lines += ["", "## Agreed follow-ups", ""]
    lines += [f"- **{f['title']}** ({f['status']}): {f['client_text']}" for f in content["follow_ups"]] or [
        "- No follow-ups were selected for this report."]
    h = content["household"]
    if h:
        lines += ["", f"## Household context — {h['name']}", "",
                  f"Household profile version {h['version']}, as of {h['as_of']}."]
        if h["priorities"]:
            lines += ["", "### Priorities", "", h["priorities"]]
        if h["goals"] is not None:
            lines += ["", "### Goals", ""]
            lines += [f"- {g['name']} · {g['priority']} · target {g['target_date'] or 'date not established'} · "
                      f"{_amount(g['amount'])}" for g in h["goals"]] or ["- No goals recorded."]
        if h["accounts"] is not None:
            lines += ["", "### Household account inventory (advisor-entered, not reconciled)", "",
                      "These balances were entered manually and are listed separately from the analyzed "
                      "portfolio. They have not been reconciled with it and may overlap with or differ from "
                      "it. Do not add them to the portfolio totals above.", "",
                      "| Account | Type | Owners | Balance | Valued | Basis |", "|---|---|---|---|---|---|"]
            lines += [f"| {a['name']} | {a['account_type']} | {', '.join(a['owners'])} | {_amount(a['balance'])} | "
                      f"{a['as_of'] or '—'} | {a['evidence']} |" for a in h["accounts"]]
    lines += ["", "## Data notes", ""] + [f"- {n}" for n in content["data_notes"]]
    lines += ["", "## Disclaimer", "", content["disclaimer"], ""]
    return "\n".join(lines)


def render_html(content: dict, stamp: dict) -> str:
    p = content["portfolio"]
    out = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
           f"<title>{_esc(content['title'])} — {_esc(p['source_name'])}</title>",
           f"<style>{_HTML_STYLE}{_REPORT_STYLE}</style></head><body>",
           f"<h1>{_esc(content['title'])}</h1>"]
    if content["prepared_for"]:
        out.append(f"<p><strong>Prepared for:</strong> {_esc(content['prepared_for'])}</p>")
    out += [f"<p class='stamp {'draft' if stamp['kind'] == 'draft' else 'approved'}'>{_esc(_stamp_text(stamp))}</p>",
            "<h2>Summary</h2>",
            *[f"<p>{_esc(par)}</p>" for par in content["client_summary"].split("\n") if par.strip()],
            f"<h2>Analyzed portfolio — {_esc(p['source_name'])}</h2>",
            f"<p class='scope'>{_esc(content['scope_statement'])}</p><ul>",
            f"<li>Total value: {_money(p['total_market_value'])}</li>",
            f"<li>Unrealized gain/loss: {_money(p['total_unrealized_gain_loss'])}</li>",
            f"<li>Holdings: {p['holdings_count']}</li>",
            f"<li>Stated risk tolerance: {_esc(p['risk_tolerance'])} · Goal: {_esc(p['client_goal'])}</li>",
            f"<li>Analysis #{p['analysis_id']}, engine v{_esc(p['engine_version'])}, analyzed {_esc(p['analyzed_at'])}</li></ul>",
            "<table><thead><tr><th>Asset class</th><th>Value</th><th>Weight</th></tr></thead><tbody>",
            *[f"<tr><td>{_esc(a['name'])}</td><td>{_money(a['market_value'])}</td><td>{a['weight_pct']}%</td></tr>"
              for a in p["asset_allocation"]],
            "</tbody></table><h2>Review items</h2>"]
    if content["review_items"]:
        out += [f"<div class='review-item sev-{_esc(i['severity'])}'><h3>[{_esc(i['severity'].upper())}] "
                f"{_esc(i['title'])}</h3><p>{_esc(i['message'])}</p></div>" for i in content["review_items"]]
    else:
        out.append("<p>No review thresholds were exceeded for this portfolio.</p>")
    out.append("<h2>Agreed follow-ups</h2>")
    if content["follow_ups"]:
        out += ["<ul>", *[f"<li><strong>{_esc(f['title'])}</strong> ({_esc(f['status'])}): {_esc(f['client_text'])}</li>"
                          for f in content["follow_ups"]], "</ul>"]
    else:
        out.append("<p>No follow-ups were selected for this report.</p>")
    h = content["household"]
    if h:
        out += [f"<h2>Household context — {_esc(h['name'])}</h2>",
                f"<p>Household profile version {h['version']}, as of {_esc(h['as_of'])}.</p>"]
        if h["priorities"]:
            out += ["<h3>Priorities</h3>", f"<p>{_esc(h['priorities'])}</p>"]
        if h["goals"] is not None:
            out.append("<h3>Goals</h3>")
            out += ["<ul>", *[f"<li>{_esc(g['name'])} · {_esc(g['priority'])} · target "
                              f"{_esc(g['target_date'] or 'date not established')} · {_amount(g['amount'])}</li>"
                              for g in h["goals"]], "</ul>"] if h["goals"] else ["<p>No goals recorded.</p>"]
        if h["accounts"] is not None:
            out += ["<h3>Household account inventory (advisor-entered, not reconciled)</h3>",
                    "<p class='scope'>These balances were entered manually and are listed separately from the "
                    "analyzed portfolio. They have not been reconciled with it and may overlap with or differ "
                    "from it. Do not add them to the portfolio totals above.</p>",
                    "<table><thead><tr><th>Account</th><th>Type</th><th>Owners</th><th>Balance</th>"
                    "<th>Valued</th><th>Basis</th></tr></thead><tbody>",
                    *[f"<tr><td>{_esc(a['name'])}</td><td>{_esc(a['account_type'])}</td><td>{_esc(', '.join(a['owners']))}</td>"
                      f"<td>{_amount(a['balance'])}</td><td>{_esc(a['as_of'] or '—')}</td><td>{_esc(a['evidence'])}</td></tr>"
                      for a in h["accounts"]], "</tbody></table>"]
    out += ["<h2>Data notes</h2><ul>", *[f"<li>{_esc(n)}</li>" for n in content["data_notes"]], "</ul>",
            "<h2>Disclaimer</h2>", f"<p class='disclaimer'>{_esc(content['disclaimer'])}</p>", "</body></html>"]
    return "".join(out)


# --- Workflow ----------------------------------------------------------------

def preview(db_path, analysis_id: int, draft: Draft) -> dict:
    content, sources = build(db_path, analysis_id, draft)
    return {"preview_sha256": digest(content, sources), "content": content, "sources": sources,
            "html": render_html(content, {"kind": "draft"})}


def _record(conn, row) -> dict:
    files = {f["format"]: f["sha256"] for f in conn.execute(
        "SELECT format, sha256 FROM approved_report_files WHERE report_id = ?", (row["id"],))}
    return {"id": row["id"], "analysis_id": row["analysis_id"], "approved_at": row["approved_at"],
            "content_sha256": row["content_sha256"], "content": json.loads(row["content_json"]),
            "sources": json.loads(row["sources_json"]), "files": files}


def approve(db_path, analysis_id: int, approval: Approval) -> dict:
    content, sources = build(db_path, analysis_id, approval.draft)
    content_sha = digest(content, sources)
    if content_sha != approval.preview_sha256:
        raise ReportConflict("The report changed since your preview. Review the updated preview before approving.")
    approved_at = db._now()
    with closing(db._connect(db_path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        # Render inside the write lock so the report ID in the stamp is the one stored.
        report_id = (conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM approved_reports").fetchone()[0])
        # Sources are re-derived under the lock: a change after the first check still blocks.
        if digest(*build(db_path, analysis_id, approval.draft)) != content_sha:
            raise ReportConflict("The report sources changed during approval. Review the updated preview.")
        stamp = {"kind": "approved", "report_id": report_id, "approved_at": approved_at, "content_sha256": content_sha}
        html = render_html(content, stamp)
        try:
            files = {"markdown": render_markdown(content, stamp).encode(), "html": html.encode(),
                     "pdf": html_to_pdf_bytes(html)}
        except PdfRenderError as exc:
            raise ReportInvalid("The PDF could not be rendered, so nothing was approved. Try again.") from exc
        conn.execute(
            """INSERT INTO approved_reports (id, analysis_id, brief_id, household_id, household_version,
               content_json, sources_json, content_sha256, approved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_id, analysis_id, sources["brief_id"],
             sources["household"]["household_id"] if sources["household"] else None,
             sources["household"]["version"] if sources["household"] else None,
             json.dumps(content), json.dumps(sources), content_sha, approved_at))
        for fmt, body in files.items():
            conn.execute("INSERT INTO approved_report_files (report_id, format, body, sha256) VALUES (?, ?, ?, ?)",
                         (report_id, fmt, body, hashlib.sha256(body).hexdigest()))
        conn.execute("INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)",
                     (analysis_id, "client_report_approved",
                      json.dumps({"report_id": report_id, "content_sha256": content_sha, "sources": sources}), approved_at))
        row = conn.execute("SELECT * FROM approved_reports WHERE id = ?", (report_id,)).fetchone()
        return _record(conn, row)


def get_report(db_path, report_id: int) -> dict:
    with closing(db._connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM approved_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise ReportNotFound("Approved report not found.")
        return _record(conn, row)


def list_reports(db_path, analysis_id: int) -> list[dict]:
    if db.get_analysis(db_path, analysis_id) is None:
        raise ReportNotFound("Analysis not found.")
    with closing(db._connect(db_path)) as conn:
        rows = conn.execute("SELECT * FROM approved_reports WHERE analysis_id = ? ORDER BY id DESC",
                            (analysis_id,)).fetchall()
        return [_record(conn, row) for row in rows]


def get_file(db_path, report_id: int, fmt: str) -> bytes:
    with closing(db._connect(db_path)) as conn:
        row = conn.execute("SELECT body FROM approved_report_files WHERE report_id = ? AND format = ?",
                           (report_id, fmt)).fetchone()
    if row is None:
        raise ReportNotFound("Approved report file not found.")
    return bytes(row["body"])


def router(db_path_provider) -> APIRouter:
    api = APIRouter()

    def guard(action):
        try:
            return action()
        except ReportNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except reviews.ReviewNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except ReportConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ReportInvalid as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/analyses/{analysis_id}/reports/draft")
    def defaults(analysis_id: int):
        return guard(lambda: draft_defaults(db_path_provider(), analysis_id))

    @api.post("/analyses/{analysis_id}/reports/preview")
    def preview_report(analysis_id: int, draft: Draft):
        return guard(lambda: preview(db_path_provider(), analysis_id, draft))

    @api.post("/analyses/{analysis_id}/reports", status_code=201)
    def approve_report(analysis_id: int, approval: Approval):
        return guard(lambda: approve(db_path_provider(), analysis_id, approval))

    @api.get("/analyses/{analysis_id}/reports")
    def analysis_reports(analysis_id: int):
        return guard(lambda: {"reports": list_reports(db_path_provider(), analysis_id)})

    @api.get("/reports/{report_id}")
    def read_report(report_id: int):
        return guard(lambda: get_report(db_path_provider(), report_id))

    @api.get("/reports/{report_id}/{fmt}")
    def download(report_id: int, fmt: Format):
        body = guard(lambda: get_file(db_path_provider(), report_id, fmt))
        media, ext = _MEDIA[fmt]
        return Response(body, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="client-report-{report_id}.{ext}"',
            "X-Content-SHA256": hashlib.sha256(body).hexdigest(),
        })

    return api
