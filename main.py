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
