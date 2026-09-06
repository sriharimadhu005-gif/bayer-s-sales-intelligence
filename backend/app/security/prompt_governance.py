"""
Horeca Sales Intelligence — Prompt Governance Module.

Pre-LLM security gate that screens every user message for:
  - Prompt injection / override attempts
  - Role escalation
  - System prompt / secret extraction
  - Data modification requests
  - Direct SQL injection
  - Security control bypass attempts
  - Multi-step jailbreak patterns

Design: rule-based with text normalisation (no LLM dependency).
Each detection stage returns immediately on a high-confidence match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .constants import (
    INJECTION_PATTERNS,
    LEETSPEAK_MAP,
    THREAT_SCORE_THRESHOLD,
    SAFE_REFUSAL_MESSAGE,
    PROMPT_REVEAL_REFUSAL,
)

__all__ = ["screen_prompt", "GovernanceResult"]


# ═══════════════════════════════════════════════════════════════════════
# Result type
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class GovernanceResult:
    """Outcome of the prompt governance screen."""
    is_safe: bool
    category: str | None = None          # e.g. "prompt_injection", "role_escalation"
    reason: str | None = None            # Human-readable explanation
    confidence: float = 0.0              # 0.0 – 1.0
    matched_patterns: list[str] = field(default_factory=list)
    refusal_message: str = SAFE_REFUSAL_MESSAGE

    def __bool__(self) -> bool:          # truthy = safe
        return self.is_safe


# ═══════════════════════════════════════════════════════════════════════
# Text normalisation helpers
# ═══════════════════════════════════════════════════════════════════════

def _normalise_unicode(text: str) -> str:
    """NFKC-normalise and strip accents / diacritics."""
    normalised = unicodedata.normalize("NFKC", text)
    # Strip combining characters (accents) to defeat homoglyph attacks
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", normalised)
        if unicodedata.category(ch) != "Mn"
    )
    return stripped


def _decode_leetspeak(text: str) -> str:
    """Convert common leetspeak substitutions back to ASCII."""
    return "".join(LEETSPEAK_MAP.get(ch, ch) for ch in text)


def _collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace (including zero-width chars) to single spaces."""
    # Remove zero-width characters
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _prepare(text: str) -> str:
    """Full normalisation pipeline: unicode → leetspeak → whitespace → lowercase."""
    text = _normalise_unicode(text)
    text = _decode_leetspeak(text)
    text = _collapse_whitespace(text)
    return text.lower()


# ═══════════════════════════════════════════════════════════════════════
# Detection engine
# ═══════════════════════════════════════════════════════════════════════

def _despaced(text: str) -> str:
    """
    Detect and reverse character-spacing obfuscation.
    'f o r g e t  y o u r  r u l e s' → 'forget your rules'

    Heuristic: if the text has many single characters separated by spaces,
    collapse them. Only applies when > 40% of 'words' are single characters.
    """
    words = text.split()
    if not words:
        return text
    single_char_count = sum(1 for w in words if len(w) == 1)
    if single_char_count / len(words) > 0.3:
        # Collapse single-char runs into words, keeping multi-char words separate
        result = []
        current_word = []
        for w in words:
            if len(w) == 1:
                current_word.append(w)
            else:
                if current_word:
                    result.append("".join(current_word))
                    current_word = []
                result.append(w)
        if current_word:
            result.append("".join(current_word))
        return " ".join(result)
    return text


def _scan_patterns(original: str, normalised: str) -> GovernanceResult:
    """
    Run the original AND normalised text against all injection patterns.
    Uses a cumulative scoring system: if total score ≥ threshold, block.
    High-confidence single matches (≥ 0.90) block immediately.
    """
    # Also generate a de-spaced variant to catch character-spacing obfuscation
    despaced = _despaced(normalised)
    texts_to_check = [original, normalised]
    if despaced != normalised:
        texts_to_check.append(despaced)

    top_score: float = 0.0
    top_category: str | None = None
    top_reason: str | None = None
    matched: list[str] = []

    for regex, category, score, reason in INJECTION_PATTERNS:
        # Check against original, normalised, and de-spaced variants
        if any(regex.search(t) for t in texts_to_check):
            matched.append(f"{category}: {reason}")

            if score > top_score:
                top_score = score
                top_category = category
                top_reason = reason

            # Immediate block on very high confidence
            if score >= 0.90:
                refusal = (
                    PROMPT_REVEAL_REFUSAL
                    if category == "secret_extraction"
                    else SAFE_REFUSAL_MESSAGE
                )
                return GovernanceResult(
                    is_safe=False,
                    category=category,
                    reason=reason,
                    confidence=score,
                    matched_patterns=matched,
                    refusal_message=refusal,
                )

    # Check cumulative threshold
    if top_score >= THREAT_SCORE_THRESHOLD:
        refusal = (
            PROMPT_REVEAL_REFUSAL
            if top_category == "secret_extraction"
            else SAFE_REFUSAL_MESSAGE
        )
        return GovernanceResult(
            is_safe=False,
            category=top_category,
            reason=top_reason,
            confidence=top_score,
            matched_patterns=matched,
            refusal_message=refusal,
        )

    return GovernanceResult(is_safe=True, confidence=0.0, matched_patterns=matched)


# Well-known dangerous phrases for concatenated (all-spaces-removed) detection
_CONCAT_DANGER_PHRASES = [
    ("ignorepreviousinstructions", "prompt_injection", "Obfuscated: ignore previous instructions"),
    ("forgetyourrules", "prompt_injection", "Obfuscated: forget your rules"),
    ("forgetyourinstructions", "prompt_injection", "Obfuscated: forget your instructions"),
    ("disregardtheinstructions", "prompt_injection", "Obfuscated: disregard the instructions"),
    ("overridesystemprompt", "prompt_injection", "Obfuscated: override system prompt"),
    ("ignoreyourrules", "prompt_injection", "Obfuscated: ignore your rules"),
    ("deletefrom", "sql_injection", "Obfuscated: DELETE FROM"),
    ("droptable", "sql_injection", "Obfuscated: DROP TABLE"),
    ("insertinto", "sql_injection", "Obfuscated: INSERT INTO"),
    ("systemprompt", "secret_extraction", "Obfuscated: system prompt"),
    ("apikey", "secret_extraction", "Obfuscated: API key"),
]


def _check_concat_obfuscation(text: str) -> GovernanceResult | None:
    """
    Check for dangerous phrases in fully-concatenated text (all spaces removed).
    This catches character-spacing obfuscation that defeats regex patterns.
    """
    concat = text.lower().replace(" ", "")
    for phrase, category, reason in _CONCAT_DANGER_PHRASES:
        if phrase in concat:
            refusal = (
                PROMPT_REVEAL_REFUSAL
                if category == "secret_extraction"
                else SAFE_REFUSAL_MESSAGE
            )
            return GovernanceResult(
                is_safe=False,
                category=category,
                reason=reason,
                confidence=0.85,
                matched_patterns=[f"{category}: {reason}"],
                refusal_message=refusal,
            )
    return None


def _check_raw_sql_keywords(text: str) -> GovernanceResult | None:
    """
    Detect raw modifying SQL keywords appearing prominently in the message.
    This catches messages like "DELETE FROM customers" even without
    the full injection pattern.
    """
    upper = text.upper()
    dangerous_starters = [
        ("INSERT INTO", "sql_injection", "Raw INSERT statement in prompt"),
        ("UPDATE ", "sql_injection", "Raw UPDATE statement in prompt"),
        ("DELETE FROM", "sql_injection", "Raw DELETE statement in prompt"),
        ("DROP TABLE", "sql_injection", "Raw DROP TABLE statement in prompt"),
        ("DROP DATABASE", "sql_injection", "Raw DROP DATABASE statement in prompt"),
        ("ALTER TABLE", "sql_injection", "Raw ALTER TABLE statement in prompt"),
        ("TRUNCATE TABLE", "sql_injection", "Raw TRUNCATE statement in prompt"),
        ("TRUNCATE ", "sql_injection", "Raw TRUNCATE statement in prompt"),
        ("CREATE TABLE", "sql_injection", "Raw CREATE TABLE statement in prompt"),
        ("GRANT ", "sql_injection", "Raw GRANT statement in prompt"),
        ("REVOKE ", "sql_injection", "Raw REVOKE statement in prompt"),
    ]

    for keyword, category, reason in dangerous_starters:
        if keyword in upper:
            return GovernanceResult(
                is_safe=False,
                category=category,
                reason=reason,
                confidence=0.95,
                matched_patterns=[f"{category}: {reason}"],
                refusal_message=SAFE_REFUSAL_MESSAGE,
            )
    return None


def _check_multi_step_jailbreak(
    message: str,
    conversation_history: list[dict] | None,
) -> GovernanceResult | None:
    """
    Detect multi-step jailbreak patterns by analysing conversation history.
    Looks for escalation sequences where earlier messages set up context
    for a later malicious request.
    """
    if not conversation_history or len(conversation_history) < 2:
        return None

    normalised_msg = _prepare(message)

    # Pattern: current message contains mild escalation keywords AND
    # previous messages also contained escalation keywords (building up)
    escalation_keywords = [
        "ignore", "forget", "override", "pretend", "act as",
        "new rules", "new instructions", "disable", "bypass",
        "admin", "root", "superuser", "unrestricted",
        "no restrictions", "no rules", "no limits",
    ]

    history_escalation_count = 0
    for entry in conversation_history[-6:]:
        content = _prepare(entry.get("content", ""))
        if entry.get("role") == "user":
            hits = sum(1 for kw in escalation_keywords if kw in content)
            if hits > 0:
                history_escalation_count += hits

    current_hits = sum(1 for kw in escalation_keywords if kw in normalised_msg)

    # If there's a pattern of escalation across messages, flag it
    if history_escalation_count >= 2 and current_hits >= 1:
        return GovernanceResult(
            is_safe=False,
            category="multi_step_jailbreak",
            reason="Detected escalation pattern across conversation history",
            confidence=0.80,
            matched_patterns=["multi_step_jailbreak: Escalation pattern detected"],
            refusal_message=SAFE_REFUSAL_MESSAGE,
        )

    return None


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def screen_prompt(
    message: str,
    conversation_history: list[dict] | None = None,
) -> GovernanceResult:
    """
    Screen a user prompt for malicious intent before it reaches the LLM.

    Parameters
    ----------
    message : str
        The raw user message.
    conversation_history : list[dict] | None
        Previous conversation messages (role + content dicts), used for
        multi-step jailbreak detection.

    Returns
    -------
    GovernanceResult
        .is_safe=True  → message may proceed to the LLM.
        .is_safe=False → message is blocked; return .refusal_message to user.
    """
    if not message or not message.strip():
        return GovernanceResult(is_safe=True)

    original = message.strip()
    normalised = _prepare(original)

    # Stage 1: Pattern-based detection
    pattern_result = _scan_patterns(original, normalised)
    if not pattern_result.is_safe:
        return pattern_result

    # Stage 2: Concatenated-text obfuscation detection
    concat_result = _check_concat_obfuscation(original)
    if concat_result is not None:
        return concat_result

    # Stage 3: Raw SQL keyword detection
    sql_result = _check_raw_sql_keywords(original)
    if sql_result is not None:
        return sql_result

    # Stage 4: Multi-step jailbreak detection
    jailbreak_result = _check_multi_step_jailbreak(
        original, conversation_history
    )
    if jailbreak_result is not None:
        return jailbreak_result

    # All stages passed
    return GovernanceResult(is_safe=True)
