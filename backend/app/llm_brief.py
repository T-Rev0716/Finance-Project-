"""LLM-backed brief generation (llm-v1): narrative drafting only.

The deterministic analysis is the source of truth. The model receives a
normalized input packet (never raw database objects) and may return ONLY
the five narrative sections as strict JSON. The data-bearing sections —
portfolio snapshot, evidence table, data assumptions, compliance
disclaimer — are copied verbatim from the deterministic generator, and
review items keep their deterministic rule_id/severity/title, so evidence
mapping and disclaimers cannot be altered by the model.

Validation compares the model output back against the packet:
- strict schema (exactly the five allowed keys, non-empty bounded strings),
- review items map 1:1, in order, to the stored flag rule_ids,
- an extended banned-phrase scan (advisor-support language only),
- a fact-token guard: every dollar amount, percentage, ticker-like token,
  and snake_case identifier in the narrative must already appear in the
  packet, so hallucinated values trigger fallback.

Any failure raises LLMBriefError; the caller falls back to deterministic-v1.
"""

import json
import re

from . import compliance
from .brief import _deterministic_brief

PROMPT_VERSION = "brief-prompt-v2"

NARRATIVE_KEYS = [
    "executive_summary",
    "key_review_items",
    "advisor_talking_points",
    "client_discussion_questions",
    "follow_up_items",
]

MAX_STRING_LENGTH = 1500
MAX_LIST_ITEMS = 15

SYSTEM_PROMPT = """\
You are a drafting assistant for AdvisorLens, an advisor-support portfolio review tool.
You will receive a JSON packet containing the complete results of a deterministic
portfolio analysis: client profile, portfolio summary, and review flags with rule IDs,
thresholds, and evidence.

Your only job is to draft professional, concise, advisor-ready NARRATIVE language for a
Client Portfolio Review Brief, based strictly on that packet.

Hard rules:
- The deterministic analysis is the source of truth. Do not add, remove, reinterpret,
  or re-rank findings. Do not mention holdings, market data, risks, or facts that are
  not in the packet.
- This is advisor-support material, not investment, tax, or legal advice. Use
  advisor-support language only: review, evaluate, consider, may indicate.
- Never suggest buying, selling, holding, trading, rebalancing, tax-loss harvesting,
  or performance expectations. Never use: buy, sell, hold, guaranteed, risk-free,
  best investment, will outperform, should invest, tax-loss harvesting, harvest losses,
  execute trades, rebalance now, make changes to taxable positions.
- Every dollar amount, percentage, and ticker you write must appear in the packet.
  Copy numeric values exactly as they appear (rounding to fewer decimal places is
  acceptable); never compute, convert, estimate, or introduce new figures.
- Produce exactly one key review item per flag in the packet, in the same order, each
  carrying that flag's exact rule_id.
- Do not refer to yourself, AI, language models, prompts, or the drafting process.
- Write plain sentences only: no markdown, bullets, headers, or formatting inside strings.

Return ONLY a JSON object (no prose, no code fences) with exactly these keys:
{
  "executive_summary": ["paragraph", ...],
  "key_review_items": [{"rule_id": "<exact rule_id>", "narrative": "..."}, ...],
  "advisor_talking_points": ["...", ...],
  "client_discussion_questions": ["...", ...],
  "follow_up_items": ["...", ...]
}
If the packet contains no flags, "key_review_items" must be an empty list.
"""


class LLMBriefError(RuntimeError):
    """Any LLM-path failure (provider, parsing, validation). Triggers fallback."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def build_input_packet(analysis: dict) -> dict:
    """Normalize the stored analysis record into the only input the model sees."""
    summary = analysis["summary"]
    return {
        "analysis_id": analysis["id"],
        "source_name": analysis["source_name"],
        "file_sha256": analysis["file_sha256"],
        "created_at": analysis["created_at"],
        "engine_version": analysis["engine_version"],
        "risk_tolerance": analysis["risk_tolerance"],
        "client_goal": analysis["client_goal"],
        "summary": {
            "total_market_value": summary["total_market_value"],
            "total_cost_basis": summary["total_cost_basis"],
            "total_unrealized_gain_loss": summary["total_unrealized_gain_loss"],
            "holdings_count": summary["holdings_count"],
            "asset_allocation": summary["asset_allocation"],
            "sector_allocation": summary["sector_allocation"],
            "account_type_allocation": summary["account_type_allocation"],
            "top_holdings": summary["top_holdings"],
        },
        "flags": [
            {
                "rule_id": f["rule_id"],
                "severity": f["severity"],
                "title": f["title"],
                "message": f["message"],
                "threshold": f["threshold"],
                "evidence": f["evidence"],
            }
            for f in analysis["flags"]
        ],
    }


# --- Fact-token guard ---------------------------------------------------------

_MONEY_RE = re.compile(r"\$\s?-?[\d,]+(?:\.\d+)?")
_PERCENT_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?\s?%")
_UPPER_RE = re.compile(r"\b[A-Z]{2,6}\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# Generic uppercase tokens that are fine in narrative without being tickers.
_UPPER_WHITELIST = {"US", "USD", "ID", "CSV", "OK"}


def _to_float(token: str) -> float:
    return float(token.replace("$", "").replace("%", "").replace(",", "").strip())


def _token_decimals(token: str) -> int:
    digits = token.replace("$", "").replace("%", "").replace(",", "").strip()
    if "." in digits:
        return len(digits.split(".", 1)[1])
    return 0


def _number_matches(token: str, numbers: set[float]) -> bool:
    """A money/percent token matches if it equals a packet number, or if a
    packet number rounds to it at the token's own precision — so narrative
    like '57%' is accepted when the packet contains 57.22, while a value no
    packet number rounds to (e.g. $999,999.99) still fails."""
    value = _to_float(token)
    if value in numbers:
        return True
    decimals = _token_decimals(token)
    return any(round(n, decimals) == value for n in numbers)


def _allowed_facts(packet: dict) -> tuple[set[float], set[str], set[str]]:
    """Every number, uppercase token, and snake_case identifier the packet contains."""
    blob = json.dumps(packet)
    numbers: set[float] = set()
    for token in _NUMBER_RE.findall(blob):
        try:
            value = _to_float(token)
        except ValueError:
            continue
        numbers.add(value)
        numbers.add(abs(value))
    upper = set(_UPPER_RE.findall(blob)) | _UPPER_WHITELIST
    snake = set(_SNAKE_RE.findall(blob))
    return numbers, upper, snake


def find_fact_errors(texts: list[str], packet: dict) -> list[str]:
    """Flag any dollar amount, percentage, ticker-like token, or snake_case
    identifier in the narrative that does not appear in the input packet."""
    numbers, upper, snake = _allowed_facts(packet)
    errors: list[str] = []
    for text in texts:
        for token in _MONEY_RE.findall(text):
            if not _number_matches(token, numbers):
                errors.append(f"dollar amount {token!r} does not appear in the analysis data")
        for token in _PERCENT_RE.findall(text):
            if not _number_matches(token, numbers):
                errors.append(f"percentage {token!r} does not appear in the analysis data")
        for token in _UPPER_RE.findall(text):
            if token not in upper:
                errors.append(f"symbol {token!r} does not appear in the analysis data")
        for token in _SNAKE_RE.findall(text):
            if token not in snake:
                errors.append(f"identifier {token!r} does not appear in the analysis data")
    return errors


# --- Schema / grounding validation --------------------------------------------

def _string_list_errors(key: str, value) -> list[str]:
    if not isinstance(value, list):
        return [f"{key} must be a list"]
    if not value:
        return [f"{key} must not be empty"]
    if len(value) > MAX_LIST_ITEMS:
        return [f"{key} has too many items"]
    errors = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{key} items must be non-empty strings")
        elif len(item) > MAX_STRING_LENGTH:
            errors.append(f"{key} item exceeds {MAX_STRING_LENGTH} characters")
    return errors


def validate_llm_payload(payload, packet: dict) -> list[str]:
    """Return every problem found; an empty list means the payload is accepted."""
    if not isinstance(payload, dict):
        return ["response is not a JSON object"]

    errors: list[str] = []
    unexpected = sorted(set(payload) - set(NARRATIVE_KEYS))
    if unexpected:
        errors.append(f"unexpected keys {unexpected} (only narrative sections are accepted)")
    missing = [k for k in NARRATIVE_KEYS if k not in payload]
    if missing:
        errors.append(f"missing keys {missing}")
    if errors:
        return errors

    for key in ("executive_summary", "advisor_talking_points",
                "client_discussion_questions", "follow_up_items"):
        errors.extend(_string_list_errors(key, payload[key]))

    items = payload["key_review_items"]
    expected_rule_ids = [f["rule_id"] for f in packet["flags"]]
    if not isinstance(items, list):
        errors.append("key_review_items must be a list")
    else:
        got_rule_ids = []
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != {"rule_id", "narrative"}
                or not isinstance(item.get("rule_id"), str)
                or not isinstance(item.get("narrative"), str)
                or not item["narrative"].strip()
                or len(item["narrative"]) > MAX_STRING_LENGTH
            ):
                errors.append(
                    "key_review_items entries must be {rule_id, narrative} with a "
                    "non-empty bounded narrative"
                )
                break
            got_rule_ids.append(item["rule_id"])
        else:
            if got_rule_ids != expected_rule_ids:
                errors.append(
                    f"review items must map exactly to the stored flags: "
                    f"expected rule_ids {expected_rule_ids}, got {got_rule_ids}"
                )
    if errors:
        return errors

    narrative_strings = [
        *payload["executive_summary"],
        *(item["narrative"] for item in items),
        *payload["advisor_talking_points"],
        *payload["client_discussion_questions"],
        *payload["follow_up_items"],
    ]
    for text in narrative_strings:
        violations = compliance.find_llm_violations(text)
        if violations:
            errors.append(f"banned phrase(s) {violations} in {text!r}")
    errors.extend(find_fact_errors(narrative_strings, packet))
    return errors


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text


def generate_llm_sections(analysis: dict, provider) -> dict:
    """Deterministic base -> packet -> model call -> validate -> merge narrative."""
    base = _deterministic_brief(analysis)
    packet = build_input_packet(analysis)

    from .llm import LLMProviderError  # local import to keep module deps one-directional

    try:
        raw = provider.complete_json(SYSTEM_PROMPT, json.dumps(packet, indent=2))
    except LLMProviderError as exc:
        raise LLMBriefError(f"provider error: {exc}") from exc

    try:
        payload = json.loads(_strip_code_fences(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMBriefError(f"invalid JSON from model: {exc}") from exc

    errors = validate_llm_payload(payload, packet)
    if errors:
        raise LLMBriefError("validation failed: " + "; ".join(errors[:5]))

    sections = dict(base)
    sections["executive_summary"] = payload["executive_summary"]
    sections["advisor_talking_points"] = payload["advisor_talking_points"]
    sections["client_discussion_questions"] = payload["client_discussion_questions"]
    sections["follow_up_items"] = payload["follow_up_items"]
    sections["key_review_items"] = [
        {**base_item, "message": llm_item["narrative"]}
        for base_item, llm_item in zip(base["key_review_items"], payload["key_review_items"])
    ]
    # portfolio_snapshot, evidence_table, data_assumptions, and
    # compliance_disclaimer remain the deterministic originals by design.
    return sections
