# Hub-based search strategy — for challenging and exotic routes
# Searches via connecting hubs identified by route analysis, PLUS a direct search

import asyncio
import logging
from typing import AsyncGenerator

from models.schemas import ParsedQuery, FlightOption, RouteAnalysis

logger = logging.getLogger(__name__)

# Max hubs to search via (each hub = 1 Amadeus API call)
MAX_HUBS = 3


class HubBasedSearchStrategy:
    """
    Strategic search for hard-to-reach destinations.

    For a route like BLR→LBV with hubs [ADD, IST, CDG]:
    1. Always run direct BLR→LBV search (Amadeus may have through-ticketed options)
    2. For each hub, search BLR→LBV via that hub using Amadeus
       (Amadeus often returns multi-leg itineraries that route through these hubs)
    3. Merge all results

    We do NOT stitch separate one-way legs together — that creates pricing and
    connection-protection issues. Instead we rely on Amadeus returning through-ticketed
    multi-segment itineraries that naturally route through these hubs.
    """

    def __init__(self, amadeus, serpapi, route_analysis: RouteAnalysis):
        self.amadeus = amadeus
        self.serpapi = serpapi
        self.route_analysis = route_analysis

    async def execute(self, query: ParsedQuery) -> AsyncGenerator[tuple[str, str, list[FlightOption]], None]:
        """
        Execute hub-based search. Yields (event_type, message, flights) tuples.
        """
        hubs = self.route_analysis.connecting_hubs[:MAX_HUBS]
        airlines = self.route_analysis.recommended_airlines

        hub_names = ", ".join(hubs) if hubs else "various hubs"
        airline_names = ", ".join(airlines[:3]) if airlines else "available airlines"

        yield (
            "searching",
            f"This is a {self.route_analysis.difficulty} route. "
            f"Searching via {hub_names} ({airline_names})...",
            [],
        )

        all_flights: list[FlightOption] = []

        # Run direct search + hub-aware searches in parallel
        # For the direct search, we just search the original route
        # For hub-aware searches, we still search the same origin→destination
        # but we increase max_stops to ensure Amadeus returns connecting options
        search_tasks = []

        # Task 1: Direct search (original query as-is)
        search_tasks.append(self._search_direct(query))

        # Task 2: Search with relaxed stops to capture hub connections
        # If user specified max_stops=0 (nonstop only), bump to 1 for hub search
        if query.max_stops < 2:
            relaxed_query = query.model_copy(update={"max_stops": 2})
            search_tasks.append(self._search_relaxed(relaxed_query))

        # Task 3: SerpAPI as additional source (Google Flights may find options Amadeus misses)
        search_tasks.append(self._search_serpapi(query))

        # Run all searches in parallel
        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Hub search task failed: {result}")
                continue
            if isinstance(result, list):
                all_flights.extend(result)

        # Report per-hub results
        hub_flights = {}
        for flight in all_flights:
            if flight.layovers:
                for layover in flight.layovers:
                    hub_code = layover.airport
                    if hub_code in hubs:
                        hub_flights.setdefault(hub_code, 0)
                        hub_flights[hub_code] += 1

        for hub, count in hub_flights.items():
            yield ("searching", f"Found {count} options via {hub}", [])

        non_hub = len(all_flights) - sum(hub_flights.values())
        if non_hub > 0:
            yield ("searching", f"Found {non_hub} additional direct/other options", [])

        yield ("done", f"Found {len(all_flights)} total options across all routes", all_flights)

    async def _search_direct(self, query: ParsedQuery) -> list[FlightOption]:
        """Direct origin→destination search via Amadeus."""
        try:
            results = await self.amadeus.search(query)
            logger.info(f"Direct search: {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Direct search failed: {e}")
            return []

    async def _search_relaxed(self, query: ParsedQuery) -> list[FlightOption]:
        """Search with relaxed stops to capture more connection options."""
        try:
            results = await self.amadeus.search(query)
            logger.info(f"Relaxed search (max_stops=2): {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Relaxed search failed: {e}")
            return []

    async def _search_serpapi(self, query: ParsedQuery) -> list[FlightOption]:
        """SerpAPI/Google Flights search as additional source."""
        try:
            results = await self.serpapi.search(query)
            logger.info(f"SerpAPI search: {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"SerpAPI search failed: {e}")
            return []
