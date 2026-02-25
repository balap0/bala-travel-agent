# Direct search strategy — used for trivial and standard routes
# This is the original search behavior: query Amadeus, fallback to SerpAPI

import logging
from typing import AsyncGenerator

from models.schemas import ParsedQuery, FlightOption

logger = logging.getLogger(__name__)

AMADEUS_MIN_RESULTS = 3


class DirectSearchStrategy:
    """Standard search: Amadeus first, SerpAPI as fallback if few results."""

    def __init__(self, amadeus, serpapi):
        self.amadeus = amadeus
        self.serpapi = serpapi

    async def execute(self, query: ParsedQuery) -> AsyncGenerator[tuple[str, str, list[FlightOption]], None]:
        """
        Execute direct search. Yields (event_type, message, flights) tuples
        so the orchestrator can stream progress to the client.
        """
        all_flights: list[FlightOption] = []
        sources: list[str] = []

        # Search Amadeus
        yield ("searching", f"Searching flights {query.origin} → {query.destination}...", [])

        amadeus_results = await self.amadeus.search(query)
        if amadeus_results:
            all_flights.extend(amadeus_results)
            sources.append("amadeus")
            logger.info(f"Amadeus returned {len(amadeus_results)} results")
            yield ("searching", f"Found {len(amadeus_results)} options from Amadeus", [])

        # SerpAPI fallback if few Amadeus results
        if len(amadeus_results) < AMADEUS_MIN_RESULTS:
            yield ("searching", "Checking additional sources...", [])
            serpapi_results = await self.serpapi.search(query)
            if serpapi_results:
                all_flights.extend(serpapi_results)
                sources.append("serpapi")
                logger.info(f"SerpAPI returned {len(serpapi_results)} results")
                yield ("searching", f"Found {len(serpapi_results)} more options from Google Flights", [])

        yield ("done", f"Found {len(all_flights)} total options", all_flights)
