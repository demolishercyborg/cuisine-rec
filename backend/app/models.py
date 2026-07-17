"""Request and response schemas."""
from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    lat: float
    lng: float
    craving: str = ""
    presets: list[str] = Field(default_factory=list)
    local_iso: str  # user's local datetime, ISO 8601
    weekday: int = Field(..., ge=0, le=6)  # Mon=0..Sun=6
    dietary: list[str] = Field(default_factory=list)
    open_only: bool = True


class FeedbackRequest(BaseModel):
    place_id: str
    vote: int = Field(..., ge=-1, le=1)


class CuisinePlan(BaseModel):
    cuisines: list[str]
    meal_context: str
    rationale: str
    dietary_flags: list[str] = Field(default_factory=list)
    dish_query: str | None = None
    max_distance_mi: float | None = None


class Restaurant(BaseModel):
    place_id: str
    name: str
    cuisine: str
    rating: float | None = None
    review_count: int | None = None
    price_level: int | None = None
    lat: float
    lng: float
    address: str | None = None
    distance_mi: float | None = None
    open_now: bool | None = None
    closes_soon: bool = False
    hours_today: str | None = None
    signature_dishes: list[str] = Field(default_factory=list)
    vibe: str | None = None
    maps_uri: str | None = None
    dish_mentions: int = 0
    drive_min: int | None = None
    walk_min: int | None = None
    score: float = 0.0


class RecommendResponse(BaseModel):
    plan: CuisinePlan
    restaurants: list[Restaurant]
