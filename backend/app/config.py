"""App settings from environment variables."""
import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.google_places_key = os.environ.get("GOOGLE_PLACES_KEY", "")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.claude_model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.search_radius_m = int(os.environ.get("SEARCH_RADIUS_M", "8000"))
        self.per_cuisine_limit = int(os.environ.get("PER_CUISINE_LIMIT", "20"))
        self.cors_origins = os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173"
        ).split(",")
        self.feedback_db = os.environ.get("FEEDBACK_DB", "feedback.db")

    def require(self) -> None:
        missing = [
            name
            for name, val in (
                ("GOOGLE_PLACES_KEY", self.google_places_key),
                ("ANTHROPIC_API_KEY", self.anthropic_key),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
