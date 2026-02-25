# Search orchestrator — the core coordination engine
# Flow: NL query → Claude parse → Route analysis → Strategy selection → Search → Claude rank → response
# Supports both SSE streaming (for real-time progress) and regular POST (fallback)

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from auth.middleware import require_auth
from claude.client import ClaudeClient
from models.schemas import (
    SearchRequest, SearchResponse, RefineRequest, RefineResponse,
    ParsedQuery, FlightOption, RankedResult, RouteAnalysis,
)
from models.database import save_session, get_session
from providers.amadeus_provider import AmadeusProvider
from providers.serpapi_provider import SerpAPIProvider
from search.strategies.direct import DirectSearchStrategy
from search.strategies.hub_based import HubBasedSearchStrategy

logger = logging.getLogger(__name__)
search_router = APIRouter()

# Singleton instances
claude_client = ClaudeClient()
amadeus = AmadeusProvider()
serpapi = SerpAPIProvider()

# Minimum results from Amadeus before we also query SerpAPI
AMADEUS_MIN_RESULTS = 3


def _sse_event(event: str, data: str) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse_json_event(event: str, data: dict) -> str:
    """Format an SSE event with a JSON payload."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@search_router.post("")
async def search_flights(request: SearchRequest, req: Request, token: str = Depends(require_auth)):
    """
    Main search endpoint. Streams progress via SSE.

    Pipeline:
    1. Claude parses NL query → structured params
    2. Claude analyzes route → strategy selection
    3. Execute strategy (direct or hub-based search)
    4. Merge, deduplicate, rank with Claude
    5. Save session and return final results
    """
    # Check if client wants SSE (Accept header) or regular JSON
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _search_stream(request, token),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # Fallback: regular JSON response (collect all SSE events, return final)
        return await _search_json(request)


async def _search_stream(request: SearchRequest, token: str):
    """Generator that yields SSE events as the search pipeline progresses."""
    try:
        async for event, data in _run_pipeline(request):
            if event == "results":
                yield _sse_json_event("results", data)
            else:
                yield _sse_event(event, data)
    except Exception as e:
        logger.error(f"Search stream error: {e}")
        yield _sse_event("error", f"Search failed: {e}")


async def _search_json(request: SearchRequest) -> SearchResponse:
    """Non-streaming search — collects pipeline output and returns final JSON."""
    final_result = None
    async for event, data in _run_pipeline(request):
        if event == "results":
            final_result = data

    if final_result is None:
        raise HTTPException(status_code=500, detail="Search produced no results")

    return SearchResponse(**final_result)


async def _run_pipeline(request: SearchRequest):
    """
    Core search pipeline. Yields (event_type, data) tuples.
    Final event is ("results", SearchResponse_dict).
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    # --- Step 1: Parse natural language query ---
    yield ("thinking", "Understanding your request...")

    try:
        parsed_dict = await claude_client.parse_query(request.query)
        parsed_query = ParsedQuery(**parsed_dict)
    except Exception as e:
        logger.error(f"Query parsing failed: {e}")
        yield ("error", f"Could not understand query: {e}")
        return

    yield ("thinking", f"Got it — {parsed_query.origin} → {parsed_query.destination}, "
           f"{parsed_query.departure_date}, {parsed_query.cabin_class}")

    # Check if Claude needs clarification from the parse step
    if parsed_query.clarification_needed:
        yield ("clarify", parsed_query.clarification_needed)
        yield ("results", SearchResponse(
            session_id=session_id,
            parsed_query=parsed_query,
            results=[],
            sources_used=[],
            search_duration_seconds=round(time.time() - start_time, 2),
            total_options_found=0,
        ).model_dump(mode="json"))
        return

    # --- Step 2: Analyze route and select strategy ---
    yield ("thinking", f"Analyzing the {parsed_query.origin} → {parsed_query.destination} route...")

    try:
        analysis_dict = await claude_client.analyze_route(
            parsed_query.origin, parsed_query.destination, parsed_query.preferences
        )
        route_analysis = RouteAnalysis(**analysis_dict)
    except Exception as e:
        logger.error(f"Route analysis failed, defaulting to direct search: {e}")
        route_analysis = RouteAnalysis(
            difficulty="standard",
            strategy="direct_search",
            reasoning="Defaulting to direct search.",
        )

    # Send route analysis to client
    yield ("strategy", route_analysis.reasoning)

    if route_analysis.destination_brief:
        yield ("strategy", route_analysis.destination_brief)

    # Handle clarifying questions for hard routes
    if route_analysis.clarifying_questions:
        for q in route_analysis.clarifying_questions:
            yield ("clarify", q)

    # --- Step 3: Execute search strategy ---
    if route_analysis.strategy == "hub_based" and route_analysis.connecting_hubs:
        strategy = HubBasedSearchStrategy(amadeus, serpapi, route_analysis)
    else:
        strategy = DirectSearchStrategy(amadeus, serpapi)

    all_flights: list[FlightOption] = []
    async for event_type, message, flights in strategy.execute(parsed_query):
        if event_type == "done":
            all_flights = flights
        else:
            yield (event_type, message)

    sources_used = list({f.source for f in all_flights})

    # --- Step 4: Handle no results ---
    if not all_flights:
        no_result_msg = _build_no_results_message(parsed_query, route_analysis)
        yield ("thinking", no_result_msg)
        yield ("results", SearchResponse(
            session_id=session_id,
            parsed_query=parsed_query,
            results=[],
            sources_used=sources_used,
            search_duration_seconds=round(time.time() - start_time, 2),
            total_options_found=0,
            route_analysis=route_analysis,
        ).model_dump(mode="json"))
        return

    # --- Step 5: Deduplicate ---
    all_flights = _deduplicate_flights(all_flights)

    # --- Step 6: Rank with Claude ---
    yield ("ranking", f"Found {len(all_flights)} options, ranking by your preferences...")

    flights_as_dicts = [f.model_dump() for f in all_flights]

    try:
        rankings = await claude_client.rank_results(
            parsed_query.model_dump(),
            flights_as_dicts,
            parsed_query.preferences,
        )
    except Exception as e:
        logger.error(f"Ranking failed: {e}")
        rankings = [
            {"rank": i + 1, "flight_id": f.id, "explanation": "Sorted by price (AI ranking unavailable)", "tags": []}
            for i, f in enumerate(sorted(all_flights, key=lambda x: x.price_usd))
        ]

    # --- Step 7: Build ranked results ---
    flight_map = {f.id: f for f in all_flights}
    ranked_results = []

    for ranking in rankings:
        flight_id = ranking.get("flight_id", "")
        flight = flight_map.get(flight_id)
        if not flight:
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

    # --- Step 8: Save session ---
    conversation = [{"role": "user", "content": request.query}]
    await save_session(
        session_id=session_id,
        parsed_query=parsed_query.model_dump(),
        conversation=conversation,
        results=[r.model_dump() for r in ranked_results],
    )

    duration = round(time.time() - start_time, 2)
    logger.info(f"Search complete: {len(ranked_results)} results in {duration}s")

    yield ("results", SearchResponse(
        session_id=session_id,
        parsed_query=parsed_query,
        results=ranked_results,
        sources_used=sources_used,
        search_duration_seconds=duration,
        total_options_found=len(ranked_results),
        route_analysis=route_analysis,
    ).model_dump(mode="json"))


def _build_no_results_message(query: ParsedQuery, analysis: RouteAnalysis) -> str:
    """Explain what was tried when no flights are found."""
    parts = [f"I couldn't find flights from {query.origin} to {query.destination} on {query.departure_date}."]

    if analysis.strategy == "hub_based" and analysis.connecting_hubs:
        hubs = ", ".join(analysis.connecting_hubs)
        parts.append(f"I searched direct flights and connections via {hubs}.")
    else:
        parts.append("I searched all available providers.")

    parts.append("Would you like me to try flexible dates or a different cabin class?")
    return " ".join(parts)


# --- Refine endpoint (unchanged from original) ---

@search_router.post("/{session_id}/refine", response_model=RefineResponse)
async def refine_search(
    session_id: str,
    request: RefineRequest,
    token: str = Depends(require_auth),
):
    """Refine an existing search conversationally."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    current_query = session.get("parsed_query", {})
    conversation = session.get("conversation_history", [])

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

    if result.get("needs_new_search") and result.get("updated_query"):
        try:
            updated = ParsedQuery(**result["updated_query"])
            response.updated_query = updated

            # Run search with updated params using direct strategy
            strategy = DirectSearchStrategy(amadeus, serpapi)
            all_flights = []
            async for event_type, message, flights in strategy.execute(updated):
                if event_type == "done":
                    all_flights = flights

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
    """Remove duplicate flights across providers and search strategies."""
    seen = set()
    unique = []

    for flight in flights:
        segments_key = tuple(
            (s.departure_airport, s.arrival_airport, s.airline_code, s.flight_number)
            for s in flight.segments
        )
        price_bucket = round(flight.price_usd / 10) * 10
        fingerprint = (segments_key, price_bucket)

        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(flight)

    if len(flights) != len(unique):
        logger.info(f"Deduplicated {len(flights)} → {len(unique)} flights")

    return unique
