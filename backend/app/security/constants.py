"""
Horeca Sales Intelligence — Security Constants.

Central configuration for prompt governance and SQL validation.
All patterns, keyword lists, and thresholds live here for easy auditing.
"""

import re

# ═══════════════════════════════════════════════════════════════════════
# SQL KEYWORD CONTROLS
# ═══════════════════════════════════════════════════════════════════════

FORBIDDEN_SQL_KEYWORDS: set[str] = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "MERGE", "REPLACE", "GRANT", "REVOKE",
    "EXECUTE", "EXEC", "CALL", "COPY",
}

ALLOWED_SQL_STARTERS: set[str] = {"SELECT", "WITH"}

# PostgreSQL functions that can modify state or leak information
DANGEROUS_PG_FUNCTIONS: set[str] = {
    "pg_sleep", "dblink", "dblink_exec", "dblink_connect",
    "lo_import", "lo_export", "lo_unlink",
    "pg_read_file", "pg_read_binary_file", "pg_write_file",
    "pg_ls_dir", "pg_stat_file",
    "query_to_xml", "query_to_json",
    "pg_terminate_backend", "pg_cancel_backend",
    "pg_reload_conf", "pg_rotate_logfile",
    "set_config", "current_setting",
    "pg_advisory_lock", "pg_advisory_unlock",
    "txid_current",
}

# ═══════════════════════════════════════════════════════════════════════
# PROMPT INJECTION PATTERNS
# Organised by detection category. Each entry:
#   (compiled_regex, category, severity_score, human_reason)
# ═══════════════════════════════════════════════════════════════════════

def _compile(patterns: list[tuple[str, str, float, str]]):
    """Pre-compile regex patterns for performance."""
    return [
        (re.compile(p, re.IGNORECASE | re.DOTALL), cat, score, reason)
        for p, cat, score, reason in patterns
    ]


INJECTION_PATTERNS = _compile([
    # ── Prompt Injection / Override ──
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|guidelines?|directives?|context)",
     "prompt_injection", 0.95, "Attempt to override system instructions"),
    (r"forget\s+(all\s+)?(your|the|previous|prior)\s+(rules?|instructions?|prompts?|guidelines?|context|training)",
     "prompt_injection", 0.95, "Attempt to erase system instructions"),
    (r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|your)\s+(instructions?|prompts?|rules?|guidelines?)",
     "prompt_injection", 0.95, "Attempt to disregard system instructions"),
    (r"do\s+not\s+follow\s+(your|the|any)\s+(rules?|instructions?|guidelines?|restrictions?)",
     "prompt_injection", 0.90, "Attempt to disable rule adherence"),
    (r"override\s+(your|the|all|any|system)\s+(system\s+)?(rules?|instructions?|prompts?|guidelines?|restrictions?|safety)",
     "prompt_injection", 0.95, "Attempt to override system rules"),
    (r"new\s+(instructions?|rules?|directives?|guidelines?)\s*[:=]",
     "prompt_injection", 0.85, "Attempt to inject new instructions"),
    (r"(from\s+now\s+on|henceforth|going\s+forward)\s*(,?\s*you\s+(will|shall|must|should|are\s+going\s+to))",
     "prompt_injection", 0.85, "Attempt to redefine behaviour"),
    (r"(stop|cease|quit)\s+(being|acting\s+as|pretending\s+to\s+be)\s+(a|an|the)?\s*(assistant|bot|ai|chatbot)",
     "prompt_injection", 0.85, "Attempt to alter AI identity"),
    (r"(begin|start|enter|switch\s+to|activate)\s+(a\s+)?(new\s+)?(unrestricted|uncensored|admin|developer|debug|god|sudo)\s+(mode|persona|role|session|context)",
     "prompt_injection", 0.90, "Attempt to enter privileged mode"),
    (r"pretend\s+(that\s+)?(you\s+)?(are|have|can|don.?t\s+have)\s+(a\s+)?(no\s+)?(different|unrestricted|uncensored)\s*(ai|assistant|bot|system|rules?|restrictions?|limitations?|filters?|boundaries|constraints?)?",
     "prompt_injection", 0.90, "Attempt to assume unrestricted identity via pretending"),
    (r"pretend\s+(that\s+)?(you\s+)?(are|have|can|don.?t\s+have)\s+(no\s+)(restrictions?|rules?|limitations?|filters?|boundaries|constraints?)",
     "prompt_injection", 0.90, "Attempt to remove restrictions via pretending"),
    (r"pretend\s+(that\s+)?(you\s+)?can\s+do\s+(anything|everything)",
     "prompt_injection", 0.90, "Attempt to claim unlimited capability"),

    # ── Role Escalation ──
    (r"you\s+are\s+(now|henceforth)?\s*(a|an|the)?\s*(system\s*admin|administrator|root\s*user|superuser|dba|database\s+admin|sudo|privileged)",
     "role_escalation", 0.95, "Attempt to claim admin role"),
    (r"(i\s+am|i.?m)\s+(a|an|the)?\s*(system\s*admin|administrator|root\s*user|superuser|dba|database\s+admin|owner|developer|engineer)",
     "role_escalation", 0.85, "User claiming elevated role"),
    (r"(i\s+am|i.?m)\s+(the\s+)?(system\s+)?owner.{0,20}(override|security|access|permission)",
     "role_escalation", 0.90, "User claiming ownership to override security"),
    (r"(grant|give|assign|elevate)\s+(me|my|this\s+user)?\s*(admin|root|superuser|write|full|elevated|privileged)\s*(access|permissions?|privileges?|rights?|role)",
     "role_escalation", 0.95, "Attempt to escalate permissions"),
    (r"(act\s+as|behave\s+as|function\s+as|operate\s+as|respond\s+as)\s+(a|an|the)?\s*(admin|root|developer|engineer|system|unrestricted|uncensored)",
     "role_escalation", 0.90, "Attempt to assume elevated role"),
    (r"(enable|activate|turn\s+on|unlock)\s+(admin|developer|debug|maintenance|god|sudo|privileged)\s*(mode|access|panel|console)",
     "role_escalation", 0.90, "Attempt to enable privileged mode"),

    # ── System Prompt / Secret Extraction ──
    (r"(show|display|reveal|tell|give|print|output|repeat|recite|echo|dump)\s+(me\s+)?(your|the)?\s*(system\s*prompt|hidden\s*(prompt|instructions?)|initial\s*(prompt|instructions?)|internal\s*(prompt|instructions?)|original\s*(prompt|instructions?)|base\s*prompt|meta\s*prompt|pre\s*prompt)",
     "secret_extraction", 0.95, "Attempt to reveal system prompt"),
    (r"what\s+(are|is)\s+(your|the)\s*(system\s*)?(prompt|instructions?|rules?|guidelines?|directives?|configuration|setup)",
     "secret_extraction", 0.85, "Attempt to learn system instructions"),
    (r"(show|display|reveal|tell|give|print|output|leak|expose|dump)\s+(me\s+)?(your|the|all|any)?\s*(api\s*key|secret\s*key|password|credential|token|connection\s*string|env(ironment)?\s*var(iable)?|config(uration)?)",
     "secret_extraction", 0.95, "Attempt to extract secrets"),
    (r"what\s+(is|are)\s+(your|the)\s*(\w+\s+)?(api\s*key|password|secret|credential|token)",
     "secret_extraction", 0.95, "Attempt to learn secret values"),
    (r"(what|where)\s+(is|are)\s+(your|the)\s*(database|db|postgres|sql)\s*(password|credential|connection|host|port|user)",
     "secret_extraction", 0.95, "Attempt to extract database credentials"),
    (r"(show|tell|reveal|give|display)\s+(me\s+)?(your|the)?\s*(\w+\s+)?(password|credential|connection\s*string)",
     "secret_extraction", 0.95, "Attempt to reveal passwords/credentials"),
    (r"(show|tell|reveal|give)\s+(me\s+)?(your|the)?\s*(backend|server|internal|architecture|implementation|source\s*code|codebase)",
     "secret_extraction", 0.80, "Attempt to reveal architecture details"),
    (r"(print|echo|output|return|show)\s+(the\s+)?(value\s+of\s+)?os\.?(environ|getenv|env)|process\.env",
     "secret_extraction", 0.95, "Attempt to access environment variables"),
    (r"(what\s+)?(tools?|functions?|capabilities?|plugins?)\s+(do\s+you|are\s+you|you)\s+(have|use|access|connected)",
     "secret_extraction", 0.70, "Attempt to enumerate internal tools"),

    # ── Data Modification (Natural Language) ──
    (r"(delete|remove|erase|destroy|wipe|purge|clear)\s+(all\s+)?(the\s+)?(duplicate|old|invalid|incorrect|wrong|bad|test)?\s*(rows?|records?|entries?|data|customers?|sales?|transactions?|everything)",
     "data_modification", 0.90, "Attempt to delete database records"),
    (r"(?<!list\s)(?<!show\s)(?<!get\s)(?<!find\s)(?<!display\s)(update|change|modify|alter|edit|correct|overwrite|replace|set|assign|rewrite)\s+(the\s+)?(customer|sales?|record|data|entry|row|value|name|field|column|database|table|price|rate|quantity)\b",
     "data_modification", 0.90, "Attempt to modify database records"),
    (r"(insert|add|create|write|put|store|save)\s+(a\s+)?(new\s+)?(customer|record|entry|row|data|sale|transaction|order|value)\s+(in|into|to)\s+(the\s+)?(database|table|system|db)",
     "data_modification", 0.90, "Attempt to insert new records"),
    (r"add\s+(a\s+)?new\s+(row|record|entry|customer|data)\s+to\s+(the\s+)?(\w+\s+)?(table|database)",
     "data_modification", 0.90, "Attempt to add new data"),
    (r"(drop|truncate|destroy|nuke|reset|rebuild|recreate)\s+(the\s+)?(\w+\s+)?(table|database|schema|index|view|all\s+tables)",
     "data_modification", 0.95, "Attempt to drop/truncate database objects"),
    (r"(modify|edit|change|update|rewrite|overwrite|alter)\s+(the\s+)?(excel|xlsx|spreadsheet|csv|source)\s*(file|data|document|report)?",
     "data_modification", 0.90, "Attempt to modify Excel/source files"),
    (r"(clean\s*up|repair|normalize|sanitize|deduplicate)\s+(the\s+)?(database|data|records?|table|entries?)",
     "data_modification", 0.75, "Potential data modification via cleanup request"),
    (r"fix\s+(the\s+)?(data|database|records?|table|entries?)\s+(in|of|for|on)\s+(the\s+)?\w+",
     "data_modification", 0.80, "Attempt to fix/modify data"),
    (r"rewrite\s+(the\s+)?(database|data|records?|table|system|backend)",
     "data_modification", 0.90, "Attempt to rewrite data"),
    (r"(merge|combine|consolidate)\s+(and\s+)?(delete|remove|replace)",
     "data_modification", 0.85, "Attempt to merge-and-delete records"),

    # ── Direct SQL Execution ──
    (r"(run|execute|perform|fire|do|send)\s+(this\s+)?(sql|query|statement|command)\s*[:=]?\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE)",
     "sql_injection", 0.95, "Attempt to execute modifying SQL"),
    (r"(run|execute|perform)\s+(this\s+)?(sql|query|statement|command)\s+(exactly|as\s*is|literally|verbatim|without\s+changes?)",
     "sql_injection", 0.90, "Attempt to execute arbitrary SQL"),
    (r"(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)|ALTER\s+TABLE|CREATE\s+TABLE|TRUNCATE\s+TABLE|GRANT\s+\w+|REVOKE\s+\w+)",
     "sql_injection", 0.95, "Raw modifying SQL detected in prompt"),

    # ── Security Control Bypass ──
    (r"(disable|turn\s+off|deactivate|remove|bypass|skip|ignore|circumvent)\s+(the\s+)?(security|safety|filter|validation|check|guard|protection|restriction|firewall|governance|screening)",
     "security_bypass", 0.95, "Attempt to disable security controls"),
    (r"(there\s+are\s+no|don.?t\s+worry\s+about|skip\s+the|no\s+need\s+for)\s*(security|safety|validation|rules?|restrictions?|checks?|filters?)",
     "security_bypass", 0.90, "Attempt to dismiss security concerns"),
])


# ═══════════════════════════════════════════════════════════════════════
# NORMALISATION MAPS (for de-obfuscation)
# ═══════════════════════════════════════════════════════════════════════

LEETSPEAK_MAP: dict[str, str] = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "9": "g", "@": "a", "$": "s",
    "!": "i", "|": "l", "+": "t",
}

# ═══════════════════════════════════════════════════════════════════════
# THREAT SCORING
# ═══════════════════════════════════════════════════════════════════════

# If the total accumulated threat score meets or exceeds this threshold,
# the prompt is blocked.
THREAT_SCORE_THRESHOLD: float = 0.70

# ═══════════════════════════════════════════════════════════════════════
# SAFE REFUSAL MESSAGE
# ═══════════════════════════════════════════════════════════════════════

SAFE_REFUSAL_MESSAGE: str = (
    "I'm a **read-only analytics assistant** for sales data. "
    "I can help you retrieve, analyse, summarise, compare, and visualise data, "
    "but I cannot modify any database records, files, or system settings.\n\n"
    "How can I help you with sales analytics today?"
)

PROMPT_REVEAL_REFUSAL: str = (
    "I'm not able to share details about my internal configuration, "
    "system prompts, or architecture. "
    "I'm here to help you with sales analytics — what would you like to know?"
)
