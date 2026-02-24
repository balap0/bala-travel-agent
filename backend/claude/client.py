# Claude API client — handles NL query parsing and result ranking
# Uses the Anthropic Python SDK

import anthropic

from config import get_settings
from claude.prompts import PARSE_SYSTEM_PROMPT, RANK_SYSTEM_PROMPT


class ClaudeClient:
    """Wrapper for the Anthropic Claude API."""

    def __init__(self):
        self._client = None

    def _get_client(self) -> anthropic.Anthropic:
        """Lazy-init the Anthropic client."""
        if self._client is None:
            settings = get_settings()
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def parse_query(self, natural_language_query: str) -> dict:
        """
        Use Claude to parse a natural language travel query into structured params.
        Returns a dict matching the ParsedQuery schema.
        TODO Sprint 2: Full implementation.
        """
        # Placeholder — will call Claude with PARSE_SYSTEM_PROMPT
        return {}

    async def rank_results(self, query: dict, flights: list[dict],
                           preferences: list[str]) -> list[dict]:
        """
        Use Claude to rank flight results and generate explanations.
        Returns a list of dicts matching the RankedResult schema.
        TODO Sprint 2: Full implementation.
        """
        # Placeholder — will call Claude with RANK_SYSTEM_PROMPT
        return []

    async def handle_refinement(self, conversation_history: list,
                                 refinement_message: str,
                                 current_query: dict) -> dict:
        """
        Handle conversational refinement of a search.
        Claude interprets the follow-up and adjusts the query.
        TODO Sprint 2: Full implementation.
        """
        return {}
