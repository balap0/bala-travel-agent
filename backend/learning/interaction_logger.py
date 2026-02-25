# Append-only interaction logger — records every user action and system event
# Writes to a JSONL file that's both human-readable and machine-parseable.
# This is the data foundation for the self-improvement flywheel.

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


# Log file lives alongside the SQLite DB in backend/data/
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "interactions.jsonl")


class InteractionLogger:
    """Thread-safe, append-only JSONL logger for all user interactions."""

    def __init__(self):
        self._lock = asyncio.Lock()
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    async def _write(self, event: str, session_id: Optional[str], data: dict[str, Any]):
        """Write a single JSONL line. Never blocks the caller for long."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": session_id,
            "event": event,
            "data": data,
        }
        line = json.dumps(entry, default=str) + "\n"
        async with self._lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)

    # --- Pipeline events ---

    async def log_search(self, session_id: str, raw_query: str, parsed: dict):
        """Log when a search query is parsed."""
        await self._write("search_query", session_id, {
            "raw_query": raw_query,
            "origin": parsed.get("origin"),
            "destination": parsed.get("destination"),
            "departure_date": parsed.get("departure_date"),
            "cabin_class": parsed.get("cabin_class"),
            "max_stops": parsed.get("max_stops"),
            "preferences": parsed.get("preferences", []),
        })

    async def log_route_analysis(self, session_id: str, analysis: dict):
        """Log route analysis results."""
        await self._write("route_analysis", session_id, {
            "difficulty": analysis.get("difficulty"),
            "strategy": analysis.get("strategy"),
            "hubs": analysis.get("connecting_hubs", []),
            "airlines": analysis.get("recommended_airlines", []),
            "reasoning": analysis.get("reasoning", ""),
        })

    async def log_results(self, session_id: str, total_found: int,
                          sources: list[str], duration_s: float,
                          price_range: Optional[tuple[float, float]] = None):
        """Log search results summary."""
        await self._write("search_results", session_id, {
            "total_found": total_found,
            "sources": sources,
            "duration_s": round(duration_s, 2),
            "price_range": list(price_range) if price_range else None,
        })

    async def log_ranking(self, session_id: str, top_results: list[dict]):
        """Log the top-ranked results after Claude ranking."""
        # Only log a summary of top 3 to keep log lines readable
        summary = []
        for r in top_results[:3]:
            flight = r.get("flight", {})
            summary.append({
                "rank": r.get("rank"),
                "airline": ", ".join(flight.get("airline_names", [])),
                "price": flight.get("price_usd"),
                "duration_h": round(flight.get("total_duration_minutes", 0) / 60, 1),
                "tags": r.get("tags", []),
            })
        await self._write("ranking", session_id, {"top_results": summary})

    async def log_refinement(self, session_id: str, message: str,
                             triggered_new_search: bool):
        """Log a refinement request."""
        await self._write("refinement", session_id, {
            "message": message,
            "triggered_new_search": triggered_new_search,
        })

    # --- Frontend interaction events ---

    async def log_interaction(self, session_id: Optional[str], action: str,
                              details: dict[str, Any] = None):
        """Log a frontend interaction (click, expand, scroll)."""
        await self._write("user_click", session_id, {
            "action": action,
            **(details or {}),
        })

    # --- Preference events ---

    async def log_preference_change(self, event_type: str, preference: dict,
                                    session_id: Optional[str] = None):
        """Log preference additions, toggles, and deletions."""
        await self._write(f"preference_{event_type}", session_id, preference)


# Singleton instance for the app
interaction_logger = InteractionLogger()
