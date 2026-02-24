# Abstract base for flight data providers
# Each provider (Amadeus, SerpAPI) implements this interface

from abc import ABC, abstractmethod
from models.schemas import ParsedQuery, FlightOption


class FlightProvider(ABC):
    """Base class for flight search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'amadeus', 'serpapi')."""
        ...

    @abstractmethod
    async def search(self, query: ParsedQuery) -> list[FlightOption]:
        """
        Search for flights matching the parsed query.
        Returns a list of FlightOption objects.
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        ...
