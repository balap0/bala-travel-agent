# SerpAPI (Google Flights) provider — scrapes Google Flights via SerpAPI
# Used as fallback/enrichment when Amadeus returns few results

from providers.base import FlightProvider
from models.schemas import ParsedQuery, FlightOption
from config import get_settings


class SerpAPIProvider(FlightProvider):
    """SerpAPI Google Flights search provider."""

    @property
    def name(self) -> str:
        return "serpapi"

    async def search(self, query: ParsedQuery) -> list[FlightOption]:
        """
        Search Google Flights via SerpAPI.
        TODO Sprint 2: Full implementation with response parsing.
        """
        # Placeholder — will be implemented in Sprint 2
        return []

    async def is_available(self) -> bool:
        """Check if SerpAPI key is configured."""
        settings = get_settings()
        return bool(settings.serpapi_api_key)
