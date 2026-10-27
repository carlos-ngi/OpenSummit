import asyncio
import logging
from dataclasses import replace

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from . import __version__
from .config import Config
from .embeds import map_url, rules_embed, weekend_embed
from .storage import Store
from .weather import Spot, Weekend, change, evaluate, fetch_forecast, parse_coords, search_places

log = logging.getLogger(__name__)

NETWORK_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError)


class OpenSummit(discord.Client):
    def __init__(self, cfg: Config):
        super().__init__(intents=discord.Intents.default())
        self.cfg = cfg
        self.store = Store(cfg.data_dir / "data.json", cfg.default_rules)
        self.tree = app_commands.CommandTree(self)
        self.session: aiohttp.ClientSession | None = None
        self.lock = asyncio.Lock()

    @property
    def channel_id(self) -> int | None:
        # set with /settings channel, otherwise CHANNEL_ID from .env
        return self.store.channel_id or self.cfg.channel_id

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": f"OpenSummit/{__version__} (+https://github.com/carlos-ngi/OpenSummit)"},
        )

        for command in (weekend_cmd, spot_group, settings_group):
            self.tree.add_command(command)
        self.tree.error(on_command_error)

        if self.cfg.guild_id:
            # syncing to one server shows the commands right away, global sync can take a while
            guild = discord.Object(id=self.cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("synced %d commands", len(synced))

        self.poll.change_interval(minutes=self.cfg.poll_minutes)
        self.poll.start()

    async def close(self) -> None:
        self.poll.cancel()
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("logged in as %s, watching %d spots", self.user, len(self.store.spots))
        if not self.channel_id:
            log.warning("no channel set yet, use /settings channel in Discord or set CHANNEL_ID")

    @tasks.loop(minutes=60)
    async def poll(self) -> None:
        await self.check(list(self.store.spots))

    @poll.before_loop
    async def before_poll(self) -> None:
        await self.wait_until_ready()

    async def weekend_for(self, spot: Spot) -> Weekend:
        forecast = await fetch_forecast(self.session, spot)
        return evaluate(spot, forecast, self.store.rules)

    async def target_channel(self) -> discord.abc.Messageable | None:
        if not self.channel_id:
            return None
        channel = self.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self.channel_id)
            except discord.HTTPException as e:
                log.warning("can't access channel %s: %s", self.channel_id, e)
                return None
        return channel

    async def check(self, spots: list[Spot]) -> dict[str, bool]:
        """Check the spots and post if something changed. Returns which spots got a message."""
        channel = await self.target_channel()
        posted = {}
        async with self.lock:
            for spot in spots:
                try:
                    weekend = await self.weekend_for(spot)
                except NETWORK_ERRORS as e:
                    log.warning("[%s] forecast failed: %r", spot.name, e)
                    continue

                if channel is None:
                    # don't save anything, so the message still goes out once a channel is set
                    continue

                what = change(self.store.last.get(spot.name), weekend)
                posted[spot.name] = False
                if what:
                    try:
                        await channel.send(embed=weekend_embed(weekend, what))
                        posted[spot.name] = True
                    except discord.HTTPException as e:
                        log.warning("[%s] could not post: %s", spot.name, e)
                        continue  # try again on the next check

                self.store.last[spot.name] = {"weekend": weekend.key, "status": weekend.status.value}
                log.info("[%s] %s (%s)", spot.name, weekend.status.value, what or "no change")
            self.store.save()
        return posted


def bot_of(interaction: discord.Interaction) -> OpenSummit:
    return interaction.client  # type: ignore[return-value]


async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    original = getattr(error, "original", error)
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the **Manage Server** permission for that."
    elif isinstance(original, NETWORK_ERRORS):
        msg = "Couldn't reach the weather service, try again in a minute."
    else:
        log.error("command /%s failed", interaction.command and interaction.command.qualified_name, exc_info=error)
        msg = "Something went wrong, check the bot log."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def spot_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [
        app_commands.Choice(name=s.name, value=s.name)
        for s in bot_of(interaction).store.spots
        if current in s.name.lower()
    ][:25]


# --- /weekend ---


@app_commands.command(name="weekend", description="Show the forecast for the coming weekend")
@app_commands.describe(spot="Only show this spot")
@app_commands.autocomplete(spot=spot_autocomplete)
@app_commands.guild_only()
async def weekend_cmd(interaction: discord.Interaction, spot: str | None = None):
    bot = bot_of(interaction)
    if spot:
        found = bot.store.find(spot)
        if found is None:
            await interaction.response.send_message(f"There's no spot called `{spot}`.", ephemeral=True)
            return
        spots = [found]
    else:
        spots = list(bot.store.spots)

    if not spots:
        await interaction.response.send_message("No spots yet, add one with `/spot add`.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    results = await asyncio.gather(*(bot.weekend_for(s) for s in spots), return_exceptions=True)
    embeds = []
    for s, result in zip(spots, results, strict=True):
        if isinstance(result, NETWORK_ERRORS):
            log.warning("[%s] forecast failed: %r", s.name, result)
            embeds.append(discord.Embed(title=s.name, description="Forecast not available right now."))
        elif isinstance(result, BaseException):
            raise result
        else:
            embeds.append(weekend_embed(result))

    # discord allows max 10 embeds per message
    for i in range(0, len(embeds), 10):
        await interaction.followup.send(embeds=embeds[i : i + 10])


# --- /spot ---

spot_group = app_commands.Group(name="spot", description="Places the bot keeps an eye on", guild_only=True)


@spot_group.command(name="list", description="Show all spots")
async def spot_list(interaction: discord.Interaction):
    spots = bot_of(interaction).store.spots
    if not spots:
        await interaction.response.send_message("No spots yet, add one with `/spot add`.", ephemeral=True)
        return
    lines = [f"• [{s.name}]({map_url(s)}) `{s.lat:.4f}, {s.lon:.4f}`" for s in spots]
    await interaction.response.send_message("\n".join(lines), ephemeral=True, suppress_embeds=True)


async def resolve_place(bot: OpenSummit, place: str) -> tuple[str, float, float] | None:
    # autocomplete gives us "geo:lat,lon|name"
    if place.startswith("geo:"):
        coords, _, label = place[4:].partition("|")
        if found := parse_coords(coords):
            return label or coords, *found
    if found := parse_coords(place):
        return f"{found[0]:.4f}, {found[1]:.4f}", *found
    results = await search_places(bot.session, place, count=1)
    if results:
        r = results[0]
        return r["name"], r["latitude"], r["longitude"]
    return None


def place_label(r: dict) -> str:
    parts = [r.get("name"), r.get("admin1"), r.get("country_code")]
    label = ", ".join(p for p in parts if p)
    if r.get("elevation") is not None:
        label += f" ({r['elevation']:.0f} m)"
    return label


@spot_group.command(name="add", description="Watch a new spot")
@app_commands.describe(
    place="Search a place, or enter coordinates like 46.75, 9.95",
    name="Name to show instead of the place name",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def spot_add(
    interaction: discord.Interaction,
    place: str,
    name: app_commands.Range[str, 1, 50] | None = None,
):
    bot = bot_of(interaction)
    await interaction.response.defer(ephemeral=True, thinking=True)

    found = await resolve_place(bot, place)
    if found is None:
        await interaction.followup.send(f"Couldn't find `{place}`. Try another name or use coordinates.")
        return

    label, lat, lon = found
    name = (name or label).strip()
    if bot.store.find(name):
        await interaction.followup.send(f"`{name}` already exists, pick another name with the `name` option.")
        return

    spot = Spot(name, round(lat, 5), round(lon, 5))
    bot.store.spots.append(spot)
    bot.store.save()

    posted = await bot.check([spot])
    msg = f"Added **{name}**. I'll post when a weekend there looks good."
    if not bot.channel_id:
        msg += "\nThere's no channel set yet, use `/settings channel` so I know where to post."
    if posted.get(name):
        await interaction.followup.send(msg)
    else:
        # nothing was posted, so show the current outlook at least to the person who added it
        try:
            await interaction.followup.send(msg, embed=weekend_embed(await bot.weekend_for(spot)))
        except NETWORK_ERRORS:
            await interaction.followup.send(msg)


@spot_add.autocomplete("place")
async def place_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.strip()
    if coords := parse_coords(current):
        return [app_commands.Choice(name=f"Coordinates {coords[0]:.4f}, {coords[1]:.4f}", value=current)]
    if len(current) < 2:
        return []
    try:
        # discord gives us 3 seconds to answer
        results = await asyncio.wait_for(search_places(bot_of(interaction).session, current), 2.5)
    except NETWORK_ERRORS:
        return []
    return [
        app_commands.Choice(
            name=place_label(r)[:100],
            value=f"geo:{r['latitude']:.5f},{r['longitude']:.5f}|{r['name']}"[:100],
        )
        for r in results
    ]


@spot_group.command(name="remove", description="Stop watching a spot")
@app_commands.describe(spot="The spot to remove")
@app_commands.autocomplete(spot=spot_autocomplete)
@app_commands.checks.has_permissions(manage_guild=True)
async def spot_remove(interaction: discord.Interaction, spot: str):
    bot = bot_of(interaction)
    found = bot.store.find(spot)
    if found is None:
        await interaction.response.send_message(f"There's no spot called `{spot}`.", ephemeral=True)
        return

    async with bot.lock:
        bot.store.spots.remove(found)
        bot.store.last.pop(found.name, None)
        bot.store.save()
    await interaction.response.send_message(f"Removed **{found.name}**.", ephemeral=True)


# --- /settings ---

settings_group = app_commands.Group(
    name="settings",
    description="Bot settings",
    guild_only=True,
    default_permissions=discord.Permissions(manage_guild=True),
)


@settings_group.command(name="show", description="Show the current settings")
async def settings_show(interaction: discord.Interaction):
    bot = bot_of(interaction)
    embed = rules_embed(bot.store.rules, bot.channel_id, bot.cfg.poll_minutes)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@settings_group.command(name="rules", description="Change what counts as good weather")
@app_commands.describe(
    night_min="Coldest acceptable night in °C",
    day_max="Hottest acceptable day in °C",
    rain_mm="Max rain per day in mm",
    rain_chance="Max chance of rain in %",
    wind_kmh="Max wind and gusts in km/h",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def settings_rules(
    interaction: discord.Interaction,
    night_min: app_commands.Range[float, -30, 30] | None = None,
    day_max: app_commands.Range[float, 0, 45] | None = None,
    rain_mm: app_commands.Range[float, 0, 100] | None = None,
    rain_chance: app_commands.Range[int, 0, 100] | None = None,
    wind_kmh: app_commands.Range[float, 0, 200] | None = None,
):
    bot = bot_of(interaction)
    changes = {
        "min_night_c": night_min,
        "max_day_c": day_max,
        "max_rain_mm": rain_mm,
        "max_rain_chance": rain_chance,
        "max_wind_kmh": wind_kmh,
    }
    changes = {k: v for k, v in changes.items() if v is not None}
    if changes:
        async with bot.lock:
            bot.store.rules = replace(bot.store.rules, **changes)
            bot.store.save()
    embed = rules_embed(bot.store.rules, bot.channel_id, bot.cfg.poll_minutes)
    msg = "Saved, the next check uses the new rules." if changes else "Nothing changed. Here are the current rules:"
    await interaction.response.send_message(msg, embed=embed, ephemeral=True)


@settings_group.command(name="channel", description="Choose where the bot posts")
@app_commands.describe(channel="Leave empty to use this channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def settings_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    bot = bot_of(interaction)
    channel = channel or interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("That only works with a normal text channel.", ephemeral=True)
        return

    perms = channel.permissions_for(channel.guild.me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        await interaction.response.send_message(
            f"I need *View Channel*, *Send Messages* and *Embed Links* in {channel.mention}.", ephemeral=True
        )
        return

    async with bot.lock:
        bot.store.channel_id = channel.id
        # forget what was posted, so the current good weekends get posted in the new channel
        bot.store.last.clear()
        bot.store.save()
    await interaction.response.send_message(f"I'll post in {channel.mention} from now on.", ephemeral=True)
    await bot.check(list(bot.store.spots))


@settings_group.command(name="reset", description="Reset the weather rules to the defaults")
@app_commands.checks.has_permissions(manage_guild=True)
async def settings_reset(interaction: discord.Interaction):
    bot = bot_of(interaction)
    async with bot.lock:
        bot.store.rules = replace(bot.cfg.default_rules)
        bot.store.save()
    embed = rules_embed(bot.store.rules, bot.channel_id, bot.cfg.poll_minutes)
    await interaction.response.send_message("Rules are back to the defaults.", embed=embed, ephemeral=True)
