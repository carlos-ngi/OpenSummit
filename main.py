# OpenSummit - Discord bot that tells you if the coming weekend is good
# enough for a hike / camping trip, based on the Open-Meteo forecast.

import asyncio
import datetime as dt
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord
import requests
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))

DEFAULT_LAT = float(os.getenv("LAT", "46.75"))
DEFAULT_LON = float(os.getenv("LON", "9.95"))
DEFAULT_LOCATION_NAME = os.getenv("DEFAULT_LOCATION_NAME", "Joeriseen")

DATA_DIR = Path(__file__).resolve().parent
LOCATIONS_FILE = DATA_DIR / "locations.json"
STATE_FILE = DATA_DIR / "state.json"

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is not set (see .env.example)")
if CHANNEL_ID <= 0:
    raise SystemExit("CHANNEL_ID is not set or invalid (see .env.example)")


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


# --- json files ---

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"could not read {path.name}: {e}")
        return default


def save_json(path: Path, data: Any) -> None:
    # write to a temp file first so a crash can't leave a half written file
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_locations() -> dict:
    # {"locations": [{"name": "Joeriseen", "lat": 46.75, "lon": 9.95}, ...]}
    data = load_json(LOCATIONS_FILE, {"locations": []})
    if not data.get("locations"):
        data = {"locations": [{"name": DEFAULT_LOCATION_NAME, "lat": DEFAULT_LAT, "lon": DEFAULT_LON}]}
        save_json(LOCATIONS_FILE, data)
    return data


def load_state() -> dict:
    # {"last": {"<name>": {"weekend": "YYYY-MM-DD", "decision": "GO", "ts": 1700000000}}}
    return load_json(STATE_FILE, {"last": {}})


def save_state(state: dict) -> None:
    save_json(STATE_FILE, state)


def find_location(locations: list[dict], name: str) -> dict | None:
    for loc in locations:
        if str(loc.get("name", "")).lower() == name.lower():
            return loc
    return None


# --- weather ---

def next_weekend_dates() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    days_to_sat = (5 - today.weekday()) % 7  # saturday = 5
    sat = today + dt.timedelta(days=days_to_sat)
    return sat, sat + dt.timedelta(days=1)


def fetch_forecast(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max",
        "timezone": "auto",
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def pick_day(daily: dict, date: dt.date) -> dict | None:
    times = daily.get("time", [])
    iso = date.isoformat()
    if iso not in times:
        return None
    i = times.index(iso)

    def get(key: str):
        values = daily.get(key, [])
        return values[i] if i < len(values) else None

    return {
        "date": iso,
        "tmin": get("temperature_2m_min"),
        "tmax": get("temperature_2m_max"),
        "rain": get("precipitation_sum"),
        "wind": get("wind_speed_10m_max"),
        "gust": get("wind_gusts_10m_max"),
    }


def eval_day(day: dict, th: Thresholds) -> tuple[bool, list[str]]:
    missing = [k for k in ("tmin", "tmax", "rain", "wind") if day.get(k) is None]
    if missing:
        return False, [f"missing {k}" for k in missing]

    tmin = float(day["tmin"])
    tmax = float(day["tmax"])
    rain = float(day["rain"])
    wind = float(day["wind"])
    # gusts count as wind if they are higher
    if day.get("gust") is not None:
        wind = max(wind, float(day["gust"]))

    reasons = []
    if tmin < th.min_night_c:
        reasons.append(f"night too cold ({tmin:.1f}°C < {th.min_night_c:.1f}°C)")
    if tmax > th.max_day_c:
        reasons.append(f"day too hot ({tmax:.1f}°C > {th.max_day_c:.1f}°C)")
    if rain > th.max_rain_mm:
        reasons.append(f"rain ({rain:.1f}mm > {th.max_rain_mm:.1f}mm)")
    if wind > th.max_wind_kmh:
        reasons.append(f"too windy ({wind:.0f} km/h > {th.max_wind_kmh:.0f} km/h)")

    return not reasons, reasons


def fmt_value(value, fmt: str, unit: str) -> str:
    return "n/a" if value is None else f"{float(value):{fmt}}{unit}"


def fmt_day(day: dict) -> str:
    return (
        f"Tmin {fmt_value(day['tmin'], '.1f', '°C')}, Tmax {fmt_value(day['tmax'], '.1f', '°C')}, "
        f"Rain {fmt_value(day['rain'], '.1f', 'mm')}, Wind {fmt_value(day['wind'], '.0f', ' km/h')}, "
        f"Gust {fmt_value(day['gust'], '.0f', ' km/h')}"
    )


def decide_weekend(name: str, lat: float, lon: float, th: Thresholds) -> dict:
    daily = fetch_forecast(lat, lon).get("daily", {})
    sat, sun = next_weekend_dates()
    sat_day = pick_day(daily, sat)
    sun_day = pick_day(daily, sun)

    if sat_day is None or sun_day is None:
        return {
            "weekend": sat.isoformat(),
            "decision": "NO-GO",
            "text": f"No forecast for the weekend ({sat} / {sun}) at **{name}**.",
        }

    sat_ok, sat_reasons = eval_day(sat_day, th)
    sun_ok, sun_reasons = eval_day(sun_day, th)
    decision = "GO" if sat_ok and sun_ok else "NO-GO"

    lines = [
        f"Location: **{name}** (`{lat:.4f}, {lon:.4f}`)",
        f"Weekend: **{sat_day['date']}** + **{sun_day['date']}** (both days have to pass)",
        f"Rules: night ≥ {th.min_night_c:.1f}°C | day ≤ {th.max_day_c:.1f}°C | "
        f"rain ≤ {th.max_rain_mm:.1f}mm | wind/gust ≤ {th.max_wind_kmh:.0f} km/h",
        "",
        f"**Saturday**: {fmt_day(sat_day)}",
        f"**Sunday**: {fmt_day(sun_day)}",
    ]
    reasons = [f"Sat: {r}" for r in sat_reasons] + [f"Sun: {r}" for r in sun_reasons]
    if reasons:
        lines += ["", "❌ " + " | ".join(reasons)]

    return {"weekend": sat.isoformat(), "decision": decision, "text": "\n".join(lines)}


def should_notify(prev: dict | None, weekend: str, decision: str) -> tuple[bool, bool]:
    """Returns (send, alarm).

    Only a GO is announced. If a weekend that was GO turns into NO-GO,
    an alarm goes out. Everything else stays quiet.
    """
    if prev is None or prev.get("weekend") != weekend:
        return decision == "GO", False

    prev_decision = prev.get("decision")
    if prev_decision == decision:
        return False, False
    if decision == "GO":
        return True, False
    if prev_decision == "GO":
        return True, True
    return False, False


# --- discord ---

intents = discord.Intents.default()  # slash commands only, no message content intent needed
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
check_lock = asyncio.Lock()


async def send_embed(channel: discord.abc.Messageable, title: str, body: str) -> None:
    embed = discord.Embed(title=title, description=body)
    embed.set_footer(text="Forecast: Open-Meteo")
    await channel.send(embed=embed)


async def check_location(channel: discord.abc.Messageable, loc: dict, last: dict) -> None:
    name = str(loc["name"])
    lat = float(loc["lat"])
    lon = float(loc["lon"])

    try:
        # requests is blocking, so run it outside the event loop
        result = await asyncio.to_thread(decide_weekend, name, lat, lon, TH)
    except Exception as e:
        print(f"[{name}] check failed: {e}")
        return

    send, alarm = should_notify(last.get(name), result["weekend"], result["decision"])
    if send:
        if alarm:
            title = f"🚨 Conditions got worse: {name}"
        else:
            title = f"🟢 GO: {name}"
        await send_embed(channel, title, result["text"])

    last[name] = {"weekend": result["weekend"], "decision": result["decision"], "ts": int(time.time())}


async def run_checks(channel: discord.abc.Messageable, only: str | None = None) -> None:
    # poll loop and /check could otherwise run at the same time and overwrite state.json
    async with check_lock:
        state = load_state()
        last = state.setdefault("last", {})
        for loc in load_locations()["locations"]:
            if only is not None and str(loc["name"]).lower() != only.lower():
                continue
            await check_location(channel, loc, last)
        save_state(state)


def get_channel() -> discord.abc.Messageable | None:
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("channel not found, check CHANNEL_ID and the bot permissions")
    return channel


@tasks.loop(minutes=POLL_MINUTES)
async def poll_task():
    channel = get_channel()
    if channel is not None:
        await run_checks(channel)


@client.event
async def on_ready():
    print(f"logged in as {client.user}, polling every {POLL_MINUTES} min")
    try:
        synced = await tree.sync()
        print(f"synced {len(synced)} slash commands")
    except discord.HTTPException as e:
        print(f"slash command sync failed: {e}")

    if not poll_task.is_running():
        poll_task.start()


@tree.command(name="listloc", description="List all locations")
async def listloc(interaction: discord.Interaction):
    locs = load_locations()["locations"]
    lines = [f"- **{l['name']}** (`{float(l['lat']):.4f}, {float(l['lon']):.4f}`)" for l in locs]
    await interaction.response.send_message("**Locations:**\n" + "\n".join(lines), ephemeral=True)


@tree.command(name="addloc", description="Add a location")
@app_commands.describe(name="Name of the location", lat="Latitude", lon="Longitude")
async def addloc(
    interaction: discord.Interaction,
    name: str,
    lat: app_commands.Range[float, -90, 90],
    lon: app_commands.Range[float, -180, 180],
):
    name = name.strip()
    if not name:
        await interaction.response.send_message("Name can't be empty.", ephemeral=True)
        return

    data = load_locations()
    if find_location(data["locations"], name):
        await interaction.response.send_message(f"`{name}` already exists.", ephemeral=True)
        return

    data["locations"].append({"name": name, "lat": float(lat), "lon": float(lon)})
    save_json(LOCATIONS_FILE, data)
    await interaction.response.send_message(f"Added **{name}** (`{lat:.4f}, {lon:.4f}`).", ephemeral=True)

    # check the new spot right away (posts only if it's a GO)
    channel = get_channel()
    if channel is not None:
        await run_checks(channel, only=name)


@tree.command(name="remloc", description="Remove a location")
@app_commands.describe(name="Name of the location")
async def remloc(interaction: discord.Interaction, name: str):
    data = load_locations()
    loc = find_location(data["locations"], name.strip())
    if loc is None:
        await interaction.response.send_message(f"`{name}` not found.", ephemeral=True)
        return

    data["locations"].remove(loc)
    save_json(LOCATIONS_FILE, data)

    async with check_lock:
        state = load_state()
        state.get("last", {}).pop(loc["name"], None)
        save_state(state)

    await interaction.response.send_message(f"Removed `{loc['name']}`.", ephemeral=True)


@tree.command(name="check", description="Run a weather check now")
async def check(interaction: discord.Interaction):
    await interaction.response.send_message("Checking…", ephemeral=True)
    channel = get_channel()
    if channel is not None:
        await run_checks(channel)


client.run(TOKEN)
