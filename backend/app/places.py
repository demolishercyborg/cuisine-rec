"""Google Places (New) Text Search client."""
from __future__ import annotations

import httpx

from .config import get_settings

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

# Field mask sets both the response shape and the billing tier.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.currentOpeningHours",
        "places.regularOpeningHours",
        "places.googleMapsUri",
        "places.editorialSummary",
        "places.reviews",
        "places.types",
    ]
)


async def search_cuisine(
    client, cuisine, lat, lng, radius_m, limit, dietary=None, dish_query=None
):
    settings = get_settings()
    diet_prefix = (" ".join(dietary) + " ") if dietary else ""
    if dish_query:
        text_query = f"{diet_prefix}{dish_query}"
    else:
        text_query = f"{diet_prefix}{cuisine} restaurant"
    body = {
        "textQuery": text_query,
        "includedType": "restaurant",
        "maxResultCount": limit,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius_m),
            }
        },
        "rankPreference": "RELEVANCE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    resp = await client.post(PLACES_URL, json=body, headers=headers, timeout=15.0)
    resp.raise_for_status()
    return resp.json().get("places", [])
