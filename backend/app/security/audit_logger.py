"""
Horeca Sales Intelligence — Security Audit Logger.

Structured logging for all security-related events:
  - Prompt blocked by governance
  - SQL rejected by validator
  - SQL validated and executed

Writes to a JSONL file (one JSON object per line) for easy parsing.
Thread-safe. Also emits WARNING-level logs via Python's logging module.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

__all__ = ["log_security_event", "SecurityEvent"]

logger = logging.getLogger("security.audit")

# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs",
)
_LOG_FILE = os.path.join(_LOG_DIR, "security_audit.jsonl")
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════
# Event type
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SecurityEvent:
    """A single security audit event."""
    timestamp: str
    event_type: str                       # "prompt_blocked", "sql_rejected", "sql_validated"
    conversation_id: str | None = None
    user_prompt: str = ""
    detection_category: str | None = None  # e.g. "prompt_injection", "sql_injection"
    reason: str | None = None
    generated_sql: str | None = None
    validation_result: str | None = None   # "valid" or "rejected:<reason>"
    confidence: float | None = None
    matched_patterns: list[str] | None = None
    tables_accessed: list[str] | None = None


# ═══════════════════════════════════════════════════════════════════════
# File writer
# ═══════════════════════════════════════════════════════════════════════

def _ensure_log_dir():
    """Create the log directory if it doesn't exist."""
    os.makedirs(_LOG_DIR, exist_ok=True)


def _write_event(event: SecurityEvent):
    """Append a security event to the JSONL log file (thread-safe)."""
    _ensure_log_dir()
    record = asdict(event)
    line = json.dumps(record, ensure_ascii=False, default=str)

    with _lock:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.error("Failed to write security audit log: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def log_security_event(
    event_type: str,
    user_prompt: str = "",
    conversation_id: str | None = None,
    detection_category: str | None = None,
    reason: str | None = None,
    generated_sql: str | None = None,
    validation_result: str | None = None,
    confidence: float | None = None,
    matched_patterns: list[str] | None = None,
    tables_accessed: list[str] | None = None,
):
    """
    Log a security event to the audit trail.

    Parameters
    ----------
    event_type : str
        One of "prompt_blocked", "sql_rejected", "sql_validated", "sql_executed".
    user_prompt : str
        The user's original message (may be truncated for privacy).
    conversation_id : str | None
        The conversation ID, if available.
    detection_category : str | None
        The category of threat detected (e.g. "prompt_injection").
    reason : str | None
        Human-readable explanation.
    generated_sql : str | None
        The SQL that was generated (if any).
    validation_result : str | None
        The validation outcome string.
    confidence : float | None
        Confidence score of detection (0.0–1.0).
    matched_patterns : list[str] | None
        List of pattern descriptions that matched.
    tables_accessed : list[str] | None
        Tables/views referenced in the SQL.
    """
    event = SecurityEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        conversation_id=conversation_id,
        user_prompt=user_prompt[:500],  # Truncate very long prompts
        detection_category=detection_category,
        reason=reason,
        generated_sql=generated_sql[:1000] if generated_sql else None,
        validation_result=validation_result,
        confidence=confidence,
        matched_patterns=matched_patterns,
        tables_accessed=tables_accessed,
    )

    _write_event(event)

    # Also log to Python's logging system
    if event_type in ("prompt_blocked", "sql_rejected"):
        logger.warning(
            "SECURITY [%s] category=%s reason=%s conv=%s",
            event_type,
            detection_category,
            reason,
            conversation_id,
        )
    else:
        logger.info(
            "SECURITY [%s] conv=%s tables=%s",
            event_type,
            conversation_id,
            tables_accessed,
        )
