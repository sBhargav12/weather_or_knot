from __future__ import annotations

from datetime import datetime, timezone

from data_ingest.forecast_vintages import is_vintage_valid


def test_gfs_12z_not_available_at_11am():
    cycle = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert not is_vintage_valid("GFS", cycle, "2025-06-15 11:00")


def test_gfs_12z_available_at_1pm():
    cycle = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert is_vintage_valid("GFS", cycle, "2025-06-15 13:00")


def test_ecmwf_12z_not_available_at_1pm():
    cycle = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert not is_vintage_valid("ECMWF", cycle, "2025-06-15 13:00")


def test_hrrr_available_quickly():
    cycle = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
    assert is_vintage_valid("HRRR", cycle, "2025-06-15 06:45")
