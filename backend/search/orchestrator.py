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
    SearchRequest, SearchResponse, RefineRequest, RefineResponse, ReplyRequest,
    ParsedQuery, FlightOption, RankedResult, RouteAnalysis,
)
from models.database import save_session, get_session
from providers.amadeus_provider import AmadeusProvider
from providers.serpapi_provider import SerpAPIProvider
from search.strategies.direct import DirectSearchStrategy
from search.strategies.hub_based import HubBasedSearchStrategy
from learning.interaction_logger import interaction_logger
from learning.preferences import preferences_manager

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
    Tracks full conversation history for context preservation.
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    # Conversation history — tracks everything for context
    conversation = [{"role": "user", "content": request.query}]

    # --- Load user preferences for prompt injection ---
    pref_context = preferences_manager.to_prompt_context()

    # --- Step 1: Parse natural language query ---
    yield ("thinking", "Understanding your request...")

    try:
        parsed_dict = await claude_client.parse_query(request.query, preferences_context=pref_context)
        parsed_query = ParsedQuery(**parsed_dict)
    except Exception as e:
        logger.error(f"Query parsing failed: {e}")
        yield ("error", f"Could not understand query: {e}")
        return

    trip_desc = f"{parsed_query.origin} → {parsed_query.destination}, {parsed_query.departure_date}"
    if parsed_query.return_date:
        trip_desc += f", returning {parsed_query.return_date}"
    trip_desc += f", {parsed_query.cabin_class}"
    yield ("thinking", f"Got it — {trip_desc}")
    conversation.append({"role": "assistant", "content": f"Understood: {trip_desc}"})

    # Log the parsed search
    await interaction_logger.log_search(session_id, request.query, parsed_dict)

    # Check if Claude needs clarification from the parse step
    if parsed_query.clarification_needed:
        yield ("clarify", parsed_query.clarification_needed)
        conversation.append({"role": "assistant", "content": f"Need clarification: {parsed_query.clarification_needed}"})
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
            parsed_query.origin, parsed_query.destination, parsed_query.preferences,
            preferences_context=pref_context,
        )
        route_analysis = RouteAnalysis(**analysis_dict)
    except Exception as e:
        logger.error(f"Route analysis failed, defaulting to direct search: {e}")
        route_analysis = RouteAnalysis(
            difficulty="standard",
            strategy="direct_search",
            reasoning="Defaulting to direct search.",
        )

    # Log route analysis
    await interaction_logger.log_route_analysis(session_id, route_analysis.model_dump())

    # Send route analysis to client
    yield ("strategy", route_analysis.reasoning)
    conversation.append({"role": "assistant", "content": f"Route analysis: {route_analysis.reasoning}"})

    if route_analysis.destination_brief:
        yield ("strategy", route_analysis.destination_brief)
        conversation.append({"role": "assistant", "content": route_analysis.destination_brief})

    # Handle clarifying questions for hard routes — pause pipeline and wait for reply
    if route_analysis.clarifying_questions:
        for q in route_analysis.clarifying_questions:
            yield ("clarify", q)
        conversation.append({"role": "assistant", "content": "Questions: " + "; ".join(route_analysis.clarifying_questions)})

        # Save pipeline state and pause — frontend will POST to /reply when user answers
        pipeline_state = {
            "step": "awaiting_clarification",
            "parsed_query": parsed_query.model_dump(mode="json"),
            "route_analysis": route_analysis.model_dump(mode="json"),
            "pending_questions": route_analysis.clarifying_questions,
            "pref_context": pref_context,
            "start_time": start_time,
        }
        await save_session(
            session_id=session_id,
            parsed_query=parsed_query.model_dump(),
            conversation=conversation,
            pipeline_state=pipeline_state,
        )

        yield ("waiting_for_input", {
            "session_id": session_id,
            "questions": route_analysis.clarifying_questions,
            "context": "route_clarification",
        })
        return  # Stream ends — pipeline resumes when user POSTs to /reply

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

    # Log search results summary
    search_duration = round(time.time() - start_time, 2)
    price_range = None
    if all_flights:
        prices = [f.price_usd for f in all_flights]
        price_range = (min(prices), max(prices))
    await interaction_logger.log_results(
        session_id, len(all_flights), sources_used, search_duration, price_range
    )

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

    # --- Step 5.5: Apply hard constraints (filter banned airlines etc.) ---
    all_flights, filter_messages = _apply_hard_constraints(all_flights)
    for msg in filter_messages:
        yield ("thinking", msg)

    # If filtering removed everything, tell the user
    if not all_flights:
        yield ("thinking", "All options were removed by your hard constraints. Try relaxing your preferences or searching different dates.")
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

    # --- Step 6: Rank with Claude ---
    yield ("ranking", f"Found {len(all_flights)} options, ranking by your preferences...")

    flights_as_dicts = [f.model_dump() for f in all_flights]

    try:
        rankings = await claude_client.rank_results(
            parsed_query.model_dump(),
            flights_as_dicts,
            parsed_query.preferences,
            preferences_context=pref_context,
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

    # Log ranking results
    await interaction_logger.log_ranking(
        session_id, [r.model_dump() for r in ranked_results]
    )

    # --- Step 8: Save session with full conversation history ---
    conversation.append({"role": "assistant", "content": f"Found {len(ranked_results)} flight options, ranked by preferences."})
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

@search_router.post("/{session_id}/refine")
async def refine_search(
    session_id: str,
    request: RefineRequest,
    req: Request,
    token: str = Depends(require_auth),
):
    """Refine an existing search conversationally. Supports SSE streaming or JSON response."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # SSE streaming version for a better UX
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _refine_stream(session_id, request.message, session),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # JSON fallback (for backward compatibility)
    current_query = session.get("parsed_query", {})
    conversation = session.get("conversation_history", [])
    pref_context = preferences_manager.to_prompt_context()

    try:
        result = await claude_client.handle_refinement(
            conversation_history=conversation,
            refinement_message=request.message,
            current_query=current_query,
            preferences_context=pref_context,
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

    # Ambient preference detection
    pref_detected = result.get("preference_detected")
    if pref_detected and isinstance(pref_detected, dict):
        content = pref_detected.get("content", "")
        category = pref_detected.get("category", "soft_preference")
        if content:
            await preferences_manager.add(content, category, "explicit", session_id)
            response.message += f" (Remembered for future searches: \"{content}\")"

    if result.get("needs_new_search") and result.get("updated_query"):
        try:
            updated = ParsedQuery(**result["updated_query"])
            response.updated_query = updated

            strategy = DirectSearchStrategy(amadeus, serpapi)
            all_flights = []
            async for event_type, message, flights in strategy.execute(updated):
                if event_type == "done":
                    all_flights = flights

            if all_flights:
                all_flights = _deduplicate_flights(all_flights)
                all_flights, _ = _apply_hard_constraints(all_flights)
                flights_as_dicts = [f.model_dump() for f in all_flights]
                pref_ctx = preferences_manager.to_prompt_context()
                rankings = await claude_client.rank_results(
                    updated.model_dump(), flights_as_dicts, updated.preferences,
                    preferences_context=pref_ctx,
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

    await interaction_logger.log_refinement(
        session_id, request.message, bool(result.get("needs_new_search"))
    )

    conversation.append({"role": "user", "content": request.message})
    conversation.append({"role": "assistant", "content": result.get("message", "")})
    await save_session(session_id=session_id, conversation=conversation)

    return response


async def _refine_stream(session_id: str, message: str, session: dict):
    """SSE streaming refinement — same pipeline as main search but with updated params."""
    try:
        start_time = time.time()
        current_query = session.get("parsed_query", {})
        conversation = session.get("conversation_history", [])
        pref_context = preferences_manager.to_prompt_context()

        yield _sse_event("thinking", "Analyzing your refinement...")

        result = await claude_client.handle_refinement(
            conversation_history=conversation,
            refinement_message=message,
            current_query=current_query,
            preferences_context=pref_context,
        )

        agent_message = result.get("message", "")
        yield _sse_event("thinking", agent_message)

        # Ambient preference detection
        pref_detected = result.get("preference_detected")
        if pref_detected and isinstance(pref_detected, dict):
            content = pref_detected.get("content", "")
            category = pref_detected.get("category", "soft_preference")
            if content:
                await preferences_manager.add(content, category, "explicit", session_id)
                yield _sse_event("thinking", f"Noted for future searches: \"{content}\"")

        if result.get("needs_new_search") and result.get("updated_query"):
            updated = ParsedQuery(**result["updated_query"])

            yield _sse_event("searching", f"Searching with updated criteria...")

            # Use appropriate strategy based on route analysis
            strategy = DirectSearchStrategy(amadeus, serpapi)
            all_flights = []
            async for event_type, msg, flights in strategy.execute(updated):
                if event_type == "done":
                    all_flights = flights
                else:
                    yield _sse_event(event_type, msg)

            if all_flights:
                all_flights = _deduplicate_flights(all_flights)
                all_flights, filter_msgs = _apply_hard_constraints(all_flights)
                for fm in filter_msgs:
                    yield _sse_event("thinking", fm)

                yield _sse_event("ranking", f"Found {len(all_flights)} options, ranking...")

                flights_as_dicts = [f.model_dump() for f in all_flights]
                rankings = await claude_client.rank_results(
                    updated.model_dump(), flights_as_dicts, updated.preferences,
                    preferences_context=pref_context,
                )

                flight_map = {f.id: f for f in all_flights}
                ranked_results = []
                for ranking in rankings:
                    flight = flight_map.get(ranking.get("flight_id", ""))
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

                sources_used = list({f.source for f in all_flights})
                duration = round(time.time() - start_time, 2)

                # Save updated session
                conversation.append({"role": "user", "content": message})
                conversation.append({"role": "assistant", "content": agent_message})
                await save_session(
                    session_id=session_id,
                    parsed_query=updated.model_dump(),
                    conversation=conversation,
                    results=[r.model_dump() for r in ranked_results],
                )

                yield _sse_json_event("results", SearchResponse(
                    session_id=session_id,
                    parsed_query=updated,
                    results=ranked_results,
                    sources_used=sources_used,
                    search_duration_seconds=duration,
                    total_options_found=len(ranked_results),
                ).model_dump(mode="json"))
            else:
                yield _sse_event("thinking", "No results found for the updated criteria.")
        else:
            # No new search needed — just a clarification or explanation
            yield _sse_event("thinking", "No new search needed for this request.")

        await interaction_logger.log_refinement(
            session_id, message, bool(result.get("needs_new_search"))
        )

    except Exception as e:
        logger.error(f"Refine stream error: {e}")
        yield _sse_event("error", f"Refinement failed: {e}")


@search_router.post("/{session_id}/reply")
async def reply_to_agent(
    session_id: str,
    request: ReplyRequest,
    req: Request,
    token: str = Depends(require_auth),
):
    """Handle user's reply to an agent question. Returns SSE stream that resumes pipeline."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    pipeline_state = session.get("pipeline_state")
    if not pipeline_state or pipeline_state.get("step") != "awaiting_clarification":
        raise HTTPException(status_code=400, detail="No pending question for this session")

    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _resume_pipeline_stream(session_id, request.message, pipeline_state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # Non-streaming fallback — collect events and return final result
        final_result = None
        async for event, data in _resume_pipeline(session_id, request.message, pipeline_state):
            if event == "results":
                final_result = data
        if final_result is None:
            raise HTTPException(status_code=500, detail="Resume produced no results")
        return SearchResponse(**final_result)


async def _resume_pipeline_stream(session_id: str, user_reply: str, state: dict):
    """SSE wrapper for the resumed pipeline."""
    try:
        async for event, data in _resume_pipeline(session_id, user_reply, state):
            if event == "results":
                yield _sse_json_event("results", data)
            elif event == "waiting_for_input":
                yield _sse_json_event("waiting_for_input", data)
            else:
                yield _sse_event(event, data)
    except Exception as e:
        logger.error(f"Resume pipeline error: {e}")
        yield _sse_event("error", f"Resume failed: {e}")


async def _resume_pipeline(session_id: str, user_reply: str, state: dict):
    """Resume the search pipeline from where it paused, incorporating the user's answer."""
    start_time = state.get("start_time", time.time())
    parsed_query = ParsedQuery(**state["parsed_query"])
    route_analysis = RouteAnalysis(**state["route_analysis"])
    pref_context = state.get("pref_context", "")
    pending_questions = state.get("pending_questions", [])

    yield ("thinking", "Got it — adjusting search based on your answer...")

    # Use Claude to interpret the user's answer
    try:
        clarification_result = await claude_client.incorporate_clarification(
            questions=pending_questions,
            user_answer=user_reply,
            preferences_context=pref_context,
        )
    except Exception as e:
        logger.error(f"Clarification processing failed: {e}")
        clarification_result = {
            "adjusted_preferences": [],
            "adjusted_max_stops": None,
            "notes_for_ranking": "",
            "summary": "Proceeding with search.",
        }

    # Apply adjustments from clarification
    summary = clarification_result.get("summary", "")
    if summary:
        yield ("thinking", summary)

    adjusted_prefs = clarification_result.get("adjusted_preferences", [])
    if adjusted_prefs:
        parsed_query.preferences = list(set(parsed_query.preferences + adjusted_prefs))

    adjusted_stops = clarification_result.get("adjusted_max_stops")
    if adjusted_stops is not None:
        parsed_query.max_stops = adjusted_stops

    ranking_notes = clarification_result.get("notes_for_ranking", "")

    # Save any detected preference
    pref_to_save = clarification_result.get("preference_to_save")
    if pref_to_save and isinstance(pref_to_save, dict) and pref_to_save.get("content"):
        await preferences_manager.add(
            pref_to_save["content"],
            pref_to_save.get("category", "soft_preference"),
            "inferred", session_id,
        )
        yield ("thinking", f"Noted for future searches: \"{pref_to_save['content']}\"")

    # --- Continue pipeline from Step 3: Execute search strategy ---
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

    # Log search results
    search_duration = round(time.time() - start_time, 2)
    price_range = None
    if all_flights:
        prices = [f.price_usd for f in all_flights]
        price_range = (min(prices), max(prices))
    await interaction_logger.log_results(
        session_id, len(all_flights), sources_used, search_duration, price_range
    )

    if not all_flights:
        yield ("thinking", "No flights found for these criteria. Try different dates or preferences.")
        yield ("results", SearchResponse(
            session_id=session_id,
            parsed_query=parsed_query,
            results=[],
            sources_used=sources_used,
            search_duration_seconds=search_duration,
            total_options_found=0,
            route_analysis=route_analysis,
        ).model_dump(mode="json"))
        return

    # Deduplicate + filter hard constraints
    all_flights = _deduplicate_flights(all_flights)
    all_flights, filter_messages = _apply_hard_constraints(all_flights)
    for msg in filter_messages:
        yield ("thinking", msg)

    if not all_flights:
        yield ("thinking", "All options removed by your hard constraints.")
        yield ("results", SearchResponse(
            session_id=session_id, parsed_query=parsed_query, results=[],
            sources_used=sources_used,
            search_duration_seconds=round(time.time() - start_time, 2),
            total_options_found=0, route_analysis=route_analysis,
        ).model_dump(mode="json"))
        return

    # Rank
    yield ("ranking", f"Found {len(all_flights)} options, ranking by your preferences...")

    # Include ranking notes from clarification
    ranking_pref_context = pref_context
    if ranking_notes:
        ranking_pref_context += f"\n\nADDITIONAL CONTEXT FROM USER CONVERSATION:\n{ranking_notes}"

    flights_as_dicts = [f.model_dump() for f in all_flights]
    try:
        rankings = await claude_client.rank_results(
            parsed_query.model_dump(), flights_as_dicts, parsed_query.preferences,
            preferences_context=ranking_pref_context,
        )
    except Exception as e:
        logger.error(f"Ranking failed: {e}")
        rankings = [
            {"rank": i + 1, "flight_id": f.id, "explanation": "Sorted by price", "tags": []}
            for i, f in enumerate(sorted(all_flights, key=lambda x: x.price_usd))
        ]

    # Build ranked results
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

    await interaction_logger.log_ranking(session_id, [r.model_dump() for r in ranked_results])

    # Save session with full conversation history (clear pipeline state since we're done)
    # Load existing conversation from session and extend it
    existing_session = await get_session(session_id)
    conversation = existing_session.get("conversation_history", []) if existing_session else []
    # Append the Q&A exchange and results
    conversation.append({"role": "user", "content": user_reply})
    conversation.append({"role": "assistant", "content": summary or "Search adjusted based on your answer."})
    conversation.append({"role": "assistant", "content": f"Found {len(ranked_results)} flight options."})
    await save_session(
        session_id=session_id,
        parsed_query=parsed_query.model_dump(),
        conversation=conversation,
        results=[r.model_dump() for r in ranked_results],
        pipeline_state={},  # Clear pipeline state
    )

    duration = round(time.time() - start_time, 2)
    yield ("results", SearchResponse(
        session_id=session_id,
        parsed_query=parsed_query,
        results=ranked_results,
        sources_used=sources_used,
        search_duration_seconds=duration,
        total_options_found=len(ranked_results),
        route_analysis=route_analysis,
    ).model_dump(mode="json"))


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


def _apply_hard_constraints(flights: list[FlightOption]) -> tuple[list[FlightOption], list[str]]:
    """Remove flights that violate hard constraint preferences.
    Returns (filtered_flights, messages_explaining_what_was_removed).
    Hard constraints are absolute — matching flights are removed entirely, not just ranked lower.
    """
    active_prefs = preferences_manager.get_active()
    hard = [p for p in active_prefs if p["category"] == "hard_constraint" and p.get("active", True)]
    if not hard:
        return flights, []

    messages = []
    filtered = flights

    for constraint in hard:
        content_lower = constraint["content"].lower()
        # Detect airline exclusion patterns
        exclusion_keywords = ["never fly", "never book", "no ", "avoid ", "don't fly",
                              "don't book", "exclude ", "not ", "without "]
        if any(kw in content_lower for kw in exclusion_keywords):
            before_count = len(filtered)
            # Log which flights match for debugging
            for f in filtered:
                all_airlines = list(f.airline_names) + list(f.return_airline_names or [])
                seg_airlines = [s.airline for s in f.segments] + [s.airline for s in (f.return_segments or [])]
                matches = _flight_matches_airline_constraint(f, content_lower)
                if matches:
                    logger.info(f"Hard constraint MATCH: '{constraint['content']}' → removing flight with airlines {all_airlines}, segments {seg_airlines}")
            filtered = [f for f in filtered if not _flight_matches_airline_constraint(f, content_lower)]
            removed = before_count - len(filtered)
            if removed > 0:
                messages.append(f"Removed {removed} options matching your rule: \"{constraint['content']}\"")
            else:
                logger.info(f"Hard constraint '{constraint['content']}' matched 0 of {before_count} flights. Airlines in results: {[list(f.airline_names) + list(f.return_airline_names or []) for f in filtered]}")

    return filtered, messages


def _flight_matches_airline_constraint(flight: FlightOption, constraint_lower: str) -> bool:
    """Check if any airline in the flight matches an exclusion constraint.

    Checks ALL legs (outbound + return) and uses bidirectional substring matching
    with fuzzy suffix stripping (e.g., "air india" matches "air india express").
    """
    def _name_matches(name_lower: str) -> bool:
        """Check if an airline name matches the constraint text."""
        if not name_lower:
            return False
        # Direct substring: "air india" in "never fly air india"
        if name_lower in constraint_lower:
            return True
        # Constraint name in airline: constraint has "air india", airline is "air india express"
        # Extract the airline-like words from the constraint
        # Fuzzy: strip common suffixes and check again
        for suffix in [" airlines", " airways", " air", " express", " limited"]:
            if name_lower.endswith(suffix):
                base = name_lower[:-len(suffix)].strip()
                if len(base) > 2 and base in constraint_lower:
                    return True
        return False

    # Check outbound airline names (e.g., ["ETHIOPIAN AIRLINES", "AIR INDIA"])
    for name in flight.airline_names:
        if _name_matches(name.lower()):
            return True

    # Check return airline names (round-trip return legs)
    for name in (flight.return_airline_names or []):
        if _name_matches(name.lower()):
            return True

    # Check individual outbound segments (codeshare legs might not be in airline_names)
    for seg in flight.segments:
        if _name_matches(seg.airline.lower()):
            return True

    # Check individual return segments
    for seg in (flight.return_segments or []):
        if _name_matches(seg.airline.lower()):
            return True

    return False


def _deduplicate_flights(flights: list[FlightOption]) -> list[FlightOption]:
    """Remove duplicate flights across providers and search strategies."""
    seen = set()
    unique = []

    for flight in flights:
        segments_key = tuple(
            (s.departure_airport, s.arrival_airport, s.airline_code, s.flight_number)
            for s in flight.segments
        )
        # Include return segments in fingerprint for round-trip dedup
        return_key = tuple(
            (s.departure_airport, s.arrival_airport, s.airline_code, s.flight_number)
            for s in (flight.return_segments or [])
        )
        price_bucket = round(flight.price_usd / 10) * 10
        fingerprint = (segments_key, return_key, price_bucket)

        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(flight)

    if len(flights) != len(unique):
        logger.info(f"Deduplicated {len(flights)} → {len(unique)} flights")

    return unique
