# Amadeus flight search provider — wraps the Amadeus Self-Service API
# Implements the FlightProvider interface for the search orchestrator

from providers.base import FlightProvider
from models.schemas import ParsedQuery, FlightOption
from config import get_settings


class AmadeusProvider(FlightProvider):
    """Amadeus Self-Service API flight search provider."""

    def __init__(self):
        self._client = None

    @property
    def name(self) -> str:
        return "amadeus"

    async def _get_client(self):
        """Lazy-init the Amadeus client (it manages its own OAuth tokens)."""
        if self._client is None:
            from amadeus import Client
            settings = get_settings()
            self._client = Client(
                client_id=settings.amadeus_client_id,
                client_secret=settings.amadeus_client_secret,
            )
        return self._client

    async def search(self, query: ParsedQuery) -> list[FlightOption]:
        """
        Search Amadeus Flight Offers for the given query.
        TODO Sprint 2: Full implementation with response parsing.
        """
        # Placeholder — will be implemented in Sprint 2
        return []

    async def is_available(self) -> bool:
        """Check if Amadeus credentials are configured."""
        settings = get_settings()
        return bool(settings.amadeus_client_id and settings.amadeus_client_secret)
