#!/usr/bin/env python3
"""Live verification of the llm-v1 brief generator against a configured provider.

Runs one real (or mock) LLM-backed brief generation on synthetic sample data
and checks every compliance guarantee end to end:

  - generator is llm-v1 (a fallback counts as verification failure)
  - model/provider metadata is present
  - review items map exactly to the deterministic rule IDs
  - the evidence table is byte-identical to the deterministic generator's
  - the compliance disclaimer is present
  - no banned phrases anywhere (base list) or in narrative (extended list)
  - Markdown, HTML, and PDF exports render, and PDF text extraction still
    contains the rule IDs and the disclaimer

CI-safe: with no provider configured it prints how to run and exits 0
(use --strict to exit 1 instead). Never prints or stores the API key.

Usage:
  export ADVISORLENS_LLM_PROVIDER=openai-compatible
  export ADVISORLENS_LLM_MODEL=<model>
  export ADVISORLENS_LLM_API_KEY=<key>
  export ADVISORLENS_LLM_BASE_URL=<https://.../v1>   # optional
  .venv/bin/python scripts/verify_llm_live.py

Keyless demo of the same pipeline:
  ADVISORLENS_LLM_PROVIDER=mock .venv/bin/python scripts/verify_llm_live.py
"""

import argparse
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import compliance, db  # noqa: E402
from app.brief import (  # noqa: E402
    _deterministic_brief,
    _walk_strings,
    brief_to_html,
    brief_to_markdown,
    generate_brief,
)
from app.llm import LLMConfig  # noqa: E402
from app.service import analyze_csv  # noqa: E402

SAMPLES_DIR = BACKEND_DIR.parent / "data" / "samples"
DISCLAIMER_FRAGMENT = "not tax, legal, or investment advice"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", default="conservative_mismatch.csv",
                        help="synthetic sample CSV to analyze (default: %(default)s)")
    parser.add_argument("--skip-pdf", action="store_true",
                        help="skip the PDF render/extraction check (faster)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 (instead of 0) when no provider is configured")
    args = parser.parse_args()

    config = LLMConfig.from_env()
    if not config.is_configured:
        print("SKIPPED: no LLM provider is configured.")
        print("Set ADVISORLENS_LLM_PROVIDER / _MODEL / _API_KEY (see --help), or use")
        print("ADVISORLENS_LLM_PROVIDER=mock for a keyless demo of this pipeline.")
        return 1 if args.strict else 0

    print(f"Provider: {config.provider} | model: {config.model} | base_url: {config.base_url}")
    print(f"Sample: {args.sample}")

    sample_path = SAMPLES_DIR / args.sample
    if not sample_path.is_file():
        print(f"FAIL: sample '{args.sample}' not found in {SAMPLES_DIR}")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "verify.db"
        result = analyze_csv(sample_path.read_bytes(), source_name=args.sample, db_path=db_path)
        analysis = db.get_analysis(db_path, result["analysis_id"])

        brief = generate_brief(analysis, generator="llm-v1")

    metadata = brief["generator_metadata"]
    sections = brief["sections"]
    checks: list[tuple[str, bool, str]] = []

    ok = brief["generator"] == "llm-v1"
    detail = "" if ok else f"got '{brief['generator']}', reason: {metadata.get('fallback_reason')}"
    checks.append(("generator is llm-v1", ok, detail))

    checks.append(("model metadata present", bool(metadata.get("model")),
                   f"model={metadata.get('model')}, prompt={metadata.get('prompt_version')}"))

    expected_rule_ids = [f["rule_id"] for f in analysis["flags"]]
    got_rule_ids = [i["rule_id"] for i in sections["key_review_items"]]
    checks.append(("rule IDs preserved", got_rule_ids == expected_rule_ids,
                   f"expected {expected_rule_ids}, got {got_rule_ids}"))

    deterministic = _deterministic_brief(analysis)
    checks.append(("evidence table unchanged",
                   sections["evidence_table"] == deterministic["evidence_table"], ""))

    checks.append(("disclaimer present",
                   DISCLAIMER_FRAGMENT in sections["compliance_disclaimer"], ""))

    banned = []
    for text in _walk_strings(sections):
        banned += compliance.find_violations(text)
    narrative = [
        *sections["executive_summary"],
        *(i["message"] for i in sections["key_review_items"]),
        *sections["advisor_talking_points"],
        *sections["client_discussion_questions"],
        *sections["follow_up_items"],
    ]
    for text in narrative:
        banned += compliance.find_llm_violations(text)
    checks.append(("no banned phrases", not banned, f"found {banned}" if banned else ""))

    markdown = brief_to_markdown(brief)
    checks.append(("markdown export", "# Client Portfolio Review Brief" in markdown
                   and all(r in markdown for r in expected_rule_ids), ""))

    html = brief_to_html(brief)
    checks.append(("html export", html.startswith("<!DOCTYPE html>")
                   and DISCLAIMER_FRAGMENT in html, ""))

    if not args.skip_pdf:
        import io

        from pypdf import PdfReader

        from app.pdf_export import html_to_pdf_bytes

        pdf_bytes = html_to_pdf_bytes(html)
        pdf_text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
        checks.append(("pdf export + text extraction",
                       all(r in pdf_text for r in expected_rule_ids)
                       and DISCLAIMER_FRAGMENT in pdf_text,
                       f"{len(pdf_bytes)} bytes"))

    print()
    failed = False
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        failed = failed or not passed
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else
                                        f" ({detail})" if detail else ""))

    print()
    if failed:
        print("RESULT: FAIL — llm-v1 verification did not pass; see checks above.")
        return 1
    excerpt = sections["executive_summary"][0][:180]
    print(f"Model narrative excerpt: {excerpt}")
    print("RESULT: PASS — llm-v1 brief verified against the configured provider.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
