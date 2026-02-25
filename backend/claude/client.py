# Claude API client — handles NL query parsing and result ranking
# Uses the Anthropic Python SDK for all AI interactions

import asyncio
import json
import logging
import random

import anthropic

from config import get_settings
from claude.prompts import (
    PARSE_SYSTEM_PROMPT, RANK_SYSTEM_PROMPT, REFINE_SYSTEM_PROMPT,
    ROUTE_ANALYSIS_PROMPT, CLARIFICATION_RESPONSE_PROMPT,
)

logger = logging.getLogger(__name__)

# Retry config for transient API errors (529 overloaded, 500, etc.)
MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds


class ClaudeClient:
    """Wrapper for the Anthropic Claude API. Handles parsing, ranking, and refinement."""

    def __init__(self):
        self._client = None

    def _get_client(self) -> anthropic.Anthropic:
        """Lazy-init the Anthropic client."""
        if self._client is None:
            settings = get_settings()
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def _call_with_retry(self, create_fn, **kwargs):
        """Call Claude API with exponential backoff retry on transient errors (529, 500)."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(create_fn, **kwargs)
            except anthropic.APIStatusError as e:
                last_error = e
                if e.status_code in (529, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Claude API {e.status_code} (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_error  # Should not reach here, but just in case

    def _inject_preferences(self, base_prompt: str, preferences_context: str = "") -> str:
        """Append user preferences to a system prompt if they exist."""
        if preferences_context:
            return base_prompt + "\n" + preferences_context
        return base_prompt

    async def parse_query(self, natural_language_query: str,
                          preferences_context: str = "") -> dict:
        """
        Parse a natural language travel query into structured search params.
        Returns a dict matching the ParsedQuery schema fields.

        Example:
          Input:  "Flights from BLR to Nairobi Sep 4, business, minimize time"
          Output: {"origin": "BLR", "destination": "NBO", "departure_date": "2026-09-04", ...}
        """
        settings = get_settings()
        client = self._get_client()
        system_prompt = self._inject_preferences(PARSE_SYSTEM_PROMPT, preferences_context)

        try:
            response = await self._call_with_retry(
                client.messages.create,
                model=settings.claude_model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": natural_language_query}
                ],
            )

            # Extract the text response
            text = response.content[0].text.strip()

            # Clean up potential markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            parsed = json.loads(text)
            parsed["raw_query"] = natural_language_query

            logger.info(f"Claude parsed query: {parsed.get('origin')} -> {parsed.get('destination')}")
            return parsed

        except json.JSONDecodeError as e:
            logger.error(f"Claude returned invalid JSON for query parsing: {e}")
            raise ValueError(f"Failed to parse query: AI returned invalid format")
        except Exception as e:
            logger.error(f"Claude parse_query failed: {e}")
            raise

    async def analyze_route(self, origin: str, destination: str,
                            preferences: list[str] = None,
                            preferences_context: str = "") -> dict:
        """
        Analyze a route to determine search strategy before any flight API calls.
        Returns a dict matching the RouteAnalysis schema.

        Example:
          Input:  origin="BLR", destination="LBV"
          Output: {"difficulty": "challenging", "strategy": "hub_based",
                   "connecting_hubs": ["ADD", "IST", "CDG"], ...}
        """
        settings = get_settings()
        client = self._get_client()

        user_message = json.dumps({
            "origin": origin,
            "destination": destination,
            "user_preferences": preferences or [],
        })

        try:
            system_prompt = self._inject_preferences(ROUTE_ANALYSIS_PROMPT, preferences_context)
            response = await self._call_with_retry(
                client.messages.create,
                model=settings.claude_model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ],
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            analysis = json.loads(text)
            logger.info(
                f"Route analysis: {origin}→{destination} = {analysis.get('difficulty')} "
                f"({analysis.get('strategy')}), hubs={analysis.get('connecting_hubs', [])}"
            )
            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"Claude returned invalid JSON for route analysis: {e}")
            # Fallback: assume standard direct search
            return {
                "difficulty": "standard",
                "strategy": "direct_search",
                "connecting_hubs": [],
                "recommended_airlines": [],
                "destination_brief": "",
                "clarifying_questions": [],
                "reasoning": "Defaulting to direct search (route analysis failed).",
            }
        except Exception as e:
            logger.error(f"Claude route analysis failed: {e}")
            return {
                "difficulty": "standard",
                "strategy": "direct_search",
                "connecting_hubs": [],
                "recommended_airlines": [],
                "destination_brief": "",
                "clarifying_questions": [],
                "reasoning": "Defaulting to direct search (route analysis failed).",
            }

    async def rank_results(self, parsed_query: dict, flights: list[dict],
                           preferences: list[str],
                           preferences_context: str = "") -> list[dict]:
        """
        Rank flight results and generate natural language explanations.
        Returns a list of dicts with: rank, explanation, tags, flight_id.

        Claude sees all flight data and the user's preferences, then produces
        a ranked list with detailed reasoning for each position.
        """
        if not flights:
            return []

        settings = get_settings()
        client = self._get_client()

        # Build a concise summary of flights for Claude (reduce token usage)
        flight_summaries = []
        for f in flights:
            summary = {
                "id": f["id"],
                "airlines": f["airline_names"],
                "price_usd": f["price_usd"],
                "total_duration_minutes": f["total_duration_minutes"],
                "num_stops": f["num_stops"],
                "cabin_class": f["cabin_class"],
                "source": f["source"],
            }
            # Add layover info
            if f.get("layovers"):
                summary["layovers"] = [
                    {"airport": l["airport"], "minutes": l["duration_minutes"], "overnight": l.get("overnight", False)}
                    for l in f["layovers"]
                ]
            # Add segments for route info
            if f.get("segments"):
                summary["route"] = " → ".join(
                    [s["departure_airport"] for s in f["segments"]] +
                    [f["segments"][-1]["arrival_airport"]]
                )
            if f.get("co2_emissions_kg"):
                summary["co2_kg"] = f["co2_emissions_kg"]
            if f.get("fare_brand"):
                summary["fare_brand"] = f["fare_brand"]
            flight_summaries.append(summary)

        user_message = json.dumps({
            "user_preferences": preferences,
            "parsed_query": {
                "origin": parsed_query.get("origin"),
                "destination": parsed_query.get("destination"),
                "cabin_class": parsed_query.get("cabin_class"),
            },
            "flights": flight_summaries,
        }, indent=2)

        try:
            system_prompt = self._inject_preferences(RANK_SYSTEM_PROMPT, preferences_context)
            response = await self._call_with_retry(
                client.messages.create,
                model=settings.claude_model,
                max_tokens=2048,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ],
            )

            text = response.content[0].text.strip()

            # Clean up markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            rankings = json.loads(text)

            # Ensure rankings is a list
            if isinstance(rankings, dict) and "rankings" in rankings:
                rankings = rankings["rankings"]

            logger.info(f"Claude ranked {len(rankings)} flights")
            return rankings

        except json.JSONDecodeError as e:
            logger.error(f"Claude returned invalid JSON for ranking: {e}")
            # Fallback: return flights in original order with generic explanation
            return [
                {
                    "rank": i + 1,
                    "flight_id": f["id"],
                    "explanation": f"${f['price_usd']:.0f}, {f['total_duration_minutes'] // 60}h {f['total_duration_minutes'] % 60}m, {f['num_stops']} stop(s)",
                    "tags": ["recommended"] if i == 0 else [],
                }
                for i, f in enumerate(flights)
            ]
        except Exception as e:
            logger.error(f"Claude rank_results failed: {e}")
            raise

    async def handle_refinement(self, conversation_history: list,
                                refinement_message: str,
                                current_query: dict,
                                preferences_context: str = "") -> dict:
        """
        Handle conversational refinement of a search.
        Claude interprets the follow-up and determines what to change.

        Returns: {"message": str, "updated_query": dict|None, "needs_new_search": bool}
        """
        settings = get_settings()
        client = self._get_client()

        user_message = json.dumps({
            "current_query": current_query,
            "conversation_history": conversation_history[-10:],  # Last 10 messages for full context
            "user_message": refinement_message,
        }, indent=2)

        try:
            system_prompt = self._inject_preferences(REFINE_SYSTEM_PROMPT, preferences_context)
            response = await self._call_with_retry(
                client.messages.create,
                model=settings.claude_model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ],
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)
            logger.info(f"Claude refinement: needs_new_search={result.get('needs_new_search')}")
            return result

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Claude refinement failed: {e}")
            return {
                "message": "I couldn't understand that refinement. Could you rephrase?",
                "updated_query": None,
                "needs_new_search": False,
            }

    async def incorporate_clarification(self, questions: list[str],
                                         user_answer: str,
                                         preferences_context: str = "") -> dict:
        """
        Process user's answer to clarifying questions and return search adjustments.

        Returns: {
            "adjusted_preferences": ["avoid_long_layovers", ...],
            "adjusted_max_stops": int | null,
            "notes_for_ranking": "User prefers shorter layovers...",
            "preference_to_save": {"content": "...", "category": "..."} | null,
            "summary": "Got it, I'll look for shorter connections..."
        }
        """
        settings = get_settings()
        client = self._get_client()

        prompt = CLARIFICATION_RESPONSE_PROMPT.format(
            questions="\n".join(f"- {q}" for q in questions),
            answer=user_answer,
        )

        system_prompt = self._inject_preferences(prompt, preferences_context)

        try:
            response = await self._call_with_retry(
                client.messages.create,
                model=settings.claude_model,
                max_tokens=512,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_answer}
                ],
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)
            logger.info(f"Clarification result: {result.get('summary', '')}")
            return result

        except Exception as e:
            logger.error(f"Claude incorporate_clarification failed: {e}")
            return {
                "adjusted_preferences": [],
                "adjusted_max_stops": None,
                "notes_for_ranking": "",
                "summary": "I'll proceed with your search.",
            }
