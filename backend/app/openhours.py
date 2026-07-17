"""Open hours and distance helpers."""
from __future__ import annotations

import math
from datetime import datetime


def _py_weekday_to_google(py_wd: int) -> int:
    # Python Mon=0..Sun=6 to Google Sun=0..Sat=6
    return (py_wd + 1) % 7


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    # Great circle distance between two points in miles.
    radius = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def compute_open(
    opening_hours: dict | None, now: datetime, closes_soon_threshold_min: int = 45
) -> tuple[bool | None, bool, str | None]:
    # Returns (open_now, closes_soon, hours_today). open_now is None if no data.
    if not opening_hours:
        return None, False, None

    periods = opening_hours.get("periods") or []
    if not periods:
        flag = opening_hours.get("openNow")
        return (bool(flag) if flag is not None else None), False, None

    g_today = _py_weekday_to_google(now.weekday())
    g_yesterday = (g_today - 1) % 7
    now_min = _minutes(now.hour, now.minute)

    open_now = False
    minutes_until_close = None

    for p in periods:
        o = p.get("open")
        c = p.get("close")
        if not o:
            continue
        o_day = o.get("day")
        o_min = _minutes(o.get("hour", 0), o.get("minute", 0))
        # No close point means open 24 hours from that point.
        if not c:
            if o_day == g_today:
                open_now = True
            continue
        c_day = c.get("day")
        c_min = _minutes(c.get("hour", 0), c.get("minute", 0))

        if o_day == c_day:
            if o_day == g_today and o_min <= now_min < c_min:
                open_now = True
                minutes_until_close = c_min - now_min
        else:
            # Overnight window that crosses midnight.
            if o_day == g_today and now_min >= o_min:
                open_now = True
                minutes_until_close = (24 * 60 - now_min) + c_min
            elif c_day == g_today and now_min < c_min and o_day == g_yesterday:
                open_now = True
                minutes_until_close = c_min - now_min

    closes_soon = (
        open_now
        and minutes_until_close is not None
        and minutes_until_close <= closes_soon_threshold_min
    )

    hours_today = None
    descs = opening_hours.get("weekdayDescriptions") or []
    if descs and len(descs) == 7:
        hours_today = descs[now.weekday()]

    return open_now, closes_soon, hours_today
