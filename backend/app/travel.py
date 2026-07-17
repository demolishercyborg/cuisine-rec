"""Real drive + walk times via Google Routes API (computeRouteMatrix)."""
from __future__ import annotations

import asyncio

import httpx

from .config import get_settings

_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
_FIELD_MASK = "originIndex,destinationIndex,duration,status"
_WALK_THRESHOLD_MI = 1.5


def _parse_seconds(raw: list[dict], n: int) -> list[int | None]:
    """Extract duration seconds keyed by destinationIndex; None on missing/error."""
    out: list[int | None] = [None] * n
    for row in raw:
        if row.get("status", {}).get("code", 0) != 0:
            continue
        idx = row.get("destinationIndex")
        dur = row.get("duration", "")
        if idx is None or not dur:
            continue
        try:
            # duration is a string like "412s"
            out[idx] = int(str(dur).rstrip("s"))
        except (ValueError, TypeError):
            pass
    return out


async def _fetch_mode(
    client: httpx.AsyncClient,
    key: str,
    origin: dict,
    destinations: list[dict],
    mode: str,
) -> list[int | None]:
    body = {
        "origins": [{"waypoint": origin}],
        "destinations": [{"waypoint": d} for d in destinations],
        "travelMode": mode,
    }
    try:
        resp = await client.post(
            _URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
            timeout=8.0,
        )
        resp.raise_for_status()
        return _parse_seconds(resp.json(), len(destinations))
    except Exception:
        return [None] * len(destinations)


async def get_travel_times(
    client: httpx.AsyncClient,
    origin_lat: float,
    origin_lng: float,
    destinations: list[tuple[float, float, float]],  # (lat, lng, distance_mi)
) -> list[dict]:
    """
    Return one dict per destination: {"drive_min": int|None, "walk_min": int|None}.
    Walk time is only fetched for destinations within WALK_THRESHOLD_MI.
    Falls back to all-None values on any error.
    """
    if not destinations:
        return []

    key = get_settings().google_places_key
    origin_wp = {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}}
    dest_wps = [
        {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
        for lat, lng, _ in destinations
    ]

    # Fetch drive times for all; walk times only for nearby ones.
    walk_indices = [i for i, (_, _, mi) in enumerate(destinations) if mi <= _WALK_THRESHOLD_MI]
    walk_dest_wps = [dest_wps[i] for i in walk_indices]

    tasks = [_fetch_mode(client, key, origin_wp, dest_wps, "DRIVE")]
    if walk_dest_wps:
        tasks.append(_fetch_mode(client, key, origin_wp, walk_dest_wps, "WALK"))

    results = await asyncio.gather(*tasks)
    drive_secs = results[0]
    walk_secs_compact = results[1] if len(results) > 1 else []

    # Expand compact walk results back to full-length list.
    walk_secs: list[int | None] = [None] * len(destinations)
    for compact_i, orig_i in enumerate(walk_indices):
        if compact_i < len(walk_secs_compact):
            walk_secs[orig_i] = walk_secs_compact[compact_i]

    return [
        {
            "drive_min": round(s / 60) if s is not None else None,
            "walk_min": round(w / 60) if w is not None else None,
        }
        for s, w in zip(drive_secs, walk_secs)
    ]
