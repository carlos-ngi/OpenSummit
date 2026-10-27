import datetime as dt

import discord

from .weather import Day, Rules, Spot, Status, Weekend

COLORS = {
    Status.GO: discord.Color.green(),
    Status.SATURDAY: discord.Color.gold(),
    Status.SUNDAY: discord.Color.gold(),
    Status.NO_GO: discord.Color.red(),
}

HEADLINES = {
    Status.GO: "🟢 Good weekend",
    Status.SATURDAY: "🟡 Only Saturday looks good",
    Status.SUNDAY: "🟡 Only Sunday looks good",
    Status.NO_GO: "🔴 Not this weekend",
}


def map_url(spot: Spot) -> str:
    return (
        f"https://www.openstreetmap.org/?mlat={spot.lat:.5f}&mlon={spot.lon:.5f}#map=14/{spot.lat:.5f}/{spot.lon:.5f}"
    )


def _day_field(label: str, day: Day | None) -> tuple[str, str]:
    if day is None:
        return label, "no forecast yet"

    name = f"{day.icon} {label} {day.date.day}.{day.date.month}."
    if None in (day.tmin, day.tmax, day.rain, day.wind):
        return name, "no forecast yet"

    lines = [
        day.summary.capitalize(),
        f"🌡️ {day.tmin:.0f} to {day.tmax:.0f} °C",
        f"💧 {day.rain:.1f} mm" + (f" ({day.rain_chance}%)" if day.rain_chance is not None else ""),
        f"💨 {day.wind:.0f} km/h" + (f", gusts {day.gust:.0f}" if day.gust is not None else ""),
        "",
        "✅ fine" if day.ok else "❌ " + ", ".join(day.problems),
    ]
    return name, "\n".join(lines)


def weekend_embed(w: Weekend, what: str | None = None) -> discord.Embed:
    title = f"{HEADLINES[w.status]} at {w.spot.name}"
    description = None

    if what == "worse":
        title = f"⚠️ {w.spot.name}: the weekend got worse"
        description = f"Now: **{HEADLINES[w.status]}**"
    elif w.status in (Status.SATURDAY, Status.SUNDAY):
        description = "Good for a day trip, not for a night out."

    embed = discord.Embed(
        title=title,
        description=description,
        url=map_url(w.spot),
        color=COLORS[w.status],
        timestamp=dt.datetime.now(dt.UTC),
    )
    for label, day in (("Sat", w.saturday), ("Sun", w.sunday)):
        name, value = _day_field(label, day)
        embed.add_field(name=name, value=value, inline=True)

    footer = f"{w.spot.lat:.3f}, {w.spot.lon:.3f}"
    if w.elevation is not None:
        footer += f" · {w.elevation:.0f} m"
    embed.set_footer(text=footer + " · forecast by Open-Meteo")
    return embed


def rules_embed(rules: Rules, channel_id: int | None, poll_minutes: int) -> discord.Embed:
    embed = discord.Embed(title="Settings", color=discord.Color.blurple())
    embed.add_field(
        name="A day is good when",
        value=(
            f"night is at least **{rules.min_night_c:g} °C**\n"
            f"day is at most **{rules.max_day_c:g} °C**\n"
            f"rain is at most **{rules.max_rain_mm:g} mm**\n"
            f"chance of rain is at most **{rules.max_rain_chance}%**\n"
            f"wind and gusts stay below **{rules.max_wind_kmh:g} km/h**\n"
            "and there are no thunderstorms"
        ),
        inline=False,
    )
    embed.add_field(name="Channel", value=f"<#{channel_id}>" if channel_id else "not set", inline=True)
    embed.add_field(name="Checks", value=f"every {poll_minutes} min", inline=True)
    return embed
