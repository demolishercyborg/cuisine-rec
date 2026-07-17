from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache

from anthropic import AsyncAnthropic

from .config import get_settings


@lru_cache
def _client() -> AsyncAnthropic:
    # Shared client so concurrent calls reuse pooled HTTP connections instead of each
    # paying a fresh TCP+TLS handshake. Fail fast (20s) rather than hang on a slow/degraded
    # API call — the SDK default timeout is 10 minutes.
    return AsyncAnthropic(api_key=get_settings().anthropic_key, timeout=20.0)

# Hour ranges to meal context labels
MEAL_BY_HOUR = [
    (5, "late_night"),
    (11, "breakfast"),
    (15, "lunch"),
    (17, "afternoon"),
    (22, "dinner"),
    (24, "late_night"),
]


def meal_context(now: datetime) -> str:
    h = now.hour
    for bound, label in MEAL_BY_HOUR:
        if h < bound:
            return label
    return "late_night"


_PLAN_SYSTEM = """You translate a person's food craving into concrete cuisines to search for nearby restaurants.
Return ONLY valid JSON, no prose, no markdown fences. Schema:
{"cuisines": [string, 2-4 items], "dish_query": string|null, "max_distance_mi": number|null, "rationale": string, "dietary_flags": [string]}
Rules:
- If the craving names a specific dish (e.g. "best birria tacos", "tonkotsu ramen",
  "lobster roll", "butter chicken"), set dish_query to the dish name (e.g. "birria tacos")
  and still populate cuisines with the matching cuisine category (e.g. "Mexican").
  For dish queries, 1-2 cuisines is enough — don't pad with unrelated ones.
  If the craving is a general mood, vibe, or cuisine type, set dish_query to null.
- cuisines must be concrete and searchable cuisine categories (e.g. "ramen", "Sichuan",
  "tacos", "Neapolitan pizza"). Never use ingredient-level searches like "mac and cheese"
  or "chicken pot pie" — those are dishes, not cuisines, and return poor Google Places results.
- Each cuisine must map to a real restaurant category that would appear on Google Maps
  (e.g. "Italian", "Thai", "Japanese izakaya", "Korean BBQ"). If in doubt, go broader.
- Respect the meal context: late_night favors ramen/tacos/diners, breakfast favors
  cafes/brunch, lunch favors casual spots, dinner allows sit-down restaurants.
- For mood-based cravings (e.g. "romantic", "cozy", "fun night out"), pick cuisines that
  are typically served in sit-down restaurants matching that atmosphere — not fast-casual,
  bar food, or street food unless the mood calls for it.
- If dietary constraints are given, only pick cuisines where the constraint is commonly
  accommodated, and echo the constraints in dietary_flags.
- presets are flavor/mood tags the user selected for THIS craving (e.g. "sweet treat"
  means dessert/pastry/sugar, "brothy & slurpable" means soup/noodles). They are direct
  requirements, not cuisines to diverge from — pick cuisines that actually satisfy them
  (e.g. "sweet treat" → bakery, patisserie, dessert cafe, ice cream, not an unrelated
  savory cuisine). If multiple presets are given, satisfy all of them together when
  possible.
- Pick cuisines that are distinct from each other — do not return 3 variations of the
  same cuisine (e.g. not "Thai curry", "Thai noodles", "Thai stir fry" together).
- weather describes current conditions at the user's location. Use it as a soft nudge:
  cold/rainy/snowing/stormy weather favors warm hearty cuisines (ramen, pho, soup
  dumplings, curry, stew, hot pot); hot/warm weather favors lighter or cold options
  (poke, sushi, salads, cold noodles, ceviche). If the craving text mentions a personal
  temperature tendency (e.g. "I run cold" or "I run hot"), blend it with the real weather
  — do not let it override weather entirely. For example, if it's mildly cool (60°F) and
  the user runs cold, lean warmer than you otherwise would; if it's mildly cool and the
  user runs hot, the weather barely nudges at all. If the craving already implies a strong
  food preference, honor that and let both weather and tendency play a smaller role.
- max_distance_mi: ranking priority is (1) craving fit, (2) quality, (3) distance,
  (4) weather. Weather is the last signal — use this field only to express a soft
  proximity preference when conditions make travel unpleasant. A truly great
  restaurant that fits the craving should always be shown even if it is far; closer
  options are preferred when quality is roughly equal. In bad weather (rainy, stormy,
  snowing, cold) set 2.0–4.0 mi. In good weather set 5.0–8.0 mi or null. For a
  specific dish craving loosen the cap — people will travel for exactly what they want.
  Never set a cap so tight it would exclude a clearly superior craving match.
- rationale is one short sentence the UI can show; if weather influenced the picks,
  mention it naturally (e.g. "Perfect for a rainy evening")."""


async def plan_cuisines(craving, presets, dietary, now, weather=None):
    settings = get_settings()
    client = _client()
    ctx = meal_context(now)
    user = json.dumps(
        {
            "craving_text": craving,
            "presets": presets,
            "dietary": dietary,
            "meal_context": ctx,
            "local_time": now.strftime("%H:%M"),
            "weather": weather,
        }
    )
    msg = await client.messages.create(
        model=settings.claude_model,
        max_tokens=400,
        system=_PLAN_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(text)
    data.setdefault("meal_context", ctx)
    data.setdefault("dish_query", None)
    data.setdefault("max_distance_mi", None)
    data["cuisines"] = data.get("cuisines", [])[:4]
    return data


_RANK_SYSTEM = """You are ranking a list of nearby restaurants for a user based on their craving and context.
Return ONLY valid JSON, no prose, no markdown fences. Schema:
{"ranked_ids": [string], "rationale": string}

Hard rule before anything else: group every restaurant with open_now=true (or null/unknown
hours) ahead of every restaurant with open_now=false. Rank within each group by the priority
order below — do not interleave a closed restaurant above an open one just because it scores
higher on craving fit or quality. Only exception: if a closed restaurant is a dramatically
better match (e.g. it's the only real hit for a specific dish craving), you may place it at
the top of the closed group, but it must still sort after ALL open restaurants.

Priority order — reason through these in sequence:
1. Craving fit: does the restaurant genuinely match what the user asked for? A perfect
   match at moderate quality beats a great restaurant that misses the vibe entirely.
2. Quality: rating weighted by review volume. 4.9★ with 2000 reviews is much stronger
   than 4.9★ with 15 reviews. Below 4.0★ should only appear if nothing better exists.
3. Real travel time (drive_min): use drive_min as your proximity signal, not distance_mi.
   Straight-line miles are misleading — geographic barriers like bridges, tolls, tunnels,
   and traffic corridors make some directions disproportionately slow or inconvenient even
   if the crow-flies distance looks short. A 25-min drive across a bridge to another city
   is meaningfully more of a commitment than a 25-min drive on local roads. When drive_min
   is similar, prefer the option that doesn't require crossing a major barrier. All else
   roughly equal, closer travel time is better — but a clearly superior craving match or
   quality is worth a longer drive; do not mechanically prefer the nearest option.
4. Weather & conditions: a soft final nudge only. Cold/rainy → lean toward closer,
   warmer, heartier options when quality is similar. Hot → lighter options edge up.
   Never let weather override a strong quality or craving match.

Also weigh:
- closes_soon=true: slight negative, user may not make it in time
- user_votes: net positive votes are a strong signal of past satisfaction;
  net negative votes mean real users were disappointed — down-weight accordingly
- vibe and signature_dishes: do they match the mood and craving?
- walk_min: factor walk time for very close spots — walkable is a genuine convenience bonus

Include ALL restaurant IDs in ranked_ids — do not drop any.
rationale is one sentence the UI shows — explain what drove the top pick or the overall ordering."""


async def rank_restaurants(candidates: list[dict], craving: str, weather: str | None, meal_context: str) -> list[str] | None:
    """Ask Claude to rank candidate restaurants. Returns ordered list of place_ids, or None on failure."""
    if not candidates:
        return None
    settings = get_settings()
    client = _client()
    payload = json.dumps({
        "craving": craving,
        "meal_context": meal_context,
        "weather": weather,
        "candidates": candidates,
    })
    try:
        msg = await client.messages.create(
            model=settings.claude_model,
            max_tokens=600,
            system=_RANK_SYSTEM,
            messages=[{"role": "user", "content": payload}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
        ranked = data.get("ranked_ids")
        if isinstance(ranked, list) and ranked:
            return ranked
    except Exception:
        pass
    return None


_SUMM_SYSTEM = """You summarize restaurant reviews into a compact card.
Return ONLY valid JSON, no markdown. Schema:
{"signature_dishes": [string, up to 3], "vibe": string}
Base it strictly on the provided text. If reviews don't name dishes, return an
empty list rather than guessing. vibe is at most 8 words."""


async def summarize_restaurant(name, review_texts, editorial):
    if not review_texts and not editorial:
        return {"signature_dishes": [], "vibe": None}
    settings = get_settings()
    client = _client()
    payload = json.dumps(
        {"name": name, "editorial_summary": editorial or "", "reviews": review_texts[:6]}
    )
    msg = await client.messages.create(
        model=settings.claude_model,
        max_tokens=200,
        system=_SUMM_SYSTEM,
        messages=[{"role": "user", "content": payload}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"signature_dishes": [], "vibe": None}
