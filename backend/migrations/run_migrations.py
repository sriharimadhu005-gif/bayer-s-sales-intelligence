"""
Database Migration Runner for Horeca Sales Intelligence.

Discovers and applies pending SQL migrations in the backend/migrations directory.
Tracks executed migrations in the `schema_migrations` table for idempotency.
"""

import os
import glob
import logging
import psycopg2
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrations")

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(env_path)


def get_write_connection():
    """Create a direct write-capable connection using postgres superuser."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "horeca_sales_db"),
    )


def run_migrations():
    """Apply all unapplied SQL migrations in numerical order."""
    migrations_dir = os.path.dirname(__file__)
    migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

    if not migration_files:
        logger.info("No SQL migration files found in %s", migrations_dir)
        return

    conn = get_write_connection()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Ensure schema_migrations tracker table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            conn.commit()

            cur.execute("SELECT version FROM schema_migrations;")
            applied = {row[0] for row in cur.fetchall()}

            for filepath in migration_files:
                filename = os.path.basename(filepath)
                if filename in applied:
                    logger.info("Migration already applied: %s", filename)
                    continue

                logger.info("Applying migration: %s ...", filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    sql_content = f.read()

                cur.execute(sql_content)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s);",
                    (filename,)
                )
                conn.commit()
                logger.info("Successfully applied migration: %s", filename)

    except Exception as e:
        conn.rollback()
        logger.error("Migration failed: %s", e)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
