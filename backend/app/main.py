"""Recommendation API."""
from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .feedback import get_biases, init_db, record_vote
from .models import CuisinePlan, FeedbackRequest, RecommendRequest, RecommendResponse, Restaurant
from .openhours import compute_open, haversine_miles
from .places import search_cuisine
from .reasoning import plan_cuisines, rank_restaurants, summarize_restaurant
from .travel import get_travel_times
from .weather import get_weather

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(_settings.feedback_db)
    yield


app = FastAPI(title="Cuisine Recommendation Engine", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUMMARIZE_TOP_N = 8


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/feedback")
async def feedback(req: FeedbackRequest) -> dict:
    if req.vote not in (1, -1):
        raise HTTPException(status_code=422, detail="vote must be 1 or -1")
    await asyncio.to_thread(record_vote, req.place_id, req.vote)
    return {"ok": True}


def _price_to_int(price_level):
    # Places returns enums like "PRICE_LEVEL_MODERATE".
    if price_level is None:
        return None
    mapping = {
        "PRICE_LEVEL_FREE": 0,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    if isinstance(price_level, str):
        return mapping.get(price_level)
    return None


def _rank_score(r: Restaurant, bias: float = 0.0) -> float:
    # Cheap pre-sort to pick which candidates get enrichment and go to Claude for final ranking.
    # Claude does the real reasoning — this just needs to be a reasonable first approximation.
    rating = r.rating or 0.0
    volume = math.log10((r.review_count or 0) + 1)
    base = rating * (1 + 0.35 * volume)
    if r.distance_mi is not None:
        if r.distance_mi <= 3.0:
            base -= r.distance_mi * 0.20
        else:
            base -= 3.0 * 0.20 + (r.distance_mi - 3.0) * 0.07
    if r.open_now is False:
        base -= 3.0
    elif r.open_now:
        base += 0.5
    if r.closes_soon:
        base -= 0.25
    base += r.dish_mentions * 0.4
    base += bias * 1.5
    return round(base, 4)


_STOPWORDS = {"restaurant", "food", "point", "of", "interest", "establishment", "and", "shop", "store", "house"}


def _type_words(t: str) -> set[str]:
    return {w for w in t.replace("_", " ").split() if w not in _STOPWORDS}


def _is_relevant(cuisine: str, types: list[str], name: str) -> bool:
    # Google's text search returns loosely-related nearby places (e.g. a burger bar
    # showing up under "ice cream restaurant"). Cross-check the result's own place
    # types against the cuisine we searched for and drop results with no real overlap
    # — otherwise they get mislabeled with a cuisine they have nothing to do with.
    # A cuisine word appearing in the place's own name is treated as relevant too,
    # since Google's types sometimes omit an obvious category (e.g. "Bear's Ramen
    # House" isn't tagged ramen_restaurant).
    query_words = _type_words(cuisine)
    if not query_words:
        return True
    name_words = _type_words(name)
    if query_words & name_words:
        return True
    if not types:
        return True
    type_words = {w for t in types for w in _type_words(t)}
    return bool(query_words & type_words)


def _to_restaurant(raw, cuisine, req, now):
    loc = raw.get("location", {})
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    hours = raw.get("currentOpeningHours") or raw.get("regularOpeningHours")
    open_now, closes_soon, hours_today = compute_open(hours, now)
    dist = (
        haversine_miles(req.lat, req.lng, lat, lng)
        if lat is not None and lng is not None
        else None
    )
    editorial = (raw.get("editorialSummary") or {}).get("text")
    return Restaurant(
        place_id=raw.get("id", ""),
        name=(raw.get("displayName") or {}).get("text", "Unknown"),
        cuisine=cuisine,
        rating=raw.get("rating"),
        review_count=raw.get("userRatingCount"),
        price_level=_price_to_int(raw.get("priceLevel")),
        lat=lat or 0.0,
        lng=lng or 0.0,
        address=raw.get("formattedAddress"),
        distance_mi=round(dist, 1) if dist is not None else None,
        open_now=open_now,
        closes_soon=closes_soon,
        hours_today=hours_today,
        vibe=editorial,
        maps_uri=raw.get("googleMapsUri"),
    )


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest) -> RecommendResponse:
    try:
        get_settings().require()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    now = datetime.fromisoformat(req.local_iso)

    # Fetch weather first (fast, ~100ms Open-Meteo), then pass it into the Claude
    # craving→cuisines call so weather context is available in a single prompt.
    async with httpx.AsyncClient() as client:
        weather = await get_weather(client, req.lat, req.lng)

    plan_data = await plan_cuisines(req.craving, req.presets, req.dietary, now, weather=weather)
    plan = CuisinePlan(**plan_data)
    if not plan.cuisines:
        return RecommendResponse(plan=plan, restaurants=[])

    dish_query = plan.dish_query

    # One Places search per cuisine, run together.
    async with httpx.AsyncClient() as client:
        tasks = [
            search_cuisine(
                client, c, req.lat, req.lng,
                _settings.search_radius_m, _settings.per_cuisine_limit,
                req.dietary, dish_query,
            )
            for c in plan.cuisines
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    seen = set()
    restaurants = []
    raw_by_id = {}
    for cuisine, res in zip(plan.cuisines, results):
        if isinstance(res, Exception):
            continue
        for raw in res:
            pid = raw.get("id")
            if not pid or pid in seen:
                continue
            name = (raw.get("displayName") or {}).get("text", "")
            if not _is_relevant(cuisine, raw.get("types") or [], name):
                continue
            seen.add(pid)
            raw_by_id[pid] = raw
            restaurants.append(_to_restaurant(raw, cuisine, req, now))

    # Collapse same-name branches (e.g. a chain's Berkeley and SF locations) down to
    # the single closest one — different place_ids, but showing both is redundant.
    by_name: dict[str, Restaurant] = {}
    for r in restaurants:
        key = r.name.strip().casefold()
        existing = by_name.get(key)
        if existing is None or (r.distance_mi or math.inf) < (existing.distance_mi or math.inf):
            by_name[key] = r
    restaurants = list(by_name.values())

    if req.open_only:
        restaurants = [r for r in restaurants if r.open_now is not False]

    # Pre-sort by heuristic score to pick the top-N candidates to enrich.
    biases = await asyncio.to_thread(get_biases, [r.place_id for r in restaurants])
    for r in restaurants:
        r.score = _rank_score(r, biases.get(r.place_id, 0.0))
    restaurants.sort(key=lambda r: r.score, reverse=True)

    top = restaurants[:SUMMARIZE_TOP_N]

    async def _enrich(r):
        raw = raw_by_id.get(r.place_id, {})
        reviews = [
            (rv.get("text") or {}).get("text", "")
            for rv in (raw.get("reviews") or [])
        ]
        reviews = [t for t in reviews if t]
        if dish_query:
            needle = dish_query.lower()
            r.dish_mentions = sum(1 for t in reviews if needle in t.lower())
        editorial = (raw.get("editorialSummary") or {}).get("text")
        summary = await summarize_restaurant(r.name, reviews, editorial)
        r.signature_dishes = summary.get("signature_dishes", []) or []
        if summary.get("vibe"):
            r.vibe = summary["vibe"]

    await asyncio.gather(*[_enrich(r) for r in top])

    # Re-score after enrichment, then take the final pool for Claude to rank.
    for r in restaurants:
        r.score = _rank_score(r, biases.get(r.place_id, 0.0))
    restaurants.sort(key=lambda r: r.score, reverse=True)
    final = restaurants[:20]

    # Fetch real travel times for the final pool.
    async with httpx.AsyncClient() as client:
        times = await get_travel_times(
            client,
            req.lat,
            req.lng,
            [(r.lat, r.lng, r.distance_mi or 0.0) for r in final],
        )
    for r, t in zip(final, times):
        r.drive_min = t.get("drive_min")
        r.walk_min = t.get("walk_min")

    # Claude final ranking — reasons about craving fit, quality, distance, weather
    # together with full context. Falls back to heuristic order on failure.
    candidates = [
        {
            "id": r.place_id,
            "name": r.name,
            "cuisine": r.cuisine,
            "rating": r.rating,
            "reviews": r.review_count,
            "distance_mi": r.distance_mi,
            "drive_min": r.drive_min,
            "walk_min": r.walk_min,
            "open_now": r.open_now,
            "closes_soon": r.closes_soon,
            "vibe": r.vibe,
            "signature_dishes": r.signature_dishes,
            "user_votes": round(biases.get(r.place_id, 0.0) * 10),
        }
        for r in final
    ]
    ranked_ids = await rank_restaurants(candidates, req.craving, weather, plan.meal_context)
    if ranked_ids:
        id_to_r = {r.place_id: r for r in final}
        reordered = [id_to_r[rid] for rid in ranked_ids if rid in id_to_r]
        # Append any not mentioned by Claude (safety net) at the end.
        seen_ids = set(ranked_ids)
        reordered += [r for r in final if r.place_id not in seen_ids]
        final = reordered

    # Guarantee open/unknown-hours restaurants are grouped ahead of confirmed-closed
    # ones, regardless of how Claude (or the heuristic fallback) ordered them.
    final.sort(key=lambda r: r.open_now is False)

    return RecommendResponse(plan=plan, restaurants=final)
