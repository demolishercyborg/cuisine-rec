"""Unit tests for compute_open(), focused on overnight (cross-midnight) windows."""
import pytest
from datetime import datetime

from app.openhours import compute_open, _py_weekday_to_google


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _period(o_day, o_h, o_m, c_day=None, c_h=None, c_m=None):
    p = {"open": {"day": o_day, "hour": o_h, "minute": o_m}}
    if c_day is not None:
        p["close"] = {"day": c_day, "hour": c_h, "minute": c_m}
    return p


def _now(py_weekday: int, hour: int, minute: int) -> datetime:
    """Return a datetime whose weekday() == py_weekday and time == HH:MM."""
    # 2024-01-01 is a Monday (py weekday 0); offset from there.
    base = datetime(2024, 1, 1)  # Monday
    delta_days = (py_weekday - base.weekday()) % 7
    from datetime import timedelta
    d = base + timedelta(days=delta_days)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Weekday conversion
# ---------------------------------------------------------------------------

class TestPyWeekdayToGoogle:
    def test_monday(self):
        assert _py_weekday_to_google(0) == 1

    def test_sunday(self):
        assert _py_weekday_to_google(6) == 0

    def test_saturday(self):
        assert _py_weekday_to_google(5) == 6

    def test_wednesday(self):
        assert _py_weekday_to_google(2) == 3


# ---------------------------------------------------------------------------
# No data / empty cases
# ---------------------------------------------------------------------------

class TestNoData:
    def test_none_opening_hours(self):
        open_now, closes_soon, hours_today = compute_open(None, datetime.now())
        assert open_now is None
        assert closes_soon is False
        assert hours_today is None

    def test_empty_dict(self):
        open_now, closes_soon, hours_today = compute_open({}, datetime.now())
        assert open_now is None

    def test_openNow_flag_true(self):
        open_now, closes_soon, _ = compute_open({"openNow": True}, datetime.now())
        assert open_now is True
        assert closes_soon is False

    def test_openNow_flag_false(self):
        open_now, _, _ = compute_open({"openNow": False}, datetime.now())
        assert open_now is False

    def test_empty_periods_falls_back_to_openNow(self):
        oh = {"periods": [], "openNow": True}
        open_now, _, _ = compute_open(oh, datetime.now())
        assert open_now is True


# ---------------------------------------------------------------------------
# Same-day (non-overnight) windows
# ---------------------------------------------------------------------------

class TestSameDayWindow:
    # Monday in Python = weekday 0, Google day 1
    def _monday_periods(self):
        return [_period(1, 9, 0, 1, 17, 0)]  # Mon 09:00-17:00

    def test_open_inside_window(self):
        now = _now(0, 12, 0)  # Monday 12:00
        open_now, closes_soon, _ = compute_open({"periods": self._monday_periods()}, now)
        assert open_now is True
        assert closes_soon is False

    def test_closed_before_open(self):
        now = _now(0, 8, 59)
        open_now, _, _ = compute_open({"periods": self._monday_periods()}, now)
        assert open_now is False

    def test_closed_at_close_minute(self):
        now = _now(0, 17, 0)  # Boundary: open range is [open, close)
        open_now, _, _ = compute_open({"periods": self._monday_periods()}, now)
        assert open_now is False

    def test_closes_soon_true(self):
        now = _now(0, 16, 30)  # 30 min before 17:00
        open_now, closes_soon, _ = compute_open(
            {"periods": self._monday_periods()}, now, closes_soon_threshold_min=45
        )
        assert open_now is True
        assert closes_soon is True

    def test_closes_soon_false_when_far(self):
        now = _now(0, 10, 0)  # 7 h away
        _, closes_soon, _ = compute_open({"periods": self._monday_periods()}, now)
        assert closes_soon is False


# ---------------------------------------------------------------------------
# Overnight windows (cross-midnight) — core focus
# ---------------------------------------------------------------------------

class TestOvernightWindow:
    """
    Restaurant open Saturday (Google day 6) 22:00 → Sunday (Google day 0) 02:00.
    Python: Saturday = weekday 5, Sunday = weekday 6.
    Google: Saturday = 6, Sunday = 0.
    """

    def _overnight_periods(self):
        return [_period(6, 22, 0, 0, 2, 0)]  # Sat 22:00 – Sun 02:00

    # --- Saturday side ---

    def test_open_on_saturday_after_open(self):
        now = _now(5, 22, 30)  # Saturday 22:30
        open_now, closes_soon, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert open_now is True

    def test_open_exactly_at_open(self):
        now = _now(5, 22, 0)  # Saturday 22:00 sharp
        open_now, _, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert open_now is True

    def test_closed_before_open_on_saturday(self):
        now = _now(5, 21, 59)  # Saturday 21:59
        open_now, _, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert open_now is False

    def test_closes_soon_late_saturday(self):
        # 23:30 Sat → 2.5 h until 02:00 Sun = 150 min, not soon
        now = _now(5, 23, 30)
        _, closes_soon, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert closes_soon is False

    def test_minutes_until_close_from_saturday(self):
        # At 23:45 Sat (15 min before midnight + 120 min = 135 min until 02:00 Sun)
        now = _now(5, 23, 45)
        open_now, closes_soon, _ = compute_open(
            {"periods": self._overnight_periods()}, now, closes_soon_threshold_min=140
        )
        assert open_now is True
        assert closes_soon is True  # 135 min <= 140 threshold

    # --- Sunday side (after midnight) ---

    def test_open_on_sunday_before_close(self):
        now = _now(6, 1, 30)  # Sunday 01:30
        open_now, _, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert open_now is True

    def test_open_on_sunday_at_one_minute_before_close(self):
        now = _now(6, 1, 59)  # Sunday 01:59
        open_now, closes_soon, _ = compute_open(
            {"periods": self._overnight_periods()}, now, closes_soon_threshold_min=45
        )
        assert open_now is True
        assert closes_soon is True  # 1 min left

    def test_closed_on_sunday_at_close_minute(self):
        now = _now(6, 2, 0)  # Sunday 02:00 — boundary, should be closed
        open_now, _, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert open_now is False

    def test_closed_on_sunday_after_close(self):
        now = _now(6, 3, 0)  # Sunday 03:00
        open_now, _, _ = compute_open({"periods": self._overnight_periods()}, now)
        assert open_now is False

    def test_closes_soon_just_before_sunday_close(self):
        now = _now(6, 1, 20)  # 40 min before 02:00
        _, closes_soon, _ = compute_open(
            {"periods": self._overnight_periods()}, now, closes_soon_threshold_min=45
        )
        assert closes_soon is True

    # --- Week boundary: Sunday night → Monday morning ---

    def test_sunday_night_open(self):
        # Sun (Google 0) 23:00 → Mon (Google 1) 01:00
        periods = [_period(0, 23, 0, 1, 1, 0)]
        now = _now(6, 23, 30)  # Python Sunday 23:30
        open_now, _, _ = compute_open({"periods": periods}, now)
        assert open_now is True

    def test_monday_morning_after_sunday_night(self):
        periods = [_period(0, 23, 0, 1, 1, 0)]
        now = _now(0, 0, 30)  # Python Monday 00:30
        open_now, _, _ = compute_open({"periods": periods}, now)
        assert open_now is True

    def test_monday_morning_after_close(self):
        periods = [_period(0, 23, 0, 1, 1, 0)]
        now = _now(0, 1, 0)  # Exactly at close — should be closed
        open_now, _, _ = compute_open({"periods": periods}, now)
        assert open_now is False


# ---------------------------------------------------------------------------
# 24-hour (no close period)
# ---------------------------------------------------------------------------

class TestNoClosePeriod:
    def test_open_24h(self):
        # Period with no close key means open 24 h from that day.
        periods = [_period(1, 0, 0)]  # Monday, no close
        now = _now(0, 14, 0)  # Monday 14:00
        open_now, closes_soon, _ = compute_open({"periods": periods}, now)
        assert open_now is True
        assert closes_soon is False  # minutes_until_close stays None

    def test_not_matching_day(self):
        periods = [_period(2, 0, 0)]  # Tuesday only, no close
        now = _now(0, 14, 0)  # Monday
        open_now, _, _ = compute_open({"periods": periods}, now)
        assert open_now is False


# ---------------------------------------------------------------------------
# weekdayDescriptions
# ---------------------------------------------------------------------------

class TestHoursToday:
    def test_returns_correct_weekday_description(self):
        # weekdayDescriptions is indexed by Python weekday (Mon=0).
        # Needs a non-empty periods list so the early-return branch is skipped.
        descs = [
            "Monday: 9–5", "Tuesday: 9–5", "Wednesday: 9–5",
            "Thursday: 9–5", "Friday: 9–5", "Saturday: closed", "Sunday: closed",
        ]
        # Monday in Google = day 1; add a period so we reach the description code.
        oh = {
            "periods": [_period(1, 9, 0, 1, 17, 0)],
            "weekdayDescriptions": descs,
        }
        now = _now(0, 10, 0)  # Python Monday → descs[0]
        _, _, hours_today = compute_open(oh, now)
        assert hours_today == "Monday: 9–5"

    def test_none_when_wrong_length(self):
        oh = {"periods": [], "weekdayDescriptions": ["only one entry"]}
        _, _, hours_today = compute_open(oh, datetime.now())
        assert hours_today is None
