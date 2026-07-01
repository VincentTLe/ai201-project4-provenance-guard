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
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db():
    """Yield a connection that both commits (via `with conn`) AND closes.

    Note: sqlite3's own connection context manager only manages the transaction —
    it does not close the connection — so we close it explicitly here to avoid
    leaking a file handle on every call.
    """
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def utc_now() -> str:
    """ISO 8601 UTC timestamp, e.g. 2025-04-01T14:32:10.123456+00:00."""
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _db() as conn:
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
        # Provenance-certificate tables (stretch feature).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS certificates (
                cert_id    TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                issued_at  TEXT NOT NULL,
                status     TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS challenges (
                challenge_id TEXT PRIMARY KEY,
                creator_id   TEXT NOT NULL,
                phrase       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                used         INTEGER NOT NULL DEFAULT 0
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
    stylometric_score: float | None,
    lexical_score: float | None,
    status: str,
    created_at: str,
) -> None:
    """Insert a freshly classified submission with all three signal scores."""
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO content_records (
                content_id, creator_id, text, attribution, confidence,
                ai_probability, llm_score, stylometric_score, lexical_score,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id, creator_id, text, attribution, confidence,
                ai_probability, llm_score, stylometric_score, lexical_score,
                status, created_at,
            ),
        )


def get_content_record(content_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM content_records WHERE content_id = ?", (content_id,)
        ).fetchone()
    return dict(row) if row else None


def update_content_status(content_id: str, status: str) -> None:
    """Set a content record's status (e.g. 'under_review' when an appeal is filed)."""
    with _db() as conn:
        conn.execute(
            "UPDATE content_records SET status = ? WHERE content_id = ?",
            (status, content_id),
        )


def add_audit_entry(content_id: str, event_type: str, detail: dict) -> None:
    """Append one structured event (classification or appeal) to the audit log."""
    with _db() as conn:
        conn.execute(
            "INSERT INTO audit_log (content_id, event_type, timestamp, detail) "
            "VALUES (?, ?, ?, ?)",
            (content_id, event_type, detail.get("timestamp", utc_now()),
             json.dumps(detail)),
        )


def create_challenge(challenge_id: str, creator_id: str, phrase: str, created_at: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO challenges (challenge_id, creator_id, phrase, created_at, used) "
            "VALUES (?, ?, ?, ?, 0)",
            (challenge_id, creator_id, phrase, created_at),
        )


def get_challenge(challenge_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM challenges WHERE challenge_id = ?", (challenge_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_challenge_used(challenge_id: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE challenges SET used = 1 WHERE challenge_id = ?", (challenge_id,))


def issue_certificate(cert_id: str, creator_id: str, issued_at: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO certificates (cert_id, creator_id, issued_at, status) "
            "VALUES (?, ?, ?, 'verified_human')",
            (cert_id, creator_id, issued_at),
        )


def get_active_certificate(creator_id: str) -> dict | None:
    """Return the creator's most recent active certificate, or None."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM certificates WHERE creator_id = ? AND status = 'verified_human' "
            "ORDER BY issued_at DESC LIMIT 1",
            (creator_id,),
        ).fetchone()
    return dict(row) if row else None


def get_analytics() -> dict:
    """Aggregate detection stats for the analytics dashboard (GET /analytics).

    Reads straight from SQLite — no new storage. Returns verdict distribution,
    appeal rate, and mean confidence / ai_probability.
    """
    with _db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM content_records"
        ).fetchone()["n"]

        dist_rows = conn.execute(
            "SELECT attribution, COUNT(*) AS n FROM content_records GROUP BY attribution"
        ).fetchall()
        verdict_distribution = {row["attribution"]: row["n"] for row in dist_rows}

        under_review = conn.execute(
            "SELECT COUNT(*) AS n FROM content_records WHERE status = 'under_review'"
        ).fetchone()["n"]

        appeals = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'appeal'"
        ).fetchone()["n"]

        means = conn.execute(
            "SELECT AVG(confidence) AS c, AVG(ai_probability) AS p FROM content_records"
        ).fetchone()

    appeal_rate = round(appeals / total, 4) if total else 0.0
    return {
        "total_classifications": total,
        "verdict_distribution": verdict_distribution,
        "appeals": appeals,
        "under_review": under_review,
        "appeal_rate": appeal_rate,
        "mean_confidence": round(means["c"], 4) if means["c"] is not None else None,
        "mean_ai_probability": round(means["p"], 4) if means["p"] is not None else None,
    }


def get_recent_log(limit: int = 20) -> list[dict]:
    """Return the most recent audit entries (newest first), detail flattened in."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    entries = []
    for row in rows:
        entry = {"event_type": row["event_type"]}
        entry.update(json.loads(row["detail"]))
        entries.append(entry)
    return entries
