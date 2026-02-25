# Amadeus flight search provider — wraps the Amadeus Self-Service API
# Parses the complex Amadeus response into our FlightOption model

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta

from providers.base import FlightProvider
from models.schemas import ParsedQuery, FlightOption, FlightSegment, LayoverDetail
from config import get_settings

logger = logging.getLogger(__name__)


class AmadeusProvider(FlightProvider):
    """Amadeus Self-Service API flight search provider."""

    def __init__(self):
        self._client = None

    @property
    def name(self) -> str:
        return "amadeus"

    def _get_client(self):
        """Lazy-init the Amadeus client (it manages its own OAuth tokens)."""
        if self._client is None:
            from amadeus import Client, ResponseError
            settings = get_settings()
            self._client = Client(
                client_id=settings.amadeus_client_id,
                client_secret=settings.amadeus_client_secret,
            )
        return self._client

    async def search(self, query: ParsedQuery) -> list[FlightOption]:
        """
        Search Amadeus Flight Offers Search API.
        Searches the primary date + flexible dates in parallel.
        Returns parsed FlightOption objects.
        """
        if not await self.is_available():
            logger.warning("Amadeus credentials not configured, skipping")
            return []

        try:
            # Run the synchronous Amadeus SDK call in a thread pool
            results = await asyncio.to_thread(self._search_sync, query)
            return results
        except Exception as e:
            logger.error(f"Amadeus search failed: {e}")
            return []

    def _search_sync(self, query: ParsedQuery) -> list[FlightOption]:
        """Synchronous search — runs in thread pool via asyncio.to_thread."""
        from amadeus import ResponseError
        client = self._get_client()

        try:
            # Build search parameters
            params = {
                "originLocationCode": query.origin,
                "destinationLocationCode": query.destination,
                "departureDate": query.departure_date.isoformat(),
                "adults": query.adults,
                "max": 20,  # Cap results to stay within free tier
            }

            # Round-trip: add return date if user requested it
            if query.return_date:
                params["returnDate"] = query.return_date.isoformat()

            # Add cabin class if not economy (Amadeus default is all classes)
            if query.cabin_class and query.cabin_class != "ECONOMY":
                params["travelClass"] = query.cabin_class

            # Add max stops filter
            if query.max_stops == 0:
                params["nonStop"] = "true"

            response = client.shopping.flight_offers_search.get(**params)

            if not response.data:
                logger.info(f"Amadeus returned 0 results for {query.origin}->{query.destination}")
                return []

            # Parse the dictionaries data from response
            dictionaries = getattr(response, 'result', {}).get('dictionaries', {})

            flights = []
            for offer in response.data:
                try:
                    flight = self._parse_offer(offer, dictionaries)
                    if flight:
                        flights.append(flight)
                except Exception as e:
                    logger.warning(f"Failed to parse Amadeus offer: {e}")
                    continue

            logger.info(f"Amadeus returned {len(flights)} parsed results")
            return flights

        except ResponseError as e:
            logger.error(f"Amadeus API error: {e.response.status_code} - {e.response.body}")
            return []

    def _parse_itinerary(self, itinerary: dict, offer: dict, dictionaries: dict,
                         segment_offset: int = 0) -> tuple[list[FlightSegment], list[LayoverDetail], set[str], str, int]:
        """Parse a single itinerary (outbound or return) from an Amadeus offer.
        Returns (segments, layovers, airline_names_set, cabin_class, total_duration_minutes).
        segment_offset: index offset for fare_details lookup (0 for outbound, N for return).
        """
        segments_data = itinerary.get("segments", [])
        if not segments_data:
            return [], [], set(), "ECONOMY", 0

        segments = []
        airline_names = set()
        cabin_class = "ECONOMY"

        for i, seg in enumerate(segments_data):
            carrier_code = seg.get("carrierCode", "")
            carriers = dictionaries.get("carriers", {})
            airline_name = carriers.get(carrier_code, carrier_code)
            airline_names.add(airline_name)

            dep_time = datetime.fromisoformat(seg["departure"]["at"])
            arr_time = datetime.fromisoformat(seg["arrival"]["at"])
            duration_minutes = self._parse_duration(seg.get("duration", "PT0H0M"))

            traveler_pricings = offer.get("travelerPricings", [])
            if traveler_pricings:
                fare_details = traveler_pricings[0].get("fareDetailsBySegment", [])
                fare_idx = segment_offset + i
                if fare_idx < len(fare_details):
                    cabin_class = fare_details[fare_idx].get("cabin", "ECONOMY")

            aircraft_code = seg.get("aircraft", {}).get("code", "")
            aircraft_dict = dictionaries.get("aircraft", {})
            aircraft = aircraft_dict.get(aircraft_code, aircraft_code) if aircraft_code else None

            segments.append(FlightSegment(
                airline=airline_name,
                airline_code=carrier_code,
                flight_number=f"{carrier_code}{seg.get('number', '')}",
                departure_airport=seg["departure"]["iataCode"],
                departure_time=dep_time,
                arrival_airport=seg["arrival"]["iataCode"],
                arrival_time=arr_time,
                duration_minutes=duration_minutes,
                aircraft=aircraft,
                cabin_class=cabin_class,
            ))

        layovers = []
        for i in range(len(segments) - 1):
            arr = segments[i].arrival_time
            dep = segments[i + 1].departure_time
            layover_minutes = int((dep - arr).total_seconds() / 60)
            overnight = arr.date() != dep.date()
            layovers.append(LayoverDetail(
                airport=segments[i].arrival_airport,
                duration_minutes=layover_minutes,
                overnight=overnight,
            ))

        total_duration = self._parse_duration(itinerary.get("duration", "PT0H0M"))
        return segments, layovers, airline_names, cabin_class, total_duration

    def _parse_offer(self, offer: dict, dictionaries: dict) -> FlightOption | None:
        """Parse a single Amadeus flight offer into our FlightOption model.
        Handles both one-way (1 itinerary) and round-trip (2 itineraries).
        """
        try:
            offer_id = f"ama_{offer.get('id', hashlib.md5(str(offer).encode()).hexdigest()[:8])}"
            price_data = offer.get("price", {})
            price_usd = float(price_data.get("grandTotal", price_data.get("total", 0)))

            itineraries = offer.get("itineraries", [])
            if not itineraries:
                return None

            # Parse outbound itinerary
            segments, layovers, airline_names, cabin_class, total_duration = \
                self._parse_itinerary(itineraries[0], offer, dictionaries, segment_offset=0)

            if not segments:
                return None

            # Parse return itinerary if present (round-trip)
            return_segments = []
            return_layovers = []
            return_airline_names = set()
            return_duration = 0
            trip_type = "one_way"

            if len(itineraries) > 1:
                trip_type = "round_trip"
                outbound_seg_count = len(itineraries[0].get("segments", []))
                return_segments, return_layovers, return_airline_names, _, return_duration = \
                    self._parse_itinerary(itineraries[1], offer, dictionaries,
                                          segment_offset=outbound_seg_count)

            # Combine all airline names (outbound + return) for filtering
            all_airlines = airline_names | return_airline_names

            # Get fare brand if available
            fare_brand = None
            traveler_pricings = offer.get("travelerPricings", [])
            if traveler_pricings:
                fare_details = traveler_pricings[0].get("fareDetailsBySegment", [])
                if fare_details:
                    fare_brand = fare_details[0].get("brandedFare")

            # CO2 emissions if available
            co2 = None
            if "co2Emissions" in offer:
                co2_list = offer.get("co2Emissions", [])
                if co2_list:
                    co2 = float(co2_list[0].get("weight", 0))

            return FlightOption(
                id=offer_id,
                source="amadeus",
                segments=segments,
                total_duration_minutes=total_duration,
                num_stops=len(segments) - 1,
                layovers=layovers,
                price_usd=price_usd,
                cabin_class=cabin_class,
                airline_names=list(all_airlines),
                co2_emissions_kg=co2,
                fare_brand=fare_brand,
                trip_type=trip_type,
                return_segments=return_segments,
                return_layovers=return_layovers,
                return_duration_minutes=return_duration,
                return_airline_names=list(return_airline_names),
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error parsing Amadeus offer: {e}")
            return None

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse ISO 8601 duration (e.g., 'PT4H30M') to minutes."""
        if not duration_str or not duration_str.startswith("PT"):
            return 0
        duration_str = duration_str[2:]  # Remove 'PT'
        hours = 0
        minutes = 0
        if "H" in duration_str:
            h_part, duration_str = duration_str.split("H")
            hours = int(h_part)
        if "M" in duration_str:
            m_part = duration_str.replace("M", "")
            if m_part:
                minutes = int(m_part)
        return hours * 60 + minutes

    async def is_available(self) -> bool:
        """Check if Amadeus credentials are configured."""
        settings = get_settings()
        return bool(settings.amadeus_client_id and settings.amadeus_client_secret)
