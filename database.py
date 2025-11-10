import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = "data/glupek.db"


@contextmanager
def get_db():
    """Context manager for database connections"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database tables"""
    with get_db() as conn:
        # Server configurations
        conn.execute("""
                     CREATE TABLE IF NOT EXISTS servers
                     (
                         server_id
                         TEXT
                         PRIMARY
                         KEY,
                         enabled_languages
                         TEXT
                         NOT
                         NULL,
                         custom_flags
                         TEXT
                         DEFAULT
                         '{}',
                         mode
                         TEXT
                         DEFAULT
                         'thread',
                         dictionary
                         TEXT
                         DEFAULT
                         '{}',
                         created_at
                         TIMESTAMP
                         DEFAULT
                         CURRENT_TIMESTAMP,
                         updated_at
                         TIMESTAMP
                         DEFAULT
                         CURRENT_TIMESTAMP
                     )
                     """)

        # Translation logs
        conn.execute("""
                     CREATE TABLE IF NOT EXISTS translations
                     (
                         id
                         INTEGER
                         PRIMARY
                         KEY
                         AUTOINCREMENT,
                         server_id
                         TEXT
                         NOT
                         NULL,
                         message_id
                         TEXT
                         NOT
                         NULL,
                         source_lang
                         TEXT,
                         target_lang
                         TEXT
                         NOT
                         NULL,
                         api_used
                         TEXT
                         NOT
                         NULL,
                         success
                         BOOLEAN
                         NOT
                         NULL,
                         timestamp
                         TIMESTAMP
                         DEFAULT
                         CURRENT_TIMESTAMP,
                         FOREIGN
                         KEY
                     (
                         server_id
                     ) REFERENCES servers
                     (
                         server_id
                     )
                         )
                     """)

        # API usage tracking
        conn.execute("""
                     CREATE TABLE IF NOT EXISTS api_usage
                     (
                         id
                         INTEGER
                         PRIMARY
                         KEY
                         AUTOINCREMENT,
                         api_name
                         TEXT
                         NOT
                         NULL,
                         chars_used
                         INTEGER
                         NOT
                         NULL,
                         date
                         DATE
                         DEFAULT (
                         date
                     (
                         'now'
                     )),
                         timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                         )
                     """)

        # Indexes for performance
        conn.execute("""
                     CREATE INDEX IF NOT EXISTS idx_translations_server
                         ON translations(server_id, timestamp DESC)
                     """)

        conn.execute("""
                     CREATE INDEX IF NOT EXISTS idx_translations_success
                         ON translations(server_id, success, timestamp DESC)
                     """)

        conn.execute("""
                     CREATE INDEX IF NOT EXISTS idx_api_usage_date
                         ON api_usage(api_name, date)
                     """)

        logger.info("Database initialized successfully")


def get_server_config(server_id: str, global_defaults: Dict) -> Dict:
    """
    Get server configuration from database.
    Creates default config if server doesn't exist.

    Args:
        server_id: Discord server ID
        global_defaults: Global config from config.json

    Returns:
        Dict with server configuration
    """
    with get_db() as conn:
        cursor = conn.execute(
                "SELECT * FROM servers WHERE server_id = ?",
                (server_id,)
        )
        row = cursor.fetchone()

        if row:
            return {
                "server_id": row["server_id"],
                "enabled_languages": json.loads(row["enabled_languages"]),
                "custom_flags": json.loads(row["custom_flags"]),
                "mode": row["mode"],
                "dictionary": json.loads(row["dictionary"])
            }
        else:
            # Create new server config with global defaults
            config = {
                "server_id": server_id,
                "enabled_languages": global_defaults["default_languages"].copy(),
                "custom_flags": {},
                "mode": global_defaults["default_mode"],
                "dictionary": {}
            }

            conn.execute("""
                         INSERT INTO servers (server_id, enabled_languages, custom_flags, mode, dictionary)
                         VALUES (?, ?, ?, ?, ?)
                         """, (
                             server_id,
                             json.dumps(config["enabled_languages"]),
                             json.dumps(config["custom_flags"]),
                             config["mode"],
                             json.dumps(config["dictionary"])
                         ))

            logger.info(f"Created default config for server {server_id}")
            return config


def update_server_languages(server_id: str, languages: List[str]):
    """Update enabled languages for a server"""
    with get_db() as conn:
        conn.execute(
                """UPDATE servers
                   SET enabled_languages = ?,
                       updated_at        = CURRENT_TIMESTAMP
                   WHERE server_id = ?""",
                (json.dumps(languages), server_id)
        )
        logger.info(f"Updated languages for server {server_id}")


def update_server_flags(server_id: str, flags: Dict[str, str]):
    """Update custom flags for a server"""
    with get_db() as conn:
        conn.execute(
                """UPDATE servers
                   SET custom_flags = ?,
                       updated_at   = CURRENT_TIMESTAMP
                   WHERE server_id = ?""",
                (json.dumps(flags), server_id)
        )
        logger.info(f"Updated custom flags for server {server_id}")


def update_server_mode(server_id: str, mode: str):
    """Update translation mode for a server"""
    with get_db() as conn:
        conn.execute(
                """UPDATE servers
                   SET mode       = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE server_id = ?""",
                (mode, server_id)
        )
        logger.info(f"Updated mode to {mode} for server {server_id}")


def update_server_dictionary(server_id: str, dictionary: Dict[str, str]):
    """Update custom dictionary for a server"""
    with get_db() as conn:
        conn.execute(
                """UPDATE servers
                   SET dictionary = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE server_id = ?""",
                (json.dumps(dictionary), server_id)
        )
        logger.info(f"Updated dictionary for server {server_id}")


def log_translation(server_id: str, message_id: str, source_lang: Optional[str],
                    target_lang: str, api_used: str, success: bool):
    """Log a translation attempt"""
    with get_db() as conn:
        conn.execute("""
                     INSERT INTO translations (server_id, message_id, source_lang, target_lang, api_used, success)
                     VALUES (?, ?, ?, ?, ?, ?)
                     """, (server_id, message_id, source_lang, target_lang, api_used, success))


def log_api_usage(api_name: str, chars_used: int):
    """Log API usage for quota tracking"""
    with get_db() as conn:
        conn.execute("""
                     INSERT INTO api_usage (api_name, chars_used)
                     VALUES (?, ?)
                     """, (api_name, chars_used))


def get_server_stats(server_id: str, days: int = 30) -> Dict:
    """Get translation statistics for a server"""
    with get_db() as conn:
        # Total translations
        total_result = conn.execute("""
                                    SELECT COUNT(*) as count
                                    FROM translations
                                    WHERE server_id = ?
                                      AND timestamp >= datetime('now'
                                        , '-' || ? || ' days')
                                    """, (server_id, days)).fetchone()
        total = total_result["count"] if total_result else 0

        # Successful translations
        success_result = conn.execute("""
                                      SELECT COUNT(*) as count
                                      FROM translations
                                      WHERE server_id = ?
                                        AND success = 1
                                        AND timestamp >= datetime('now'
                                          , '-' || ? || ' days')
                                      """, (server_id, days)).fetchone()
        success = success_result["count"] if success_result else 0

        # Most translated languages
        langs = conn.execute("""
                             SELECT target_lang, COUNT(*) as count
                             FROM translations
                             WHERE server_id = ?
                               AND timestamp >= datetime('now'
                                 , '-' || ? || ' days')
                             GROUP BY target_lang
                             ORDER BY count DESC
                                 LIMIT 5
                             """, (server_id, days)).fetchall()

        # API distribution (only successful)
        apis = conn.execute("""
                            SELECT api_used, COUNT(*) as count
                            FROM translations
                            WHERE server_id = ?
                              AND success = 1
                              AND timestamp >= datetime('now'
                                , '-' || ? || ' days')
                            GROUP BY api_used
                            ORDER BY count DESC
                            """, (server_id, days)).fetchall()

        return {
            "total": total,
            "success": success,
            "success_rate": (success / total * 100) if total > 0 else 0,
            "top_languages": [
                {"lang": row["target_lang"], "count": row["count"]}
                for row in langs
            ],
            "api_distribution": {
                row["api_used"]: row["count"]
                for row in apis
            }
        }


def get_api_quota_usage() -> Dict:
    """Get current API usage for today across all servers"""
    with get_db() as conn:
        usage = conn.execute("""
                             SELECT api_name, SUM(chars_used) as total
                             FROM api_usage
                             WHERE date = date ('now')
                             GROUP BY api_name
                             ORDER BY total DESC
                             """).fetchall()

        return {
            row["api_name"]: row["total"]
            for row in usage
        }


def get_server_list() -> List[Dict]:
    """Get list of all servers using the bot"""
    with get_db() as conn:
        servers = conn.execute("""
                               SELECT server_id, enabled_languages, mode, created_at
                               FROM servers
                               ORDER BY created_at DESC
                               """).fetchall()

        return [
            {
                "server_id": row["server_id"],
                "enabled_languages": json.loads(row["enabled_languages"]),
                "mode": row["mode"],
                "created_at": row["created_at"]
            }
            for row in servers
        ]


def cleanup_old_logs(days: int = 90):
    """
    Cleanup old translation logs (for GDPR/storage management)

    Args:
        days: Keep logs newer than this many days
    """
    with get_db() as conn:
        result = conn.execute("""
                              DELETE
                              FROM translations
                              WHERE timestamp < datetime('now', '-' || ? || ' days')
                              """, (days,))

        deleted = result.rowcount
        logger.info(f"Cleaned up {deleted} old translation logs")
        return deleted
