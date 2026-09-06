"""
Horeca Sales Intelligence — Database connection pool (READ-ONLY).

This module provides ONLY read-only database access. There is no write
path. The connection pool uses a read-only PostgreSQL user when configured,
and additionally sets each connection to read-only mode as a defense-in-depth
measure.

Security layers:
  1. Application-level: SQL validation via security.sql_validator before execution.
  2. Connection-level: SET default_transaction_read_only = true on each checkout.
  3. Database-level: The DB_READONLY_USER role has only SELECT privileges.
"""
import os
import logging

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from .security.sql_validator import validate_sql

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

logger = logging.getLogger("db")

_pool: pool.SimpleConnectionPool | None = None


# ═══════════════════════════════════════════════════════════════════════
# Custom exception
# ═══════════════════════════════════════════════════════════════════════

class ReadOnlyViolationError(Exception):
    """Raised when a non-read-only SQL statement is attempted."""
    pass


# ═══════════════════════════════════════════════════════════════════════
# Connection pool (read-only)
# ═══════════════════════════════════════════════════════════════════════

def get_pool() -> pool.SimpleConnectionPool:
    """
    Return the connection pool, creating it on first call.

    Uses DB_READONLY_USER / DB_READONLY_PASSWORD if set (preferred),
    otherwise falls back to DB_USER / DB_PASSWORD for backward compat.
    """
    global _pool
    if _pool is None:
        # Prefer read-only credentials; fall back to standard credentials
        db_user = os.getenv("DB_READONLY_USER") or os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DB_READONLY_PASSWORD") or os.getenv("DB_PASSWORD", "")

        _pool = pool.SimpleConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=db_user,
            password=db_password,
            database=os.getenv("DB_NAME", "horeca_sales_db"),
            options="-c default_transaction_read_only=on",
        )
        logger.info("Database pool created (user=%s, read-only enforced)", db_user)
    return _pool


# ═══════════════════════════════════════════════════════════════════════
# Read-only query execution
# ═══════════════════════════════════════════════════════════════════════

def query(sql: str, params: tuple | list | None = None) -> list[dict]:
    """
    Execute a read-only query and return rows as list of dicts.

    Security: The SQL statement is validated by the SQL validator before
    execution. If validation fails, a ReadOnlyViolationError is raised
    and no SQL reaches the database.

    Parameters
    ----------
    sql : str
        The SQL query to execute. Must be a SELECT or WITH...SELECT.
    params : tuple | list | None
        Optional query parameters for parameterised queries.

    Returns
    -------
    list[dict]
        Query result rows as dictionaries.

    Raises
    ------
    ReadOnlyViolationError
        If the SQL statement fails read-only validation.
    """
    # ── SQL validation gate ──
    result = validate_sql(sql)
    if not result.is_valid:
        logger.warning(
            "SQL REJECTED by validator: reason=%s sql=%.200s",
            result.reason,
            sql,
        )
        raise ReadOnlyViolationError(
            f"Query rejected by security validator: {result.reason}"
        )

    # ── Execute validated query ──
    p = get_pool()
    conn = p.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        p.putconn(conn)
