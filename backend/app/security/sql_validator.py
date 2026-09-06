"""
Horeca Sales Intelligence — SQL Validation Module.

Post-LLM security gate that validates every generated SQL statement
before it reaches the database. Uses AST-based parsing via sqlglot
with regex fallbacks for robustness.

Only pure read-only SELECT / WITH…SELECT statements are permitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .constants import FORBIDDEN_SQL_KEYWORDS, ALLOWED_SQL_STARTERS, DANGEROUS_PG_FUNCTIONS

__all__ = ["validate_sql", "ValidationResult"]

# ═══════════════════════════════════════════════════════════════════════
# Attempt to import sqlglot (AST parser). If not installed, fall back
# to regex-only validation. Regex-only is still strict — it just lacks
# the structural understanding of an AST parser.
# ═══════════════════════════════════════════════════════════════════════

try:
    import sqlglot
    from sqlglot import expressions as exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False


# ═══════════════════════════════════════════════════════════════════════
# Result type
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    """Outcome of SQL validation."""
    is_valid: bool
    reason: str | None = None
    statement_type: str | None = None     # "SELECT", "WITH", etc.
    tables_accessed: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # truthy = valid
        return self.is_valid


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

_COMMENT_PATTERNS = [
    re.compile(r"--[^\n]*", re.MULTILINE),          # single-line comments
    re.compile(r"/\*.*?\*/", re.DOTALL),             # block comments
]


def _strip_comments(sql: str) -> str:
    """Remove SQL comments that could be used to hide malicious code."""
    result = sql
    for pattern in _COMMENT_PATTERNS:
        result = pattern.sub(" ", result)
    return result


def _check_multi_statement(sql: str) -> str | None:
    """
    Reject multi-statement SQL. Returns a reason string if invalid, else None.
    Handles semicolons inside string literals by tracking quote state.
    """
    in_single_quote = False
    in_double_quote = False
    in_dollar_quote = False
    dollar_tag = ""
    i = 0
    statement_count = 0

    while i < len(sql):
        ch = sql[i]

        # Dollar-quoted strings (PostgreSQL-specific)
        if ch == "$" and not in_single_quote and not in_double_quote:
            end = sql.find("$", i + 1)
            if end != -1:
                tag = sql[i:end + 1]
                if in_dollar_quote and tag == dollar_tag:
                    in_dollar_quote = False
                    dollar_tag = ""
                    i = end + 1
                    continue
                elif not in_dollar_quote:
                    in_dollar_quote = True
                    dollar_tag = tag
                    i = end + 1
                    continue

        if in_dollar_quote:
            i += 1
            continue

        if ch == "'" and not in_double_quote:
            # Handle escaped quotes
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif ch == ";" and not in_single_quote and not in_double_quote:
            # Check if there is non-whitespace content after this semicolon
            remaining = sql[i + 1:].strip()
            if remaining:
                return "Multi-statement SQL is not allowed"

        i += 1

    return None


def _check_forbidden_keywords_regex(sql: str) -> str | None:
    """
    Check for forbidden SQL keywords using word-boundary regex.
    Returns a reason string if invalid, else None.
    """
    upper = sql.upper()
    for keyword in FORBIDDEN_SQL_KEYWORDS:
        # Word-boundary match to avoid false positives
        # (e.g. "customer_update" shouldn't match "UPDATE")
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, upper):
            return f"Forbidden SQL keyword detected: {keyword}"
    return None


def _check_dangerous_functions(sql: str) -> str | None:
    """Check for dangerous PostgreSQL functions."""
    lower = sql.lower()
    for func in DANGEROUS_PG_FUNCTIONS:
        # Match function calls: func_name(
        pattern = rf"\b{re.escape(func)}\s*\("
        if re.search(pattern, lower):
            return f"Dangerous function detected: {func}"
    return None


def _check_dynamic_sql(sql: str) -> str | None:
    """Detect dynamic SQL execution patterns."""
    patterns = [
        (r"\bEXECUTE\b", "EXECUTE statement detected"),
        (r"\bEXEC\b", "EXEC statement detected"),
        (r"\bPREPARE\b", "PREPARE statement detected"),
        (r"\bDEALLOCATE\b", "DEALLOCATE statement detected"),
        (r"\bDO\s*\$", "DO block (PL/pgSQL) detected"),
        (r"\bCALL\b", "CALL statement detected"),
    ]
    upper = sql.upper()
    for pattern, reason in patterns:
        if re.search(pattern, upper):
            return reason
    return None


def _check_allowed_starter(sql: str) -> str | None:
    """Verify the SQL starts with an allowed keyword."""
    stripped = sql.strip().upper()
    for starter in ALLOWED_SQL_STARTERS:
        if stripped.startswith(starter):
            return None
    return f"SQL must start with SELECT or WITH, got: {stripped[:30]}..."


def _extract_tables_regex(sql: str) -> list[str]:
    """Extract table/view names from SQL using regex (best-effort)."""
    tables = set()
    # FROM / JOIN clauses
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
        sql,
        re.IGNORECASE,
    ):
        tables.add(match.group(1).lower())
    return sorted(tables)


# ═══════════════════════════════════════════════════════════════════════
# AST-based validation (when sqlglot is available)
# ═══════════════════════════════════════════════════════════════════════

def _validate_with_ast(sql: str) -> ValidationResult:
    """
    Parse SQL into an AST and validate structurally.
    Falls back to regex validation if parsing fails.
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
    except Exception:
        # If sqlglot can't parse it, fall through to regex validation
        return _validate_regex_only(sql)

    if not parsed:
        return ValidationResult(
            is_valid=False,
            reason="Failed to parse SQL statement",
        )

    # Reject multiple statements
    if len(parsed) > 1:
        return ValidationResult(
            is_valid=False,
            reason="Multi-statement SQL is not allowed",
        )

    statement = parsed[0]

    if statement is None:
        return ValidationResult(
            is_valid=False,
            reason="Empty SQL statement",
        )

    # Check statement type via AST node type
    allowed_types = (exp.Select, exp.Union, exp.Intersect, exp.Except)
    # WITH (CTE) wraps a Select, UNION/INTERSECT/EXCEPT wrap selects too
    if not isinstance(statement, allowed_types):
        stmt_type = type(statement).__name__
        return ValidationResult(
            is_valid=False,
            reason=f"Only SELECT statements are allowed, got: {stmt_type}",
            statement_type=stmt_type,
        )

    # Walk the AST for forbidden node types
    forbidden_ast_types = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop,
        exp.Create, exp.Alter, exp.Command,
    )
    for node in statement.walk():
        if isinstance(node, forbidden_ast_types):
            node_type = type(node).__name__
            return ValidationResult(
                is_valid=False,
                reason=f"Forbidden SQL operation found in AST: {node_type}",
                statement_type=node_type,
            )

    # Extract accessed tables from AST
    tables = []
    for table_node in statement.find_all(exp.Table):
        name = table_node.name
        if name:
            tables.append(name.lower())

    # Still run regex checks for dangerous functions and dynamic SQL
    # (AST might not catch all PostgreSQL-specific patterns)
    func_check = _check_dangerous_functions(sql)
    if func_check:
        return ValidationResult(is_valid=False, reason=func_check, tables_accessed=tables)

    dynamic_check = _check_dynamic_sql(sql)
    if dynamic_check:
        return ValidationResult(is_valid=False, reason=dynamic_check, tables_accessed=tables)

    return ValidationResult(
        is_valid=True,
        statement_type="SELECT",
        tables_accessed=tables,
    )


# ═══════════════════════════════════════════════════════════════════════
# Regex-only validation (fallback when sqlglot is unavailable)
# ═══════════════════════════════════════════════════════════════════════

def _validate_regex_only(sql: str) -> ValidationResult:
    """Validate SQL using regex patterns only (no AST)."""
    tables = _extract_tables_regex(sql)

    # Check starter
    starter_check = _check_allowed_starter(sql)
    if starter_check:
        return ValidationResult(is_valid=False, reason=starter_check, tables_accessed=tables)

    # Check forbidden keywords
    keyword_check = _check_forbidden_keywords_regex(sql)
    if keyword_check:
        return ValidationResult(is_valid=False, reason=keyword_check, tables_accessed=tables)

    # Check dangerous functions
    func_check = _check_dangerous_functions(sql)
    if func_check:
        return ValidationResult(is_valid=False, reason=func_check, tables_accessed=tables)

    # Check dynamic SQL
    dynamic_check = _check_dynamic_sql(sql)
    if dynamic_check:
        return ValidationResult(is_valid=False, reason=dynamic_check, tables_accessed=tables)

    # Determine statement type
    stripped = sql.strip().upper()
    stmt_type = "WITH" if stripped.startswith("WITH") else "SELECT"

    return ValidationResult(
        is_valid=True,
        statement_type=stmt_type,
        tables_accessed=tables,
    )


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def validate_sql(sql: str) -> ValidationResult:
    """
    Validate a SQL statement for read-only safety.

    Pipeline:
      1. Strip comments
      2. Check for multi-statement SQL
      3. AST-based validation (if sqlglot installed) or regex fallback
      4. Return structured result

    Parameters
    ----------
    sql : str
        The SQL statement to validate.

    Returns
    -------
    ValidationResult
        .is_valid=True  → SQL is safe to execute.
        .is_valid=False → SQL is rejected; .reason explains why.
    """
    if not sql or not sql.strip():
        return ValidationResult(is_valid=False, reason="Empty SQL statement")

    # Step 1: Strip comments to prevent hiding malicious code
    cleaned = _strip_comments(sql)

    # Step 2: Check for multiple statements
    multi_check = _check_multi_statement(cleaned)
    if multi_check:
        return ValidationResult(is_valid=False, reason=multi_check)

    # Step 3: Run appropriate validator
    if HAS_SQLGLOT:
        return _validate_with_ast(cleaned)
    else:
        return _validate_regex_only(cleaned)
