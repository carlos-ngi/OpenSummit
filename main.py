import os
import datetime as dt

import requests
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

LAT = float(os.getenv("LAT", "46.75"))
LON = float(os.getenv("LON", "9.95"))

MIN_NIGHT_C = float(os.getenv("MIN_NIGHT_C", "8"))
MAX_DAY_C = float(os.getenv("MAX_DAY_C", "26"))
MAX_WIND_KMH = float(os.getenv("MAX_WIND_KMH", "25"))
MAX_RAIN_MM = float(os.getenv("MAX_RAIN_MM", "0.2"))

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN missing in .env")
if CHANNEL_ID <= 0:
    raise SystemExit("CHANNEL_ID missing/invalid in .env")


def next_weekend() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    days_to_sat = (5 - today.weekday()) % 7  # Sat=5
    sat = today + dt.timedelta(days=days_to_sat)
    sun = sat + dt.timedelta(days=1)
    return sat, sun


def fetch_open_meteo_daily(lat: float, lon: float) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max"
        "&timezone=Europe%2FZurich"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def pick_day(daily: dict, date_: dt.date) -> dict | None:
    times = daily.get("time", [])
    iso = date_.isoformat()
    if iso not in times:
        return None
    idx = times.index(iso)

    def at(key: str):
        arr = daily.get(key, [])
        return arr[idx] if idx < len(arr) else None

    return {
        "date": iso,
        "tmin": at("temperature_2m_min"),
        "tmax": at("temperature_2m_max"),
        "rain": at("precipitation_sum"),
        "wind": at("wind_speed_10m_max"),
        "gust": at("wind_gusts_10m_max"),
    }


def eval_day(day: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for k in ("tmin", "tmax", "rain", "wind"):
        if day.get(k) is None:
            reasons.append(f"missing {k}")
    if reasons:
        return False, reasons

    tmin = float(day["tmin"])
    tmax = float(day["tmax"])
    rain = float(day["rain"])
    wind = float(day["wind"])
    gust = day.get("gust")
    w = max(wind, float(gust)) if gust is not None else wind

    if tmin < MIN_NIGHT_C:
        reasons.append(f"night too cold ({tmin:.1f}°C < {MIN_NIGHT_C:.1f}°C)")
    if tmax > MAX_DAY_C:
        reasons.append(f"day too hot ({tmax:.1f}°C > {MAX_DAY_C:.1f}°C)")
    if rain > MAX_RAIN_MM:
        reasons.append(f"rain ({rain:.1f}mm > {MAX_RAIN_MM:.1f}mm)")
    if w > MAX_WIND_KMH:
        reasons.append(f"too windy ({w:.0f} km/h > {MAX_WIND_KMH:.0f} km/h)")

    return (len(reasons) == 0), reasons


def fmt_day(day: dict) -> str:
    gust = day["gust"]
    gust_s = f"{float(gust):.0f} km/h" if gust is not None else "n/a"
    return (
        f"Tmin {float(day['tmin']):.1f}°C, Tmax {float(day['tmax']):.1f}°C, "
        f"Rain {float(day['rain']):.1f}mm, Wind {float(day['wind']):.0f} km/h, Gust {gust_s}"
    )


def decide_weekend() -> tuple[str, str]:
    data = fetch_open_meteo_daily(LAT, LON)
    daily = data.get("daily", {})
    sat, sun = next_weekend()

    sat_day = pick_day(daily, sat)
    sun_day = pick_day(daily, sun)

    if sat_day is None or sun_day is None:
        return (
            "🔴 NO-GO",
            f"Forecast does not include weekend dates ({sat.isoformat()} / {sun.isoformat()}).",
        )

    sat_ok, sat_reasons = eval_day(sat_day)
    sun_ok, sun_reasons = eval_day(sun_day)

    decision = "🟢 GO" if (sat_ok and sun_ok) else "🔴 NO-GO"

    lines = [
        f"**OpenSummit weekend check** (both days must pass)",
        f"Location: `{LAT:.4f}, {LON:.4f}`",
        f"Rules: night ≥ {MIN_NIGHT_C:.1f}°C | day ≤ {MAX_DAY_C:.1f}°C | rain ≤ {MAX_RAIN_MM:.1f}mm | wind/gust ≤ {MAX_WIND_KMH:.0f} km/h",
        "",
        f"**Saturday {sat_day['date']}** — {fmt_day(sat_day)}",
        f"**Sunday {sun_day['date']}** — {fmt_day(sun_day)}",
    ]

    if decision.startswith("🔴"):
        if sat_reasons:
            lines.append("\n❌ Saturday: " + "; ".join(sat_reasons))
        if sun_reasons:
            lines.append("❌ Sunday: " + "; ".join(sun_reasons))
    else:
        lines.append("\n✅ Looks suitable for camping/hiking (by your rules).")

    lines.append("\nSource: Open-Meteo (fast MVP).")

    return decision, "\n".join(lines)


intents = discord.Intents.default()
client = discord.Client(intents=intents)

_posted_once = False


@client.event
async def on_ready():
    global _posted_once
    if _posted_once:
        return
    _posted_once = True

    print(f"Logged in as {client.user}")

    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("Channel not found. Check CHANNEL_ID and bot permissions.")
        return

    decision, body = decide_weekend()
    embed = discord.Embed(title=decision, description=body)

    await channel.send(embed=embed)


client.run(TOKEN)
import os
import json
import time
import datetime as dt
from dataclasses import dataclass
from typing import Any

import requests
import discord
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

# ---- Config ----
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))

DEFAULT_LAT = float(os.getenv("LAT", "46.75"))
DEFAULT_LON = float(os.getenv("LON", "9.95"))
DEFAULT_LOCATION_NAME = os.getenv("DEFAULT_LOCATION_NAME", "Joeriseen")

LOCATIONS_FILE = "locations.json"
STATE_FILE = "state.json"


@dataclass
class Thresholds:
    min_night_c: float
    max_day_c: float
    max_wind_kmh: float
    max_rain_mm: float


TH = Thresholds(
    min_night_c=float(os.getenv("MIN_NIGHT_C", "8")),
    max_day_c=float(os.getenv("MAX_DAY_C", "26")),
    max_wind_kmh=float(os.getenv("MAX_WIND_KMH", "25")),
    max_rain_mm=float(os.getenv("MAX_RAIN_MM", "0.2")),
)

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN missing in .env")
if CHANNEL_ID <= 0:
    raise SystemExit("CHANNEL_ID missing/invalid in .env")


# ---- Helpers: files ----
def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_locations() -> dict:
    """
    locations.json schema:
    {
      "locations": [
        {"name":"Joeriseen","lat":46.75,"lon":9.95}
      ]
    }
    """
    data = _load_json(LOCATIONS_FILE, {"locations": []})
    if not data.get("locations"):
        data = {"locations": [{"name": DEFAULT_LOCATION_NAME, "lat": DEFAULT_LAT, "lon": DEFAULT_LON}]}
        _save_json(LOCATIONS_FILE, data)
    return data


def load_state() -> dict:
    """
    state.json schema:
    {
      "last": {
        "<location_name>": {"weekend":"YYYY-MM-DD","decision":"GO|NO-GO","ts":...}
      }
    }
    """
    return _load_json(STATE_FILE, {"last": {}})


def save_state(state: dict) -> None:
    _save_json(STATE_FILE, state)


# ---- Weather logic (Open-Meteo quick MVP) ----
def next_weekend_dates() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    days_to_sat = (5 - today.weekday()) % 7  # Sat=5
    sat = today + dt.timedelta(days=days_to_sat)
    sun = sat + dt.timedelta(days=1)
    return sat, sun


def fetch_open_meteo_daily(lat: float, lon: float) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max"
        "&timezone=Europe%2FZurich"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def pick_day(daily: dict, date_: dt.date) -> dict | None:
    times = daily.get("time", [])
    iso = date_.isoformat()
    if iso not in times:
        return None
    idx = times.index(iso)

    def at(key: str):
        arr = daily.get(key, [])
        return arr[idx] if idx < len(arr) else None

    return {
        "date": iso,
        "tmin": at("temperature_2m_min"),
        "tmax": at("temperature_2m_max"),
        "rain": at("precipitation_sum"),
        "wind": at("wind_speed_10m_max"),
        "gust": at("wind_gusts_10m_max"),
    }


def eval_day(day: dict, th: Thresholds) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for k in ("tmin", "tmax", "rain", "wind"):
        if day.get(k) is None:
            reasons.append(f"missing {k}")
    if reasons:
        return False, reasons

    tmin = float(day["tmin"])
    tmax = float(day["tmax"])
    rain = float(day["rain"])
    wind = float(day["wind"])
    gust = day.get("gust")
    w = max(wind, float(gust)) if gust is not None else wind

    if tmin < th.min_night_c:
        reasons.append(f"night too cold ({tmin:.1f}°C < {th.min_night_c:.1f}°C)")
    if tmax > th.max_day_c:
        reasons.append(f"day too hot ({tmax:.1f}°C > {th.max_day_c:.1f}°C)")
    if rain > th.max_rain_mm:
        reasons.append(f"rain ({rain:.1f}mm > {th.max_rain_mm:.1f}mm)")
    if w > th.max_wind_kmh:
        reasons.append(f"too windy ({w:.0f} km/h > {th.max_wind_kmh:.0f} km/h)")

    return (len(reasons) == 0), reasons


def fmt_day(day: dict) -> str:
    gust = day["gust"]
    gust_s = f"{float(gust):.0f} km/h" if gust is not None else "n/a"
    return (
        f"Tmin {float(day['tmin']):.1f}°C, Tmax {float(day['tmax']):.1f}°C, "
        f"Rain {float(day['rain']):.1f}mm, Wind {float(day['wind']):.0f} km/h, Gust {gust_s}"
    )


def decide_weekend_for_location(name: str, lat: float, lon: float, th: Thresholds) -> dict:
    data = fetch_open_meteo_daily(lat, lon)
    daily = data.get("daily", {})
    sat, sun = next_weekend_dates()

    sat_day = pick_day(daily, sat)
    sun_day = pick_day(daily, sun)

    weekend_key = sat.isoformat()

    if sat_day is None or sun_day is None:
        return {
            "location": name,
            "lat": lat,
            "lon": lon,
            "weekend": weekend_key,
            "decision": "NO-GO",
            "text": f"Forecast missing weekend dates for {name}.",
            "reasons": ["forecast_missing_dates"],
        }

    sat_ok, sat_reasons = eval_day(sat_day, th)
    sun_ok, sun_reasons = eval_day(sun_day, th)
    decision = "GO" if (sat_ok and sun_ok) else "NO-GO"

    lines = [
        f"Location: **{name}** (`{lat:.4f}, {lon:.4f}`)",
        f"Weekend: **{sat_day['date']}** + **{sun_day['date']}** (both required)",
        f"Rules: night ≥ {th.min_night_c:.1f}°C | day ≤ {th.max_day_c:.1f}°C | rain ≤ {th.max_rain_mm:.1f}mm | wind/gust ≤ {th.max_wind_kmh:.0f} km/h",
        "",
        f"**Saturday** — {fmt_day(sat_day)}",
        f"**Sunday** — {fmt_day(sun_day)}",
    ]

    reasons = []
    if decision == "NO-GO":
        if sat_reasons:
            reasons += [f"Sat: {r}" for r in sat_reasons]
        if sun_reasons:
            reasons += [f"Sun: {r}" for r in sun_reasons]
        lines.append("")
        lines.append("❌ Reasons: " + " | ".join(reasons))

    return {
        "location": name,
        "lat": lat,
        "lon": lon,
        "weekend": weekend_key,
        "decision": decision,
        "text": "\n".join(lines),
        "reasons": reasons,
    }


# ---- Discord bot ----
intents = discord.Intents.default()
intents.message_content = True  # needed for !addloc commands
client = discord.Client(intents=intents)


async def send_status(channel: discord.abc.Messageable, title: str, body: str) -> None:
    embed = discord.Embed(title=title, description=body)
    embed.set_footer(text="Source: Open-Meteo (MVP).")
    await channel.send(embed=embed)


def normalize_name(s: str) -> str:
    return s.strip()


def find_location(locations: list[dict], name: str) -> dict | None:
    name_l = name.lower()
    for loc in locations:
        if str(loc.get("name", "")).lower() == name_l:
            return loc
    return None


@tasks.loop(minutes=POLL_MINUTES)
async def poll_weather():
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("Channel not found (CHANNEL_ID wrong or missing permissions).")
        return

    loc_data = load_locations()
    state = load_state()
    last = state.setdefault("last", {})

    for loc in loc_data.get("locations", []):
        name = str(loc["name"])
        lat = float(loc["lat"])
        lon = float(loc["lon"])

        try:
            result = decide_weekend_for_location(name, lat, lon, TH)
        except Exception as e:
            # Fail-safe: don't crash the loop
            print(f"[{name}] fetch/eval failed: {e}")
            continue

        wk = result["weekend"]
        dec = result["decision"]  # GO / NO-GO

        prev = last.get(name)

        # We only send when:
        # - it becomes GO (NO-GO -> GO or first time GO)
        # - it was GO and flips to NO-GO => alarm
        should_send = False
        alarm = False

        if prev is None or prev.get("weekend") != wk:
            # new weekend: only send if GO
            if dec == "GO":
                should_send = True
        else:
            prev_dec = prev.get("decision")
            if prev_dec != dec:
                if dec == "GO":
                    should_send = True
                elif prev_dec == "GO" and dec != "GO":
                    should_send = True
                    alarm = True

        if should_send:
            title = f"🟢 GO — {name}" if dec == "GO" else f"🚨 ALERT: NO-GO — {name}"
            if alarm:
                title = f"🚨 ALERT: conditions worsened — {name}"
            await send_status(channel, title, result["text"])

        # Update state
        last[name] = {
            "weekend": wk,
            "decision": dec,
            "ts": int(time.time()),
        }

    save_state(state)


@client.event
async def on_ready():
    print(f"Logged in as {client.user} | poll={POLL_MINUTES}min")
    if not poll_weather.is_running():
        poll_weather.start()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_ID:
        return

    content = (message.content or "").strip()
    if not content.startswith("!"):
        return

    # Commands:
    # !addloc Name 46.75 9.95
    # !remloc Name
    # !listloc
    # !check  (force immediate evaluation now)
    parts = content.split()
    cmd = parts[0].lower()

    loc_data = load_locations()
    locations = loc_data.get("locations", [])

    if cmd == "!listloc":
        if not locations:
            await message.channel.send("No locations configured.")
            return
        lines = [f"- **{loc['name']}** (`{float(loc['lat']):.4f}, {float(loc['lon']):.4f}`)" for loc in locations]
        await message.channel.send("**Locations:**\n" + "\n".join(lines))
        return

    if cmd == "!addloc":
        if len(parts) < 4:
            await message.channel.send("Usage: `!addloc Name LAT LON`")
            return
        name = normalize_name(parts[1])
        try:
            lat = float(parts[2])
            lon = float(parts[3])
        except ValueError:
            await message.channel.send("LAT/LON must be numbers. Example: `!addloc Joeriseen 46.75 9.95`")
            return

        if find_location(locations, name):
            await message.channel.send(f"Location `{name}` already exists. Use `!remloc {name}` first.")
            return

        locations.append({"name": name, "lat": lat, "lon": lon})
        loc_data["locations"] = locations
        _save_json(LOCATIONS_FILE, loc_data)

        await message.channel.send(f"Added location: **{name}** (`{lat:.4f}, {lon:.4f}`)")

        # Optional: evaluate immediately and send ONLY if GO
        try:
            result = decide_weekend_for_location(name, lat, lon, TH)
            if result["decision"] == "GO":
                await send_status(message.channel, f"🟢 GO — {name}", result["text"])
        except Exception as e:
            await message.channel.send(f"Note: evaluation failed right now: `{e}`")

        return

    if cmd == "!remloc":
        if len(parts) < 2:
            await message.channel.send("Usage: `!remloc Name`")
            return
        name = normalize_name(parts[1])
        loc = find_location(locations, name)
        if not loc:
            await message.channel.send(f"Location `{name}` not found.")
            return
        locations = [l for l in locations if str(l.get("name", "")).lower() != name.lower()]
        loc_data["locations"] = locations
        _save_json(LOCATIONS_FILE, loc_data)

        # also remove from state
        state = load_state()
        state.get("last", {}).pop(name, None)
        save_state(state)

        await message.channel.send(f"Removed location: `{name}`")
        return

    if cmd == "!check":
        await message.channel.send("Running check now…")
        await poll_weather()  # run once immediately
        return

    await message.channel.send("Commands: `!addloc Name LAT LON`, `!remloc Name`, `!listloc`, `!check`")


client.run(TOKEN)
