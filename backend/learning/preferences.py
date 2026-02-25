# User preferences manager — persistent, versioned, prompt-injectable
# Stores preferences as human-readable JSON with version snapshots.
# Preferences are fed into all Claude prompts to personalize results.

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Optional

from learning.interaction_logger import interaction_logger


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PREFS_PATH = os.path.join(DATA_DIR, "user_preferences.json")
HISTORY_DIR = os.path.join(DATA_DIR, "preferences_history")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_prefs() -> dict:
    return {"version": 0, "updated_at": _now_iso(), "preferences": []}


class PreferencesManager:
    """Manages user preferences with JSON storage and version history."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(HISTORY_DIR, exist_ok=True)

    def _load(self) -> dict:
        if not os.path.exists(PREFS_PATH):
            return _empty_prefs()
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict):
        """Save preferences and create a version snapshot."""
        data["version"] = data.get("version", 0) + 1
        data["updated_at"] = _now_iso()

        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        # Snapshot for version history
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot = os.path.join(HISTORY_DIR, f"v{data['version']}_{ts}.json")
        shutil.copy2(PREFS_PATH, snapshot)

    def get_all(self) -> dict:
        """Return full preferences data including version info."""
        return self._load()

    def get_active(self) -> list[dict]:
        """Return only active preferences."""
        data = self._load()
        return [p for p in data["preferences"] if p.get("active", True)]

    async def add(self, content: str, category: str = "soft_preference",
                  source: str = "explicit", session_id: Optional[str] = None) -> dict:
        """Add a new preference. Returns the created preference."""
        data = self._load()

        # Avoid exact duplicates
        for p in data["preferences"]:
            if p["content"].lower().strip() == content.lower().strip():
                return p

        pref = {
            "id": f"pref_{uuid.uuid4().hex[:8]}",
            "content": content,
            "category": category,
            "source": source,
            "active": True,
            "created_at": _now_iso(),
        }
        data["preferences"].append(pref)
        self._save(data)

        await interaction_logger.log_preference_change("added", pref, session_id)
        return pref

    async def toggle(self, pref_id: str, session_id: Optional[str] = None) -> Optional[dict]:
        """Toggle a preference active/inactive. Returns updated preference or None."""
        data = self._load()
        for p in data["preferences"]:
            if p["id"] == pref_id:
                p["active"] = not p["active"]
                self._save(data)
                await interaction_logger.log_preference_change(
                    "toggled", {"id": pref_id, "active": p["active"]}, session_id
                )
                return p
        return None

    async def delete(self, pref_id: str, session_id: Optional[str] = None) -> bool:
        """Delete a preference. Returns True if found and deleted."""
        data = self._load()
        original_len = len(data["preferences"])
        data["preferences"] = [p for p in data["preferences"] if p["id"] != pref_id]

        if len(data["preferences"]) < original_len:
            self._save(data)
            await interaction_logger.log_preference_change(
                "deleted", {"id": pref_id}, session_id
            )
            return True
        return False

    def to_prompt_context(self) -> str:
        """Convert active preferences into natural language for Claude prompts.

        Returns empty string if no active preferences exist.

        Example output:
            USER PREFERENCES (always apply these):
            Hard constraints (MUST follow):
            - Never include Air India flights
            Soft preferences (use to influence ranking):
            - Prefer morning departures
        """
        active = self.get_active()
        if not active:
            return ""

        hard = [p["content"] for p in active if p["category"] == "hard_constraint"]
        soft = [p["content"] for p in active if p["category"] == "soft_preference"]
        context = [p["content"] for p in active if p["category"] == "context"]

        lines = ["\n\nUSER PREFERENCES (always apply these):"]

        if hard:
            lines.append("Hard constraints (MUST follow, these are absolute rules):")
            for h in hard:
                lines.append(f"- {h}")

        if soft:
            lines.append("Soft preferences (use to influence ranking when options are comparable):")
            for s in soft:
                lines.append(f"- {s}")

        if context:
            lines.append("Traveler context:")
            for c in context:
                lines.append(f"- {c}")

        return "\n".join(lines)


# Singleton for the app
preferences_manager = PreferencesManager()
