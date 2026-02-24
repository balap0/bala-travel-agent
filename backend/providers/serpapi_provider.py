# SerpAPI (Google Flights) provider — searches via Google Flights scraping
# Used as fallback when Amadeus returns few results, or for broader coverage

import asyncio
import hashlib
import logging
from datetime import datetime

from serpapi import GoogleSearch

from providers.base import FlightProvider
from models.schemas import ParsedQuery, FlightOption, FlightSegment, LayoverDetail
from config import get_settings

logger = logging.getLogger(__name__)

# Map our cabin class names to SerpAPI's travel_class parameter values
CABIN_MAP = {
    "ECONOMY": "1",
    "PREMIUM_ECONOMY": "2",
    "BUSINESS": "3",
    "FIRST": "4",
}


class SerpAPIProvider(FlightProvider):
    """SerpAPI Google Flights search provider."""

    @property
    def name(self) -> str:
        return "serpapi"

    async def search(self, query: ParsedQuery) -> list[FlightOption]:
        """Search Google Flights via SerpAPI."""
        if not await self.is_available():
            logger.warning("SerpAPI key not configured, skipping")
            return []

        try:
            results = await asyncio.to_thread(self._search_sync, query)
            return results
        except Exception as e:
            logger.error(f"SerpAPI search failed: {e}")
            return []

    def _search_sync(self, query: ParsedQuery) -> list[FlightOption]:
        """Synchronous search — runs in thread pool."""
        settings = get_settings()

        params = {
            "engine": "google_flights",
            "departure_id": query.origin,
            "arrival_id": query.destination,
            "outbound_date": query.departure_date.isoformat(),
            "type": "2",  # One-way
            "travel_class": CABIN_MAP.get(query.cabin_class, "1"),
            "adults": query.adults,
            "currency": "USD",
            "hl": "en",
            "api_key": settings.serpapi_api_key,
        }

        # Add stop filter
        if query.max_stops == 0:
            params["stops"] = "1"  # SerpAPI: 1=nonstop
        elif query.max_stops == 1:
            params["stops"] = "2"  # 2 = 1 stop or fewer

        try:
            search = GoogleSearch(params)
            results = search.get_dict()

            if "error" in results:
                logger.error(f"SerpAPI error: {results['error']}")
                return []

            flights = []

            # Parse both "best_flights" and "other_flights" from Google
            for category in ["best_flights", "other_flights"]:
                for flight_data in results.get(category, []):
                    try:
                        flight = self._parse_flight(flight_data, query)
                        if flight:
                            flights.append(flight)
                    except Exception as e:
                        logger.warning(f"Failed to parse SerpAPI flight: {e}")

            logger.info(f"SerpAPI returned {len(flights)} parsed results")
            return flights

        except Exception as e:
            logger.error(f"SerpAPI request failed: {e}")
            return []

    def _parse_flight(self, flight_data: dict, query: ParsedQuery) -> FlightOption | None:
        """Parse a single SerpAPI flight result into our FlightOption model."""
        try:
            legs = flight_data.get("flights", [])
            if not legs:
                return None

            flight_id = f"serp_{hashlib.md5(str(flight_data).encode()).hexdigest()[:8]}"

            segments = []
            airline_names = set()

            for leg in legs:
                airline = leg.get("airline", "Unknown")
                airline_names.add(airline)

                dep_info = leg.get("departure_airport", {})
                arr_info = leg.get("arrival_airport", {})

                segments.append(FlightSegment(
                    airline=airline,
                    airline_code=leg.get("airline_logo", "")[-6:-4].upper() if leg.get("airline_logo") else "",
                    flight_number=leg.get("flight_number", ""),
                    departure_airport=dep_info.get("id", query.origin),
                    departure_time=self._parse_time(dep_info.get("time", "")),
                    arrival_airport=arr_info.get("id", query.destination),
                    arrival_time=self._parse_time(arr_info.get("time", "")),
                    duration_minutes=leg.get("duration", 0),
                    aircraft=leg.get("airplane"),
                    cabin_class=leg.get("travel_class", query.cabin_class),
                ))

            # Parse layovers
            layovers = [
                LayoverDetail(
                    airport=lo.get("id", lo.get("name", "?")),
                    airport_name=lo.get("name"),
                    duration_minutes=lo.get("duration", 0),
                    overnight=lo.get("overnight", False),
                )
                for lo in flight_data.get("layovers", [])
            ]

            price = float(flight_data.get("price", 0))
            total_duration = flight_data.get("total_duration", 0)

            # Carbon emissions (SerpAPI returns grams)
            co2 = None
            carbon = flight_data.get("carbon_emissions", {})
            if carbon and carbon.get("this_flight"):
                co2 = float(carbon["this_flight"]) / 1000  # grams → kg

            return FlightOption(
                id=flight_id,
                source="serpapi",
                segments=segments,
                total_duration_minutes=total_duration,
                num_stops=len(segments) - 1,
                layovers=layovers,
                price_usd=price,
                cabin_class=query.cabin_class,
                airline_names=list(airline_names),
                co2_emissions_kg=co2,
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error parsing SerpAPI flight: {e}")
            return None

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        """Parse SerpAPI time strings (formats vary)."""
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(time_str, fmt)
            except (ValueError, TypeError):
                continue
        return datetime.now()

    async def is_available(self) -> bool:
        """Check if SerpAPI key is configured."""
        settings = get_settings()
        return bool(settings.serpapi_api_key)
