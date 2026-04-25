from __future__ import annotations

from data_ingest.wethr_client import WethrClient


def test_celsius_to_fahrenheit():
    assert WethrClient.celsius_to_fahrenheit(0) == 32
    assert WethrClient.celsius_to_fahrenheit(10) == 50


def test_history_requires_start_and_end():
    client = WethrClient("dummy")
    try:
        client.get_history("KNYC", "", "2026-04-25 23:59:59")
    except ValueError as exc:
        assert "start_time and end_time" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_forecast_maxt_handles_empty_response(monkeypatch):
    client = WethrClient("dummy")
    monkeypatch.setattr(client, "get_forecast", lambda station, model, run="latest": [])
    assert client.get_forecast_maxt("KNYC", "HRRR", "2026-04-25") is None


def test_forecast_maxt_filters_target_local_date(monkeypatch):
    client = WethrClient("dummy")
    rows = [
        {"valid_time": "2026-04-25 12:00:00", "temperature_f": "50.0"},
        {"valid_time": "2026-04-25 18:00:00", "temperature_f": "57.5"},
        {"valid_time": "2026-04-26 18:00:00", "temperature_f": "80.0"},
    ]
    monkeypatch.setattr(client, "get_forecast", lambda station, model, run="latest": rows)
    assert client.get_forecast_maxt("KNYC", "HRRR", "2026-04-25") == 57.5
