"""Fetch current weather from Open-Meteo (no API key required)."""
from __future__ import annotations

import httpx

_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes → condition label
def _condition(code: int, precip: float) -> str:
    if code in (71, 73, 75, 77, 85, 86):
        return "snowing"
    if code in (95, 96, 99):
        return "stormy"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rainy"
    if precip > 0.1:
        return "rainy"
    if code in (1, 2, 3, 45, 48):
        return "overcast"
    return "clear"


def _temp_label(f: float) -> str:
    if f <= 45:
        return "freezing"
    if f <= 55:
        return "cold"
    if f <= 65:
        return "cool"
    if f <= 75:
        return "mild"
    if f <= 85:
        return "warm"
    return "hot"


def _descriptor(temp_f: float, code: int, precip: float) -> str:
    tl = _temp_label(temp_f)
    cond = _condition(code, precip)
    temp_str = f"{round(temp_f)}°F"
    if cond in ("rainy", "snowing", "stormy"):
        return f"{tl} and {cond} ({temp_str})"
    if cond == "overcast":
        return f"{tl} and overcast ({temp_str})"
    return f"{tl} and {cond} ({temp_str})"


async def get_weather(client: httpx.AsyncClient, lat: float, lng: float) -> str | None:
    try:
        resp = await client.get(
            _URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "current": "temperature_2m,precipitation,weather_code",
                "temperature_unit": "fahrenheit",
                "forecast_days": 1,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        current = resp.json().get("current", {})
        temp_f = current.get("temperature_2m")
        precip = current.get("precipitation", 0.0)
        code = current.get("weather_code", 0)
        if temp_f is None:
            return None
        return _descriptor(float(temp_f), int(code), float(precip))
    except Exception:
        return None
