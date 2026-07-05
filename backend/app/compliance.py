"""Compliance language guard.

AdvisorLens is an advisor-support tool, not a robo-advisor. Output must
never contain direct-advice language. This module is used both by tests
and as a runtime guard on every generated flag.
"""

import re

BANNED_PHRASES = [
    r"\bbuy\b",
    r"\bsell\b",
    r"\bguaranteed?\b",
    r"\brisk[- ]free\b",
    r"\bbest investment\b",
    r"\bwill outperform\b",
]

_BANNED_RE = re.compile("|".join(BANNED_PHRASES), re.IGNORECASE)


class ComplianceError(RuntimeError):
    """Raised when generated text violates the language policy."""


def find_violations(text: str) -> list[str]:
    return [m.group(0) for m in _BANNED_RE.finditer(text)]


def assert_compliant_text(text: str, context: str = "output") -> None:
    violations = find_violations(text)
    if violations:
        raise ComplianceError(f"Banned phrase(s) {violations} found in {context}: {text!r}")


def assert_compliant_flags(flags: list) -> None:
    """Check every human-readable field of every flag before it leaves the engine."""
    for flag in flags:
        for field_name in ("title", "message"):
            assert_compliant_text(getattr(flag, field_name), context=f"{flag.rule_id}.{field_name}")
        if flag.rule_id.startswith("tax_") or "tax-loss" in flag.message.lower():
            evidence = flag.evidence or {}
            if evidence.get("account_type") not in (None,) and evidence.get("is_retirement_account"):
                raise ComplianceError(
                    f"Tax-loss language attached to a retirement account in {flag.rule_id}: {evidence}"
                )
