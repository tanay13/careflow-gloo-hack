"""Deterministic demo clock.

All scheduling uses a fixed "now" (DEMO_NOW) so that demo runs and evals are
reproducible regardless of the real date. Synthetic calendars are expressed as
day offsets from Monday of the demo week.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from config import settings

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def demo_now() -> datetime:
    return datetime.fromisoformat(settings.demo_now)


def week_start() -> datetime:
    now = demo_now()
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def at_offset(day_offset: int, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return week_start() + timedelta(days=day_offset, hours=h, minutes=m)


def end_of_week() -> datetime:
    """Friday 17:00 of the demo week."""
    return at_offset(4, "17:00")


def end_of_today() -> datetime:
    now = demo_now()
    return now.replace(hour=17, minute=0, second=0, microsecond=0)


def fmt(dt: datetime) -> str:
    return dt.strftime("%a %b %-d, %-I:%M %p")


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
