"""SQLite persistence for Provenance Guard.

Two tables (see planning.md "Locked decisions"):
  - content_records : one row per submission — its text, verdict, per-signal scores,
                      and status (flipped to "under_review" on appeal).
  - audit_log       : append-only structured history of every decision and appeal.

The audit_log stores each event's structured fields as a JSON string in `detail`,
so both classification and appeal events share one flexible schema. GET /log parses
`detail` back out and flattens it into each returned entry.
"""
import json
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now() -> str:
    """ISO 8601 UTC timestamp, e.g. 2025-04-01T14:32:10.123456+00:00."""
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_records (
                content_id        TEXT PRIMARY KEY,
                creator_id        TEXT NOT NULL,
                text              TEXT NOT NULL,
                attribution       TEXT,
                confidence        REAL,
                ai_probability    REAL,
                llm_score         REAL,
                stylometric_score REAL,
                lexical_score     REAL,
                status            TEXT NOT NULL,
                created_at        TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                detail     TEXT NOT NULL
            )
            """
        )


def create_content_record(
    *,
    content_id: str,
    creator_id: str,
    text: str,
    attribution: str,
    confidence: float | None,
    ai_probability: float | None,
    llm_score: float | None,
    status: str,
    created_at: str,
) -> None:
    """Insert a freshly classified submission. Signal-2/3 scores fill in at M4."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO content_records (
                content_id, creator_id, text, attribution, confidence,
                ai_probability, llm_score, stylometric_score, lexical_score,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                content_id, creator_id, text, attribution, confidence,
                ai_probability, llm_score, status, created_at,
            ),
        )


def get_content_record(content_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM content_records WHERE content_id = ?", (content_id,)
        ).fetchone()
    return dict(row) if row else None


def add_audit_entry(content_id: str, event_type: str, detail: dict) -> None:
    """Append one structured event (classification or appeal) to the audit log."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (content_id, event_type, timestamp, detail) "
            "VALUES (?, ?, ?, ?)",
            (content_id, event_type, detail.get("timestamp", utc_now()),
             json.dumps(detail)),
        )


def get_recent_log(limit: int = 20) -> list[dict]:
    """Return the most recent audit entries (newest first), detail flattened in."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    entries = []
    for row in rows:
        entry = {"event_type": row["event_type"]}
        entry.update(json.loads(row["detail"]))
        entries.append(entry)
    return entries
