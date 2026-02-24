# SQLite database for session and conversation storage
# Lightweight, zero-cost persistence for a single-user app

import aiosqlite
import json
import os
from datetime import date, datetime


class _DateEncoder(json.JSONEncoder):
    """JSON encoder that handles date/datetime objects from Pydantic models."""
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _dumps(obj):
    """JSON serialize with date support."""
    return json.dumps(obj, cls=_DateEncoder)


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sessions.db")


async def init_db():
    """Initialize SQLite database and create tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                parsed_query TEXT,
                conversation_history TEXT DEFAULT '[]',
                last_results TEXT
            )
        """)
        await db.commit()


async def save_session(session_id: str, parsed_query: dict = None,
                       conversation: list = None, results: list = None):
    """Save or update a search session."""
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        existing = await db.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = await existing.fetchone()

        if row:
            updates = ["updated_at = ?"]
            params = [now]
            if parsed_query is not None:
                updates.append("parsed_query = ?")
                params.append(_dumps(parsed_query))
            if conversation is not None:
                updates.append("conversation_history = ?")
                params.append(_dumps(conversation))
            if results is not None:
                updates.append("last_results = ?")
                params.append(_dumps(results))
            params.append(session_id)

            await db.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?",
                params
            )
        else:
            await db.execute(
                """INSERT INTO sessions (session_id, created_at, updated_at,
                   parsed_query, conversation_history, last_results)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id, now, now,
                    _dumps(parsed_query) if parsed_query else None,
                    _dumps(conversation or []),
                    _dumps(results) if results else None,
                )
            )
        await db.commit()


async def get_session(session_id: str) -> dict | None:
    """Retrieve a session by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None

        return {
            "session_id": row[0],
            "created_at": row[1],
            "updated_at": row[2],
            "parsed_query": json.loads(row[3]) if row[3] else None,
            "conversation_history": json.loads(row[4]) if row[4] else [],
            "last_results": json.loads(row[5]) if row[5] else None,
        }
