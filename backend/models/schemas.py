# Pydantic models for API request/response contracts and internal data structures

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


# --- Request Models ---

class LoginRequest(BaseModel):
    password: str


class SearchRequest(BaseModel):
    """Natural language flight search request."""
    query: str = Field(..., min_length=5, max_length=2000, description="Natural language travel query")
    session_id: Optional[str] = Field(None, description="Existing session for conversation continuity")


class RefineRequest(BaseModel):
    """Follow-up refinement to an existing search."""
    message: str = Field(..., min_length=2, max_length=1000, description="Conversational refinement")


class ReplyRequest(BaseModel):
    """User's reply to an agent question during the search conversation."""
    message: str = Field(..., min_length=1, max_length=2000, description="Reply to agent's question")


# --- Internal Models (Claude parse output) ---

class ParsedQuery(BaseModel):
    """Structured flight search params extracted by Claude from natural language."""
    origin: str = Field(..., description="IATA airport code (e.g., BLR)")
    destination: str = Field(..., description="IATA airport code (e.g., NBO)")
    departure_date: date
    return_date: Optional[date] = None
    flexible_days: int = Field(default=2, description="Days of flexibility around departure date")
    cabin_class: str = Field(default="ECONOMY", description="ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST")
    max_stops: int = Field(default=2, description="Maximum number of stops")
    adults: int = Field(default=1, ge=1, le=9)
    preferences: list[str] = Field(default_factory=list, description="User priorities like minimize_time, cheapest, reliable_airline")
    raw_query: str = Field(..., description="Original natural language text")
    clarification_needed: Optional[str] = Field(None, description="If query is ambiguous, what to ask the user")


# --- Flight Data Models ---

class FlightSegment(BaseModel):
    """A single leg of a flight (e.g., BLR -> ADD)."""
    airline: str
    airline_code: str
    flight_number: str
    departure_airport: str
    departure_time: datetime
    arrival_airport: str
    arrival_time: datetime
    duration_minutes: int
    aircraft: Optional[str] = None
    cabin_class: str = "ECONOMY"


class LayoverDetail(BaseModel):
    """Layover information between segments."""
    airport: str
    airport_name: Optional[str] = None
    duration_minutes: int
    overnight: bool = False


class FlightOption(BaseModel):
    """A complete flight itinerary (possibly multi-segment, one-way or round-trip)."""
    id: str
    source: str = Field(..., description="Data source: amadeus or serpapi")
    segments: list[FlightSegment]
    total_duration_minutes: int
    num_stops: int
    layovers: list[LayoverDetail] = Field(default_factory=list)
    price_usd: float
    cabin_class: str
    airline_names: list[str]
    baggage_info: Optional[dict] = None
    co2_emissions_kg: Optional[float] = None
    booking_links: Optional[list[str]] = None
    fare_brand: Optional[str] = None
    # Round-trip fields
    trip_type: str = Field(default="one_way", description="one_way or round_trip")
    return_segments: list[FlightSegment] = Field(default_factory=list)
    return_layovers: list[LayoverDetail] = Field(default_factory=list)
    return_duration_minutes: int = Field(default=0)
    return_airline_names: list[str] = Field(default_factory=list)


class RankedResult(BaseModel):
    """A flight option with AI-generated ranking and explanation."""
    rank: int
    flight: FlightOption
    explanation: str = Field(..., description="Claude's reasoning for this ranking position")
    tags: list[str] = Field(default_factory=list, description="Labels like recommended, cheapest, fastest")


# --- Response Models ---

class LoginResponse(BaseModel):
    token: str
    message: str = "Authenticated"


class SearchResponse(BaseModel):
    """Full search response with ranked, explained results."""
    session_id: str
    parsed_query: ParsedQuery
    results: list[RankedResult]
    sources_used: list[str]
    search_duration_seconds: float
    total_options_found: int
    route_analysis: Optional["RouteAnalysis"] = None


class RefineResponse(BaseModel):
    """Response to a conversational refinement."""
    session_id: str
    message: str = Field(..., description="Claude's response to the refinement")
    updated_query: Optional[ParsedQuery] = None
    results: Optional[list[RankedResult]] = None


class ErrorResponse(BaseModel):
    """Standardized error response."""
    error: str
    detail: Optional[str] = None


# --- Route Analysis Models (Phase 1: Strategic Search) ---

class RouteAnalysis(BaseModel):
    """Claude's strategic analysis of a route before any flight API calls."""
    difficulty: str = Field(..., description="trivial, standard, challenging, or exotic")
    strategy: str = Field(..., description="direct_search or hub_based")
    connecting_hubs: list[str] = Field(default_factory=list, description="IATA codes of recommended connecting hubs")
    recommended_airlines: list[str] = Field(default_factory=list, description="Airlines likely to serve this route")
    destination_brief: str = Field(default="", description="Key travel context about the destination")
    clarifying_questions: list[str] = Field(default_factory=list, description="Questions to ask for hard routes")
    reasoning: str = Field(default="", description="Why this strategy was chosen — shown to user")


class SSEEvent(BaseModel):
    """A single Server-Sent Event during the search pipeline."""
    event: str = Field(..., description="Event type: thinking, strategy, clarify, searching, ranking, results, error")
    data: str = Field(..., description="Event payload — natural language message or JSON for results")
