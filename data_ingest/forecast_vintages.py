from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

MODEL_AVAILABILITY_DELAYS = {
    "GFS": timedelta(hours=4, minutes=40),
    "ECMWF": timedelta(hours=7),
    "HRRR": timedelta(minutes=30),
    "NBM": timedelta(minutes=45),
    "UKMO": timedelta(hours=5),
    "NAM": timedelta(hours=4, minutes=35),
}


def earliest_available_utc(model: str, cycle_init_utc: datetime) -> datetime:
    """Return the earliest UTC time when a model run is expected public."""
    if cycle_init_utc.tzinfo is None:
        cycle_init_utc = cycle_init_utc.replace(tzinfo=UTC)
    delay = MODEL_AVAILABILITY_DELAYS.get(model.upper(), timedelta(hours=5))
    return cycle_init_utc.astimezone(UTC) + delay


def is_vintage_valid(model: str, cycle_init_utc: datetime, trade_time_et: str) -> bool:
    """Return True only if the model run was available before the ET trade time."""
    et = ZoneInfo("America/New_York")
    trade_dt = datetime.fromisoformat(trade_time_et).replace(tzinfo=et)
    trade_utc = trade_dt.astimezone(UTC)
    available_utc = earliest_available_utc(model, cycle_init_utc)
    return available_utc <= trade_utc


def get_valid_models_at_time(trade_time_et: str, available_cycles: dict[str, datetime]) -> list[str]:
    """Return model names whose cycle was available by the ET trade time."""
    valid = []
    for model, cycle_utc in available_cycles.items():
        if is_vintage_valid(model, cycle_utc, trade_time_et):
            valid.append(model)
    return valid
