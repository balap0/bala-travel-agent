# Search orchestrator — coordinates the full flow:
# NL query → Claude parse → Amadeus + SerpAPI search → Claude rank → response
# This is the skeleton; full implementation in Sprint 2.

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth.middleware import require_auth
from models.schemas import (
    SearchRequest, SearchResponse, RefineRequest, RefineResponse,
    ParsedQuery, RankedResult, ErrorResponse,
)
from models.database import save_session, get_session

search_router = APIRouter()


@search_router.post("", response_model=SearchResponse)
async def search_flights(request: SearchRequest, token: str = Depends(require_auth)):
    """
    Main search endpoint. Accepts a natural language query, parses it,
    searches flight APIs, ranks results, and returns explained options.
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    # TODO Sprint 2: Replace with real implementation
    # Step 1: Claude parses NL query → ParsedQuery
    # Step 2: Search Amadeus (primary) + SerpAPI (fallback) in parallel
    # Step 3: Merge and deduplicate results
    # Step 4: Claude ranks and explains
    # Step 5: Save session and return

    # Placeholder response for skeleton verification
    return SearchResponse(
        session_id=session_id,
        parsed_query=ParsedQuery(
            origin="BLR",
            destination="NBO",
            departure_date="2026-09-04",
            cabin_class="BUSINESS",
            max_stops=2,
            adults=1,
            preferences=["minimize_time"],
            raw_query=request.query,
        ),
        results=[],
        sources_used=[],
        search_duration_seconds=round(time.time() - start_time, 2),
        total_options_found=0,
    )


@search_router.post("/{session_id}/refine", response_model=RefineResponse)
async def refine_search(
    session_id: str,
    request: RefineRequest,
    token: str = Depends(require_auth),
):
    """
    Refine an existing search conversationally.
    E.g., "What about a day later?" or "Show me economy options".
    """
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # TODO Sprint 2: Implement conversational refinement
    return RefineResponse(
        session_id=session_id,
        message="Refinement not yet implemented. Coming in Sprint 2.",
    )


@search_router.get("/{session_id}", response_model=SearchResponse)
async def get_search_results(session_id: str, token: str = Depends(require_auth)):
    """Retrieve results from a previous search session."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # TODO Sprint 2: Return cached results from session
    raise HTTPException(status_code=501, detail="Not yet implemented")
