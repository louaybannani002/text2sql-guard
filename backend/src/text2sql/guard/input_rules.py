"""Layer 1 of the input guard: fast, deterministic rules (no LLM).

SQL is detected by *statement shape* (``DROP TABLE``, ``DELETE FROM``, ``UPDATE … SET``), not by
bare keywords: business questions say "did revenue drop", "orders were deleted", "sellers who
grant installments", and must not be blocked for it. The LLM classifier (layer 2) handles what
rules cannot express.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

MAX_LENGTH = 500

type RuleCategory = Literal["invalid_input", "sql_command", "prompt_injection"]

# Unicode categories never needed in a question: control (Cc), invisible format characters
# such as zero-width spaces used to hide words from filters (Cf), private use and surrogates.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})
_ALLOWED_WHITESPACE = frozenset("\n\r\t")


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


_OBJECT = r"(table|schema|database|view|materialized\s+view|index|role|user|function|extension)"

SQL_RULES: dict[str, re.Pattern[str]] = {
    "drop_object": _rx(rf"\bdrop\s+{_OBJECT}\b"),
    "delete_from": _rx(r"\bdelete\s+from\b"),
    "update_set": _rx(r"\bupdate\s+[\w.\"]+\s+set\b"),
    "insert_into": _rx(r"\binsert\s+into\b"),
    "truncate": _rx(r"\btruncate\s+(table\s+)?[\w.\"]+"),
    "alter_object": _rx(rf"\balter\s+({_OBJECT}|system)\b"),
    "create_object": _rx(rf"\bcreate\s+(or\s+replace\s+)?{_OBJECT}\b"),
    # A privilege word is required: "sellers grant installments to customers" is a question.
    "grant_revoke": _rx(
        r"\b(grant|revoke)\s+(all|select|insert|update|delete|truncate|references|trigger"
        r"|usage|execute|connect|create|temporary|temp)\b.{0,80}\b(on|to|from)\b"
        r"|\bgrant\b.{0,60}\bto\s+public\b"
    ),
    "copy_program_or_file": _rx(r"\bcopy\b.{0,80}\b(to|from)\s+(program|stdout|'/)"),
    "dangerous_function": _rx(
        r"\b(pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|dblink)\s*\("
    ),
    "stacked_statement": _rx(r";\s*(drop|delete|update|insert|alter|create|grant|truncate)\b"),
    "comment_terminator": _rx(r"'\s*;?\s*--"),
    "tautology": _rx(r"'\s*or\s+'?\d+'?\s*=\s*'?\d+"),
    "union_select": _rx(r"\bunion\s+(all\s+)?select\b"),
}

INJECTION_RULES: dict[str, re.Pattern[str]] = {
    "ignore_instructions": _rx(
        r"\b(ignore|disregard|forget|override|skip)\b.{0,30}"
        r"\b(previous|prior|above|earlier|preceding|all|your|the|system)\b.{0,20}"
        r"\b(instructions?|rules?|prompts?|guidelines|directions|messages?|constraints)\b"
    ),
    "system_prompt": _rx(r"\b(system|developer|hidden|initial)\s+(prompt|message|instructions?)\b"),
    # "your rules" is about the assistant; "the rules for free shipping" is a normal question.
    "reveal_instructions": _rx(
        r"\b(repeat|reveal|print|output|show|display|tell\s+me|what\s+are)\b.{0,30}"
        r"\byour\s+(instructions|prompt|rules|guidelines|configuration)\b"
        r"|\b(repeat|reveal|print|output)\b.{0,30}\b(the|these|those)\s+(instructions|prompt)\b"
    ),
    "role_play": _rx(
        r"\b(you\s+are\s+now|from\s+now\s+on\s+you|pretend\s+(to\s+be|you\s+are)|act\s+as\s+(an?\s+)?"
        r"(admin|administrator|dba|developer|root|superuser|unrestricted|jailbroken))\b"
    ),
    "jailbreak": _rx(r"\b(jailbreak|do\s+anything\s+now|dan\s+mode|developer\s+mode)\b"),
    "bypass_safety": _rx(
        r"\b(bypass|disable|turn\s+off|circumvent|evade)\b.{0,25}"
        r"\b(safety|security|guard|guardrails?|filters?|restrictions|checks|validation)\b"
    ),
    "prompt_tags": _rx(r"</?\s*(question|schema|examples|system|assistant|user)\s*>|<\|[^|]*\|>"),
}


@dataclass(frozen=True, slots=True)
class RuleHit:
    """Why layer 1 rejected the input."""

    category: RuleCategory
    rule: str
    reason: str


def normalize(text: str) -> str:
    """NFKC (folds look-alikes such as full-width or Roman-numeral letters) + single spaces."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def check_rules(question: str) -> RuleHit | None:
    """Return the first rule the question breaks, or None if layer 1 lets it through."""
    stripped = question.strip()
    if not stripped:
        return RuleHit("invalid_input", "empty", "The question is empty.")
    if len(stripped) > MAX_LENGTH:
        return RuleHit(
            "invalid_input", "too_long", f"Questions are limited to {MAX_LENGTH} characters."
        )
    for char in stripped:
        if unicodedata.category(char) in _FORBIDDEN_CATEGORIES and char not in _ALLOWED_WHITESPACE:
            return RuleHit(
                "invalid_input",
                "control_character",
                "The question contains control or invisible characters.",
            )
    text = normalize(stripped)
    for name, pattern in SQL_RULES.items():
        if pattern.search(text):
            return RuleHit(
                "sql_command",
                name,
                "Ask a question in plain language; SQL commands are not accepted.",
            )
    for name, pattern in INJECTION_RULES.items():
        if pattern.search(text):
            return RuleHit(
                "prompt_injection", name, "The question tries to change how the assistant works."
            )
    return None
