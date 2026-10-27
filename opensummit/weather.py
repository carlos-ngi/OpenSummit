"""Forecast fetching and the actual GO / NO-GO logic.

Everything except the two fetch functions is plain code without I/O,
so it can be tested without network.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import StrEnum

import aiohttp

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

DAILY_VARS = (
    "weather_code",
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
)

THUNDERSTORM_CODES = {95, 96, 99}

# WMO weather codes -> (icon, text)
WEATHER = {
    0: ("☀️", "clear"),
    1: ("🌤️", "mostly clear"),
    2: ("⛅", "partly cloudy"),
    3: ("☁️", "overcast"),
    45: ("🌫️", "fog"),
    48: ("🌫️", "rime fog"),
    51: ("🌦️", "light drizzle"),
    53: ("🌦️", "drizzle"),
    55: ("🌧️", "heavy drizzle"),
    56: ("🌧️", "freezing drizzle"),
    57: ("🌧️", "freezing drizzle"),
    61: ("🌦️", "light rain"),
    63: ("🌧️", "rain"),
    65: ("🌧️", "heavy rain"),
    66: ("🌧️", "freezing rain"),
    67: ("🌧️", "freezing rain"),
    71: ("🌨️", "light snow"),
    73: ("🌨️", "snow"),
    75: ("❄️", "heavy snow"),
    77: ("🌨️", "snow grains"),
    80: ("🌦️", "rain showers"),
    81: ("🌧️", "rain showers"),
    82: ("🌧️", "violent showers"),
    85: ("🌨️", "snow showers"),
    86: ("❄️", "snow showers"),
    95: ("⛈️", "thunderstorm"),
    96: ("⛈️", "thunderstorm with hail"),
    99: ("⛈️", "thunderstorm with hail"),
}


@dataclass
class Rules:
    min_night_c: float = 8
    max_day_c: float = 26
    max_rain_mm: float = 0.2
    max_rain_chance: int = 50
    max_wind_kmh: float = 25


@dataclass
class Spot:
    name: str
    lat: float
    lon: float


@dataclass
class Day:
    date: dt.date
    code: int | None
    tmin: float | None
    tmax: float | None
    rain: float | None
    rain_chance: int | None
    wind: float | None
    gust: float | None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def icon(self) -> str:
        return WEATHER.get(self.code, ("❔", ""))[0]

    @property
    def summary(self) -> str:
        return WEATHER.get(self.code, ("", "unknown"))[1]


class Status(StrEnum):
    GO = "go"
    SATURDAY = "saturday"
    SUNDAY = "sunday"
    NO_GO = "no-go"

    @property
    def rank(self) -> int:
        return {"go": 2, "saturday": 1, "sunday": 1, "no-go": 0}[self.value]


@dataclass
class Weekend:
    spot: Spot
    saturday: Day | None
    sunday: Day | None
    status: Status
    elevation: float | None = None  # height Open-Meteo used for the forecast

    @property
    def key(self) -> str:
        # identifies the weekend, used to know if we already notified about it
        day = self.saturday or self.sunday
        return day.date.isoformat() if day else ""


def weekend_dates(today: dt.date) -> tuple[dt.date, dt.date]:
    """Next Saturday and Sunday. On a Saturday that's today and tomorrow,
    on a Sunday it's already the next weekend."""
    sat = today + dt.timedelta(days=(5 - today.weekday()) % 7)
    return sat, sat + dt.timedelta(days=1)


def check_day(day: Day, rules: Rules) -> list[str]:
    if None in (day.tmin, day.tmax, day.rain, day.wind):
        return ["no forecast data yet"]

    problems = []
    if day.code in THUNDERSTORM_CODES:
        problems.append("thunderstorms")
    if day.tmin < rules.min_night_c:
        problems.append(f"too cold at night ({day.tmin:.0f} °C)")
    if day.tmax > rules.max_day_c:
        problems.append(f"too hot ({day.tmax:.0f} °C)")
    if day.rain > rules.max_rain_mm:
        problems.append(f"rain ({day.rain:.1f} mm)")
    elif day.rain_chance is not None and day.rain_chance > rules.max_rain_chance:
        # only mention the chance if the amount itself wasn't already too much
        problems.append(f"{day.rain_chance}% chance of rain")
    wind = max(day.wind, day.gust or 0)
    if wind > rules.max_wind_kmh:
        problems.append(f"too windy ({wind:.0f} km/h)")
    return problems


def _day_from(daily: dict, date: dt.date) -> Day | None:
    times = daily.get("time", [])
    if date.isoformat() not in times:
        return None
    i = times.index(date.isoformat())

    def get(key):
        values = daily.get(key) or []
        return values[i] if i < len(values) else None

    return Day(
        date=date,
        code=get("weather_code"),
        tmin=get("temperature_2m_min"),
        tmax=get("temperature_2m_max"),
        rain=get("precipitation_sum"),
        rain_chance=get("precipitation_probability_max"),
        wind=get("wind_speed_10m_max"),
        gust=get("wind_gusts_10m_max"),
    )


def local_today(forecast: dict) -> dt.date:
    # "today" at the spot, not on the server
    offset = dt.timedelta(seconds=forecast.get("utc_offset_seconds", 0))
    return (dt.datetime.now(dt.UTC) + offset).date()


def evaluate(spot: Spot, forecast: dict, rules: Rules, today: dt.date | None = None) -> Weekend:
    today = today or local_today(forecast)
    sat_date, sun_date = weekend_dates(today)
    daily = forecast.get("daily", {})

    sat = _day_from(daily, sat_date)
    sun = _day_from(daily, sun_date)
    for day in (sat, sun):
        if day is not None:
            day.problems = check_day(day, rules)

    sat_ok = sat is not None and sat.ok
    sun_ok = sun is not None and sun.ok
    if sat_ok and sun_ok:
        status = Status.GO
    elif sat_ok:
        status = Status.SATURDAY
    elif sun_ok:
        status = Status.SUNDAY
    else:
        status = Status.NO_GO
    return Weekend(spot, sat, sun, status, forecast.get("elevation"))


def change(prev: dict | None, weekend: Weekend) -> str | None:
    """What changed compared to the last check.

    Returns "new" / "better" / "worse" / "changed", or None if there's
    nothing worth a message. A plain NO-GO is never announced, only when
    a weekend that looked good falls apart.
    """
    status = weekend.status
    if prev is None or prev.get("weekend") != weekend.key:
        return "new" if status != Status.NO_GO else None

    try:
        before = Status(prev.get("status"))
    except ValueError:
        return "new" if status != Status.NO_GO else None

    if status == before:
        return None
    if status.rank > before.rank:
        return "better"
    if status.rank < before.rank:
        return "worse"
    return "changed"  # saturday <-> sunday


_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_coords(text: str) -> tuple[float, float] | None:
    m = _COORDS.match(text)
    if not m:
        return None
    lat, lon = float(m[1]), float(m[2])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


async def fetch_forecast(session: aiohttp.ClientSession, spot: Spot) -> dict:
    params = {
        "latitude": spot.lat,
        "longitude": spot.lon,
        "daily": ",".join(DAILY_VARS),
        "timezone": "auto",
        # 8 days so the next Sunday is included even when it's Sunday today
        "forecast_days": 8,
    }
    # no elevation param: Open-Meteo then corrects the forecast to the real terrain height
    async with session.get(FORECAST_URL, params=params) as r:
        r.raise_for_status()
        return await r.json()


async def search_places(session: aiohttp.ClientSession, query: str, count: int = 5) -> list[dict]:
    params = {"name": query, "count": count, "language": "en", "format": "json"}
    async with session.get(GEOCODING_URL, params=params) as r:
        r.raise_for_status()
        data = await r.json()
    return data.get("results") or []
