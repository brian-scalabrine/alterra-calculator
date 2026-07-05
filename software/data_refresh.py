"""
Daily yield-data refresh schedule and cache helpers.

Refreshes once per day after 3:00 PM Eastern if the cache has not been updated
since the most recent 3:00 PM cutoff.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from scrape_boxtrades import scrape_boxtrades
from update_maturity_dates import remove_expired_maturities

CACHE_FILE = "yield_data_cache.json"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_REFRESH_HOUR = 15
DEFAULT_REFRESH_MINUTE = 0


@dataclass
class CachePayload:
    df: pd.DataFrame
    last_refreshed_at: Optional[datetime]


def get_refresh_timezone(tz_name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    return ZoneInfo(tz_name)


def latest_refresh_cutoff(
    now: Optional[datetime] = None,
    *,
    tz_name: str = DEFAULT_TIMEZONE,
    hour: int = DEFAULT_REFRESH_HOUR,
    minute: int = DEFAULT_REFRESH_MINUTE,
) -> datetime:
    """Most recent scheduled refresh time (3:00 PM ET by default)."""
    tz = get_refresh_timezone(tz_name)
    if now is None:
        now = datetime.now(tz)
    else:
        now = now.astimezone(tz)

    cutoff_today = datetime.combine(now.date(), time(hour, minute), tzinfo=tz)
    if now >= cutoff_today:
        return cutoff_today
    return cutoff_today - timedelta(days=1)


def needs_scheduled_refresh(
    last_refreshed_at: Optional[datetime],
    now: Optional[datetime] = None,
    *,
    tz_name: str = DEFAULT_TIMEZONE,
    hour: int = DEFAULT_REFRESH_HOUR,
    minute: int = DEFAULT_REFRESH_MINUTE,
) -> bool:
    """True when data should be scraped for the current refresh window."""
    cutoff = latest_refresh_cutoff(now=now, tz_name=tz_name, hour=hour, minute=minute)
    if last_refreshed_at is None:
        return True

    tz = get_refresh_timezone(tz_name)
    last = last_refreshed_at.astimezone(tz)
    return last < cutoff


def _parse_last_refreshed(value) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["Maturity Date", "Effective Yield"])


def load_cache(cache_path: str = CACHE_FILE) -> CachePayload:
    """Load cached yield data and refresh timestamp."""
    if not os.path.exists(cache_path):
        return CachePayload(df=_empty_df(), last_refreshed_at=None)

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return CachePayload(df=_empty_df(), last_refreshed_at=None)

    if isinstance(raw, list):
        records = raw
        last_refreshed_at = None
    elif isinstance(raw, dict):
        records = raw.get("records", [])
        last_refreshed_at = _parse_last_refreshed(raw.get("last_refreshed_at"))
    else:
        return CachePayload(df=_empty_df(), last_refreshed_at=None)

    if not records:
        return CachePayload(df=_empty_df(), last_refreshed_at=last_refreshed_at)

    df = pd.DataFrame(records)
    if not df.empty:
        df["Maturity Date"] = pd.to_datetime(df["Maturity Date"])
        df = remove_expired_maturities(df)
    return CachePayload(df=df, last_refreshed_at=last_refreshed_at)


def save_cache(
    df: pd.DataFrame,
    last_refreshed_at: datetime,
    cache_path: str = CACHE_FILE,
) -> None:
    """Persist yield data and refresh timestamp."""
    df_cache = df.copy()
    if not df_cache.empty:
        df_cache["Maturity Date"] = df_cache["Maturity Date"].dt.strftime("%Y-%m-%d")

    payload = {
        "last_refreshed_at": last_refreshed_at.isoformat(),
        "records": df_cache.to_dict("records"),
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def refresh_yield_data(
    *,
    force: bool = False,
    cache_path: str = CACHE_FILE,
    tz_name: str = DEFAULT_TIMEZONE,
    hour: int = DEFAULT_REFRESH_HOUR,
    minute: int = DEFAULT_REFRESH_MINUTE,
) -> tuple[pd.DataFrame, bool, Optional[datetime], Optional[str]]:
    """
    Refresh yield data when due (or when forced).

    Returns:
        (dataframe, did_refresh, last_refreshed_at, error_message)
    """
    cached = load_cache(cache_path)
    tz = get_refresh_timezone(tz_name)
    now = datetime.now(tz)

    if not force and not needs_scheduled_refresh(
        cached.last_refreshed_at,
        now=now,
        tz_name=tz_name,
        hour=hour,
        minute=minute,
    ):
        return cached.df, False, cached.last_refreshed_at, None

    try:
        fresh_data = scrape_boxtrades()
    except Exception as exc:
        if not cached.df.empty:
            return cached.df, False, cached.last_refreshed_at, str(exc)
        return _empty_df(), False, None, str(exc)

    if fresh_data.empty:
        if not cached.df.empty:
            return cached.df, False, cached.last_refreshed_at, "No data received from scraping."
        return _empty_df(), False, None, "No data received from scraping."

    fresh_data["Maturity Date"] = pd.to_datetime(fresh_data["Maturity Date"])
    fresh_data = remove_expired_maturities(fresh_data)
    refreshed_at = datetime.now(tz)
    save_cache(fresh_data, refreshed_at, cache_path=cache_path)
    return fresh_data, True, refreshed_at, None


def format_last_refreshed(last_refreshed_at: Optional[datetime], tz_name: str = DEFAULT_TIMEZONE) -> str:
    if last_refreshed_at is None:
        return "Never"
    tz = get_refresh_timezone(tz_name)
    return last_refreshed_at.astimezone(tz).strftime("%b %d, %Y %I:%M %p %Z")
