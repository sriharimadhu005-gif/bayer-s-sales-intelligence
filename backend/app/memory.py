"""
Horeca Sales Intelligence — Conversation Memory Manager.

Provides ChatGPT-style conversation memory with:
  - Per-session message history (user + assistant + metadata)
  - Structured state tracking (current report, last query, last chart, etc.)
  - Token-aware rolling context window
  - Automatic compression of old messages into bullet-point summaries
  - Coreference-resolution context injection

Design:
  In-memory storage keyed by conversation_id. Each conversation maintains
  a list of ConversationMessage objects, a compressed summary of older
  exchanges, and a StructuredState dict that tracks the "working context"
  (last report, last SQL, last chart, etc.) so the LLM can resolve
  follow-up references without re-inferring from raw text.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

# Qwen3 32B context window is 32,768 tokens.
# Reserve ~2,500 for system prompt, ~4,000 for response, ~500 buffer.
MAX_CONTEXT_TOKENS = 20_000       # conservative budget for history
COMPRESSION_THRESHOLD = 16_000    # trigger compression at 80% of budget
MIN_RECENT_MESSAGES = 8           # never compress the last N messages (4 exchanges)
CHARS_PER_TOKEN = 4               # rough estimate for Qwen3 tokenizer


# ═══════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ConversationMessage:
    """A single message in the conversation history."""
    role: str                              # "user" | "assistant" | "summary"
    content: str                           # text content
    timestamp: str                         # ISO 8601 timestamp
    token_count: int                       # estimated token count
    metadata: dict[str, Any] | None = None # tables, charts, SQL, report specs


@dataclass
class StructuredState:
    """
    Tracks the 'working context' of a conversation — what the LLM needs
    to resolve follow-up references like "it", "same report", "previous query".
    """
    current_report: dict[str, Any] | None = None   # {month, type, format, output, filename, ...}
    last_query: dict[str, Any] | None = None        # {sql, results_summary, row_count}
    last_chart: dict[str, Any] | None = None         # {type, data_summary}
    last_table: dict[str, Any] | None = None         # {columns, row_count}
    last_generated_filename: str | None = None
    last_report_prefill: dict[str, Any] | None = None
    uploaded_file: str | None = None
    selected_template: str | None = None
    last_dataset: list[dict[str, Any]] | None = None # Full structured rows for report generation
    last_sql: str | None = None                      # SQL query that produced last_dataset
    last_title: str | None = None                    # Topic or query intent title
    last_columns: list[str] | None = None            # Column names in order
    last_filters: dict[str, Any] | None = None       # Applied filters (dates, routes, etc.)
    pending_clarification: dict[str, Any] | None = None  # Active entity clarification {original_message, entity_type, candidates, ...}
    resolved_entities: dict[str, Any] | None = None      # Canonical entities resolved for current/last query

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict, omitting None values and omitting raw datasets."""
        out = {}
        for k, v in self.__dict__.items():
            if v is None:
                continue
            if k == "last_dataset":
                out["has_cached_dataset"] = len(v) if isinstance(v, list) else 0
            else:
                out[k] = v
        return out

    def is_empty(self) -> bool:
        """Return True if no state has been recorded yet."""
        return all(v is None for v in self.__dict__.values())


@dataclass
class Conversation:
    """Full conversation state for a single chat session."""
    id: str
    messages: list[ConversationMessage] = field(default_factory=list)
    summary: str = ""                      # compressed summary of older messages
    structured_state: StructuredState = field(default_factory=StructuredState)
    cached_reports: dict[str, dict] = field(default_factory=dict) # report_id -> {bytes, filename, created_at}
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_tokens: int = 0


# ═══════════════════════════════════════════════════════════════════════
# In-memory conversation store
# ═══════════════════════════════════════════════════════════════════════

_store: dict[str, Conversation] = {}


def _get_or_create(conv_id: str) -> Conversation:
    """Retrieve an existing conversation or create a new one."""
    if conv_id not in _store:
        _store[conv_id] = Conversation(id=conv_id)
    return _store[conv_id]


# ═══════════════════════════════════════════════════════════════════════
# Token estimation
# ═══════════════════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """
    Rough token count. Qwen3 uses a BPE tokenizer; 1 token ≈ 4 characters
    is a reasonable conservative estimate for English + SQL + JSON.
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


# ═══════════════════════════════════════════════════════════════════════
# Core API
# ═══════════════════════════════════════════════════════════════════════

def add_message(
    conv_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> ConversationMessage:
    """
    Append a message to the conversation and update token counts.

    Parameters
    ----------
    conv_id  : Conversation identifier.
    role     : "user" or "assistant".
    content  : The text content of the message.
    metadata : Optional dict of structured data (table, chart, SQL, report spec).

    Returns
    -------
    The created ConversationMessage.
    """
    conv = _get_or_create(conv_id)

    # Estimate tokens: content + serialised metadata summary
    meta_text = ""
    if metadata:
        # Include a compact representation for token counting
        meta_parts = []
        if metadata.get("sql"):
            meta_parts.append(f"SQL: {metadata['sql']}")
        if metadata.get("table"):
            t = metadata["table"]
            cols = t.get("columns", [])
            row_count = len(t.get("rows", []))
            meta_parts.append(f"Table: {cols} ({row_count} rows)")
        if metadata.get("chart"):
            meta_parts.append(f"Chart: {metadata['chart'].get('type', 'unknown')}")
        if metadata.get("report_prefill"):
            meta_parts.append(f"Report: {metadata['report_prefill']}")
        meta_text = " | ".join(meta_parts)

    token_count = estimate_tokens(content) + estimate_tokens(meta_text)

    msg = ConversationMessage(
        role=role,
        content=content,
        timestamp=datetime.now().isoformat(),
        token_count=token_count,
        metadata=metadata,
    )

    conv.messages.append(msg)
    conv.total_tokens += token_count

    # Auto-compress if we exceed the threshold
    if conv.total_tokens > COMPRESSION_THRESHOLD:
        compress_history(conv_id)

    return msg


def update_structured_state(
    conv_id: str,
    current_report: dict[str, Any] | None = ...,
    last_query: dict[str, Any] | None = ...,
    last_chart: dict[str, Any] | None = ...,
    last_table: dict[str, Any] | None = ...,
    last_generated_filename: str | None = ...,
    last_report_prefill: dict[str, Any] | None = ...,
    uploaded_file: str | None = ...,
    selected_template: str | None = ...,
    last_dataset: list[dict[str, Any]] | None = ...,
    last_sql: str | None = ...,
    last_title: str | None = ...,
    last_columns: list[str] | None = ...,
    last_filters: dict[str, Any] | None = ...,
    pending_clarification: dict[str, Any] | None = ...,
    resolved_entities: dict[str, Any] | None = ...,
) -> StructuredState:
    """
    Update specific fields of the structured state. Only fields that are
    explicitly passed (not the sentinel ``...``) are updated.

    Returns the updated StructuredState.
    """
    conv = _get_or_create(conv_id)
    state = conv.structured_state

    sentinel = ...
    if current_report is not sentinel:
        state.current_report = current_report
    if last_query is not sentinel:
        state.last_query = last_query
    if last_chart is not sentinel:
        state.last_chart = last_chart
    if last_table is not sentinel:
        state.last_table = last_table
    if last_generated_filename is not sentinel:
        state.last_generated_filename = last_generated_filename
    if last_report_prefill is not sentinel:
        state.last_report_prefill = last_report_prefill
    if uploaded_file is not sentinel:
        state.uploaded_file = uploaded_file
    if selected_template is not sentinel:
        state.selected_template = selected_template
    if last_dataset is not sentinel:
        state.last_dataset = last_dataset
    if last_sql is not sentinel:
        state.last_sql = last_sql
    if last_title is not sentinel:
        state.last_title = last_title
    if last_columns is not sentinel:
        state.last_columns = last_columns
    if last_filters is not sentinel:
        state.last_filters = last_filters
    if pending_clarification is not sentinel:
        state.pending_clarification = pending_clarification
    if resolved_entities is not sentinel:
        state.resolved_entities = resolved_entities

    return state


def get_structured_state(conv_id: str) -> StructuredState:
    """Retrieve the StructuredState for a conversation."""
    return _get_or_create(conv_id).structured_state


def get_pending_clarification(conv_id: str) -> dict[str, Any] | None:
    """Retrieve any active clarification request for this conversation."""
    return _get_or_create(conv_id).structured_state.pending_clarification


def set_pending_clarification(conv_id: str, clarification: dict[str, Any] | None) -> None:
    """Set or update the active clarification request for this conversation."""
    _get_or_create(conv_id).structured_state.pending_clarification = clarification


def clear_pending_clarification(conv_id: str) -> None:
    """Clear any active clarification request for this conversation."""
    _get_or_create(conv_id).structured_state.pending_clarification = None


def get_latest_dataset(conv_id: str) -> tuple[list[dict] | None, list[str] | None, str, dict]:
    """
    Retrieve the latest conversational dataset from memory using priority:
    1. structured_state.last_dataset
    2. structured_state.last_table (reconstructed as dict rows)
    3. Traversal backwards through message metadata for tables or rows.

    Returns (rows, columns, title, filters). If no data, returns (None, None, "", {}).
    """
    conv = _get_or_create(conv_id)
    state = conv.structured_state

    # 1. Direct dataset in state
    if state.last_dataset:
        cols = state.last_columns or (list(state.last_dataset[0].keys()) if state.last_dataset else [])
        title = state.last_title or "Conversational Sales Report"
        filters = state.last_filters or {}
        return state.last_dataset, cols, title, filters

    # 2. Table in state
    if state.last_table and state.last_table.get("columns") and state.last_table.get("rows"):
        cols = state.last_table["columns"]
        raw_rows = state.last_table["rows"]
        rows = [dict(zip(cols, r)) for r in raw_rows]
        title = state.last_title or "Conversational Query Results"
        filters = state.last_filters or {}
        return rows, cols, title, filters

    # 3. Walk backwards through conversation messages
    for msg in reversed(conv.messages):
        if msg.role == "assistant" and msg.metadata:
            meta = msg.metadata
            if meta.get("rows") and isinstance(meta["rows"], list):
                r = meta["rows"]
                c = meta.get("columns") or (list(r[0].keys()) if r else [])
                t = meta.get("title") or "Conversational Data Report"
                return r, c, t, meta.get("filters", {})
            if meta.get("table") and isinstance(meta["table"], dict):
                t_dict = meta["table"]
                cols = t_dict.get("columns", [])
                raw_rows = t_dict.get("rows", [])
                if cols and raw_rows:
                    rows = [dict(zip(cols, row)) for row in raw_rows]
                    return rows, cols, "Conversational Table Report", meta.get("filters", {})

    # 4. Text metric reconstruction (e.g. Total Sales = ₹5.6 Cr, Top Performer = ABC Ltd, Growth = 14%)
    for msg in reversed(conv.messages):
        if msg.role == "assistant" and msg.content:
            text = msg.content
            # Skip refusal/error responses
            if any(k in text.lower() for k in ["there is no structured data", "couldn't understand", "failed to fetch", "error"]):
                continue
            kv_rows = []
            for line in text.split("\n"):
                clean_l = line.strip().lstrip("-*• ")
                if not clean_l:
                    continue
                # Match "Key = Value" or "Key: Value"
                m = re.match(r"^([\w\s\(\)/%-]+?)\s*(?:=|\b:\b)\s*([₹\$\w\s.,%/-]+)$", clean_l)
                if m:
                    k = m.group(1).strip().strip("*").strip()
                    v = m.group(2).strip().strip("*").strip()
                    if k and v and len(k) < 60 and len(v) < 100:
                        kv_rows.append({"Metric": k, "Value": v})
            if len(kv_rows) >= 2:
                return kv_rows, ["Metric", "Value"], "Metric Summary Report", {}

    return None, None, "", {}


def store_conversation_report(
    conv_id: str,
    report_id: str,
    file_bytes: bytes,
    filename: str,
) -> None:
    """Store generated Excel file bytes for on-demand download."""
    conv = _get_or_create(conv_id)
    conv.cached_reports[report_id] = {
        "bytes": file_bytes,
        "filename": filename,
        "created_at": datetime.now().isoformat(),
    }


def get_conversation_report(
    conv_id: str,
    report_id: str,
) -> tuple[bytes, str] | None:
    """Retrieve cached Excel report bytes and filename."""
    conv = _get_or_create(conv_id)
    rep = conv.cached_reports.get(report_id)
    if rep:
        return rep["bytes"], rep["filename"]
    return None


def get_context_window(
    conv_id: str,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> list[dict[str, str]]:
    """
    Build a rolling context window for the LLM, containing:
      1. Conversation summary (if any compressed history exists)
      2. Recent messages that fit within the token budget

    Returns a list of ``{role, content}`` dicts ready for the LLM messages array.
    """
    conv = _get_or_create(conv_id)

    result: list[dict[str, str]] = []
    used_tokens = 0

    # 1. Include summary if available
    if conv.summary:
        summary_tokens = estimate_tokens(conv.summary)
        if summary_tokens < max_tokens:
            result.append({
                "role": "system",
                "content": f"CONVERSATION SUMMARY (earlier exchanges):\n{conv.summary}",
            })
            used_tokens += summary_tokens

    # 2. Walk backwards through messages, collecting as many as fit
    messages_to_include: list[ConversationMessage] = []
    remaining_budget = max_tokens - used_tokens

    for msg in reversed(conv.messages):
        if msg.token_count > remaining_budget:
            break
        messages_to_include.insert(0, msg)
        remaining_budget -= msg.token_count

    # 3. Convert to LLM message format
    for msg in messages_to_include:
        content = msg.content
        # Enrich assistant messages with metadata summary for context
        if msg.role == "assistant" and msg.metadata:
            meta_parts = []
            if msg.metadata.get("sql"):
                meta_parts.append(f"[SQL executed: {msg.metadata['sql'][:200]}]")
            if msg.metadata.get("table"):
                t = msg.metadata["table"]
                cols = t.get("columns", [])
                row_count = len(t.get("rows", []))
                meta_parts.append(f"[Returned table: {', '.join(cols[:6])} — {row_count} rows]")
            if msg.metadata.get("chart"):
                chart = msg.metadata["chart"]
                meta_parts.append(f"[Generated {chart.get('type', '')} chart]")
            if msg.metadata.get("report_prefill"):
                rp = msg.metadata["report_prefill"]
                meta_parts.append(f"[Report prefill: {rp}]")
            if meta_parts:
                content = content + "\n" + " ".join(meta_parts)

        result.append({"role": msg.role, "content": content})

    return result


def build_state_prompt(conv_id: str) -> str:
    """
    Render the structured state as a concise prompt block for injection
    into the system message, so the LLM can resolve coreferences.

    Returns an empty string if no state has been recorded.
    """
    conv = _get_or_create(conv_id)
    state = conv.structured_state

    if state.is_empty():
        return ""

    lines = ["## CURRENT WORKING CONTEXT (structured state)"]
    lines.append("Use this to resolve references like 'it', 'same', 'previous', etc.\n")

    if state.current_report:
        lines.append(f"- **Current report**: {state.current_report}")
    if state.last_query:
        lines.append(f"- **Last database query**: {state.last_query}")
    if state.last_chart:
        lines.append(f"- **Last chart generated**: {state.last_chart}")
    if state.last_table:
        lines.append(f"- **Last table shown**: columns={state.last_table.get('columns')}, rows={state.last_table.get('row_count')}")
    if state.last_generated_filename:
        lines.append(f"- **Last generated file**: {state.last_generated_filename}")
    if state.last_report_prefill:
        lines.append(f"- **Last report parameters**: {state.last_report_prefill}")
    if state.uploaded_file:
        lines.append(f"- **Uploaded file**: {state.uploaded_file}")
    if state.selected_template:
        lines.append(f"- **Selected template**: {state.selected_template}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Context compression
# ═══════════════════════════════════════════════════════════════════════

def compress_history(conv_id: str, target_tokens: int | None = None) -> None:
    """
    Compress the oldest messages into a bullet-point summary, preserving
    the most recent exchanges in full detail.

    Algorithm:
      1. Identify messages to compress (everything except the last MIN_RECENT_MESSAGES).
      2. Build a concise summary from the compressed messages.
      3. Replace the compressed messages with nothing (they're captured in the summary).
      4. Prepend the new summary to any existing summary.
    """
    conv = _get_or_create(conv_id)
    target = target_tokens or (MAX_CONTEXT_TOKENS // 2)

    if len(conv.messages) <= MIN_RECENT_MESSAGES:
        return  # nothing to compress

    # Split: messages to compress vs messages to keep
    compress_count = len(conv.messages) - MIN_RECENT_MESSAGES
    if compress_count <= 0:
        return

    to_compress = conv.messages[:compress_count]
    to_keep = conv.messages[compress_count:]

    # Build summary from messages being compressed
    summary_lines = []
    for msg in to_compress:
        prefix = "User" if msg.role == "user" else "Assistant"
        # Truncate long content for the summary
        text = msg.content[:150].replace("\n", " ").strip()
        if len(msg.content) > 150:
            text += "..."

        summary_lines.append(f"- {prefix}: {text}")

        # Include key metadata in summary
        if msg.metadata:
            if msg.metadata.get("sql"):
                sql_short = msg.metadata["sql"][:100].replace("\n", " ")
                summary_lines.append(f"  [Executed SQL: {sql_short}]")
            if msg.metadata.get("chart"):
                summary_lines.append(f"  [Generated {msg.metadata['chart'].get('type', '')} chart]")
            if msg.metadata.get("report_prefill"):
                summary_lines.append(f"  [Report parameters: {msg.metadata['report_prefill']}]")

    new_summary_block = "\n".join(summary_lines)

    # Merge with existing summary
    if conv.summary:
        conv.summary = conv.summary + "\n" + new_summary_block
    else:
        conv.summary = new_summary_block

    # Trim the summary itself if it grows too large
    summary_tokens = estimate_tokens(conv.summary)
    if summary_tokens > target:
        # Keep only the most recent portion of the summary
        lines = conv.summary.split("\n")
        while estimate_tokens("\n".join(lines)) > target and len(lines) > 5:
            lines.pop(0)
        conv.summary = "...(earlier context omitted)...\n" + "\n".join(lines)

    # Replace message list with only the recent messages
    conv.messages = to_keep

    # Recalculate total tokens
    conv.total_tokens = (
        estimate_tokens(conv.summary)
        + sum(m.token_count for m in conv.messages)
    )


# ═══════════════════════════════════════════════════════════════════════
# Conversation lifecycle
# ═══════════════════════════════════════════════════════════════════════

def delete_conversation(conv_id: str) -> bool:
    """
    Delete a conversation and all its history.
    Returns True if the conversation existed, False otherwise.
    """
    if conv_id in _store:
        del _store[conv_id]
        return True
    return False


def get_conversation(conv_id: str) -> Conversation | None:
    """Return the conversation object, or None if it doesn't exist."""
    return _store.get(conv_id)


def get_message_count(conv_id: str) -> int:
    """Return the number of messages in a conversation."""
    conv = _store.get(conv_id)
    return len(conv.messages) if conv else 0


def list_conversations() -> list[str]:
    """Return all active conversation IDs."""
    return list(_store.keys())
