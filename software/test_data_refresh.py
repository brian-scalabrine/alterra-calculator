"""Tests for daily refresh scheduling logic."""

from datetime import datetime
from zoneinfo import ZoneInfo

from data_refresh import latest_refresh_cutoff, needs_scheduled_refresh

TZ = ZoneInfo("America/New_York")


def test_before_3pm_uses_yesterday_cutoff():
    now = datetime(2026, 7, 5, 10, 0, tzinfo=TZ)
    cutoff = latest_refresh_cutoff(now=now)
    assert cutoff == datetime(2026, 7, 4, 15, 0, tzinfo=TZ)


def test_after_3pm_uses_today_cutoff():
    now = datetime(2026, 7, 5, 16, 0, tzinfo=TZ)
    cutoff = latest_refresh_cutoff(now=now)
    assert cutoff == datetime(2026, 7, 5, 15, 0, tzinfo=TZ)


def test_no_refresh_needed_when_updated_after_cutoff():
    now = datetime(2026, 7, 5, 16, 0, tzinfo=TZ)
    last = datetime(2026, 7, 5, 15, 5, tzinfo=TZ)
    assert needs_scheduled_refresh(last, now=now) is False


def test_refresh_needed_when_updated_before_cutoff():
    now = datetime(2026, 7, 5, 16, 0, tzinfo=TZ)
    last = datetime(2026, 7, 5, 14, 0, tzinfo=TZ)
    assert needs_scheduled_refresh(last, now=now) is True


def test_refresh_needed_when_never_refreshed():
    now = datetime(2026, 7, 5, 16, 0, tzinfo=TZ)
    assert needs_scheduled_refresh(None, now=now) is True


if __name__ == "__main__":
    test_before_3pm_uses_yesterday_cutoff()
    test_after_3pm_uses_today_cutoff()
    test_no_refresh_needed_when_updated_after_cutoff()
    test_refresh_needed_when_updated_before_cutoff()
    test_refresh_needed_when_never_refreshed()
    print("All refresh schedule tests passed.")
