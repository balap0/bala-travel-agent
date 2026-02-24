# Search orchestrator — the core coordination engine
# Flow: NL query → Claude parse → Amadeus + SerpAPI (parallel) → merge → Claude rank → response

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth.middleware import require_auth
from claude.client import ClaudeClient
from models.schemas import (
    SearchRequest, SearchResponse, RefineRequest, RefineResponse,
    ParsedQuery, FlightOption, RankedResult,
)
from models.database import save_session, get_session
from providers.amadeus_provider import AmadeusProvider
from providers.serpapi_provider import SerpAPIProvider

logger = logging.getLogger(__name__)
search_router = APIRouter()

# Singleton instances (created once, reused across requests)
claude_client = ClaudeClient()
amadeus = AmadeusProvider()
serpapi = SerpAPIProvider()

# Minimum results from Amadeus before we also query SerpAPI
AMADEUS_MIN_RESULTS = 3


@search_router.post("", response_model=SearchResponse)
async def search_flights(request: SearchRequest, token: str = Depends(require_auth)):
    """
    Main search endpoint. Full pipeline:
    1. Claude parses NL query → structured params
    2. Search Amadeus (always) + SerpAPI (if needed) in parallel
    3. Merge and deduplicate results
    4. Claude ranks and explains each result
    5. Save session and return
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    # --- Step 1: Parse natural language query with Claude ---
    try:
        parsed_dict = await claude_client.parse_query(request.query)
        parsed_query = ParsedQuery(**parsed_dict)
    except Exception as e:
        logger.error(f"Query parsing failed: {e}")
        raise HTTPException(status_code=400, detail=f"Could not understand query: {e}")

    # Check if Claude needs clarification
    if parsed_query.clarification_needed:
        return SearchResponse(
            session_id=session_id,
            parsed_query=parsed_query,
            results=[],
            sources_used=[],
            search_duration_seconds=round(time.time() - start_time, 2),
            total_options_found=0,
        )

    # --- Step 2: Search flight providers ---
    all_flights: list[FlightOption] = []
    sources_used: list[str] = []

    # Always search Amadeus first
    amadeus_results = await amadeus.search(parsed_query)
    if amadeus_results:
        all_flights.extend(amadeus_results)
        sources_used.append("amadeus")
        logger.info(f"Amadeus returned {len(amadeus_results)} results")

    # Search SerpAPI if Amadeus has few results or SerpAPI is available
    if len(amadeus_results) < AMADEUS_MIN_RESULTS:
        serpapi_results = await serpapi.search(parsed_query)
        if serpapi_results:
            all_flights.extend(serpapi_results)
            sources_used.append("serpapi")
            logger.info(f"SerpAPI returned {len(serpapi_results)} results")

    if not all_flights:
        return SearchResponse(
            session_id=session_id,
            parsed_query=parsed_query,
            results=[],
            sources_used=sources_used,
            search_duration_seconds=round(time.time() - start_time, 2),
            total_options_found=0,
        )

    # --- Step 3: Deduplicate ---
    all_flights = _deduplicate_flights(all_flights)

    # --- Step 4: Rank with Claude ---
    flights_as_dicts = [f.model_dump() for f in all_flights]

    try:
        rankings = await claude_client.rank_results(
            parsed_query.model_dump(),
            flights_as_dicts,
            parsed_query.preferences,
        )
    except Exception as e:
        logger.error(f"Ranking failed: {e}")
        # Fallback: sort by price
        rankings = [
            {"rank": i + 1, "flight_id": f.id, "explanation": "Sorted by price (AI ranking unavailable)", "tags": []}
            for i, f in enumerate(sorted(all_flights, key=lambda x: x.price_usd))
        ]

    # --- Step 5: Build ranked results ---
    flight_map = {f.id: f for f in all_flights}
    ranked_results = []

    for ranking in rankings:
        flight_id = ranking.get("flight_id", "")
        flight = flight_map.get(flight_id)
        if not flight:
            # Try to match by index if ID doesn't match
            idx = ranking.get("rank", 1) - 1
            if 0 <= idx < len(all_flights):
                flight = all_flights[idx]
            else:
                continue

        ranked_results.append(RankedResult(
            rank=ranking.get("rank", len(ranked_results) + 1),
            flight=flight,
            explanation=ranking.get("explanation", ""),
            tags=ranking.get("tags", []),
        ))

    # --- Step 6: Save session ---
    conversation = [{"role": "user", "content": request.query}]
    await save_session(
        session_id=session_id,
        parsed_query=parsed_query.model_dump(),
        conversation=conversation,
        results=[r.model_dump() for r in ranked_results],
    )

    duration = round(time.time() - start_time, 2)
    logger.info(f"Search complete: {len(ranked_results)} results in {duration}s")

    return SearchResponse(
        session_id=session_id,
        parsed_query=parsed_query,
        results=ranked_results,
        sources_used=sources_used,
        search_duration_seconds=duration,
        total_options_found=len(ranked_results),
    )


@search_router.post("/{session_id}/refine", response_model=RefineResponse)
async def refine_search(
    session_id: str,
    request: RefineRequest,
    token: str = Depends(require_auth),
):
    """
    Refine an existing search conversationally.
    Claude interprets the follow-up and decides whether a new search is needed.
    """
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    current_query = session.get("parsed_query", {})
    conversation = session.get("conversation_history", [])

    # Ask Claude to interpret the refinement
    try:
        result = await claude_client.handle_refinement(
            conversation_history=conversation,
            refinement_message=request.message,
            current_query=current_query,
        )
    except Exception as e:
        logger.error(f"Refinement failed: {e}")
        return RefineResponse(
            session_id=session_id,
            message="Sorry, I couldn't process that refinement. Please try rephrasing.",
        )

    response = RefineResponse(
        session_id=session_id,
        message=result.get("message", ""),
    )

    # If a new search is needed, run it
    if result.get("needs_new_search") and result.get("updated_query"):
        try:
            updated = ParsedQuery(**result["updated_query"])
            response.updated_query = updated

            # Run the search pipeline with updated params
            all_flights = await amadeus.search(updated)
            sources = ["amadeus"] if all_flights else []

            if len(all_flights) < AMADEUS_MIN_RESULTS:
                serpapi_results = await serpapi.search(updated)
                if serpapi_results:
                    all_flights.extend(serpapi_results)
                    sources.append("serpapi")

            if all_flights:
                all_flights = _deduplicate_flights(all_flights)
                flights_as_dicts = [f.model_dump() for f in all_flights]
                rankings = await claude_client.rank_results(
                    updated.model_dump(), flights_as_dicts, updated.preferences
                )

                flight_map = {f.id: f for f in all_flights}
                response.results = []
                for ranking in rankings:
                    flight = flight_map.get(ranking.get("flight_id", ""))
                    if not flight:
                        idx = ranking.get("rank", 1) - 1
                        if 0 <= idx < len(all_flights):
                            flight = all_flights[idx]
                        else:
                            continue
                    response.results.append(RankedResult(
                        rank=ranking.get("rank", 1),
                        flight=flight,
                        explanation=ranking.get("explanation", ""),
                        tags=ranking.get("tags", []),
                    ))

        except Exception as e:
            logger.error(f"Refined search failed: {e}")
            response.message += " (Search with updated params failed, showing previous results.)"

    # Update conversation history
    conversation.append({"role": "user", "content": request.message})
    conversation.append({"role": "assistant", "content": result.get("message", "")})
    await save_session(session_id=session_id, conversation=conversation)

    return response


@search_router.get("/{session_id}")
async def get_search_results(session_id: str, token: str = Depends(require_auth)):
    """Retrieve cached results from a previous search session."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "parsed_query": session.get("parsed_query"),
        "results": session.get("last_results", []),
        "sources_used": [],
        "search_duration_seconds": 0,
        "total_options_found": len(session.get("last_results", [])),
    }


def _deduplicate_flights(flights: list[FlightOption]) -> list[FlightOption]:
    """
    Remove duplicate flights across providers.
    Two flights are considered duplicates if they have the same route segments
    at similar times and similar prices.
    """
    seen = set()
    unique = []

    for flight in flights:
        # Create a fingerprint from key attributes
        segments_key = tuple(
            (s.departure_airport, s.arrival_airport, s.airline_code, s.flight_number)
            for s in flight.segments
        )
        # Round price to nearest $10 to catch minor price differences
        price_bucket = round(flight.price_usd / 10) * 10
        fingerprint = (segments_key, price_bucket)

        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(flight)

    if len(flights) != len(unique):
        logger.info(f"Deduplicated {len(flights)} → {len(unique)} flights")

    return unique
