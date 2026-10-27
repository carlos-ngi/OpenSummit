import os
from dataclasses import dataclass
from pathlib import Path

from .weather import Rules


class ConfigError(Exception):
    pass


def _int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{name} has to be a number, got {value!r}") from None


def _float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigError(f"{name} has to be a number, got {value!r}") from None


@dataclass
class Config:
    token: str
    channel_id: int | None
    guild_id: int | None
    poll_minutes: int
    data_dir: Path
    default_rules: Rules


def load() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError("DISCORD_TOKEN is not set, see .env.example")

    poll = _int("POLL_MINUTES", 60)
    if poll < 5:
        raise ConfigError("POLL_MINUTES should be at least 5, the forecast only updates about every hour")

    d = Rules()
    rules = Rules(
        min_night_c=_float("MIN_NIGHT_C", d.min_night_c),
        max_day_c=_float("MAX_DAY_C", d.max_day_c),
        max_rain_mm=_float("MAX_RAIN_MM", d.max_rain_mm),
        max_rain_chance=_int("MAX_RAIN_CHANCE", d.max_rain_chance),
        max_wind_kmh=_float("MAX_WIND_KMH", d.max_wind_kmh),
    )

    return Config(
        token=token,
        channel_id=_int("CHANNEL_ID"),
        guild_id=_int("GUILD_ID"),
        poll_minutes=poll,
        data_dir=Path(os.getenv("DATA_DIR", "data")),
        default_rules=rules,
    )
