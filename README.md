# OpenSummit

A Discord bot that keeps an eye on the weather for your favourite spots and tells you when the next weekend is good for a hike or a night outside.

It doesn't spam the forecast every day. It posts when a weekend starts to look good, and again if it falls apart.

```
🟢 Good weekend at Jöriseen
🌤️ Sat 31.10.          🌤️ Sun 1.11.
Mostly clear           Mostly clear
🌡️ 9 to 20 °C          🌡️ 10 to 21 °C
💧 0.0 mm (10%)        💧 0.0 mm (5%)
💨 10 km/h, gusts 20   💨 12 km/h, gusts 25
✅ fine                ✅ fine
```

## How it decides

For every spot the bot gets the forecast from [Open-Meteo](https://open-meteo.com/) (free, no API key). The forecast is corrected to the real height of the spot, so a summit gets summit weather and not the weather of the valley below.

A day is good when all of these hold:

| Rule | Default |
|---|---|
| coldest temperature at least | 8 °C |
| warmest temperature at most | 26 °C |
| rain at most | 0.2 mm |
| chance of rain at most | 50 % |
| wind and gusts below | 25 km/h |
| no thunderstorms | |

Then the weekend gets one of these:

- 🟢 **Good weekend**: both days are fine, go camping
- 🟡 **Only Saturday / Sunday**: good for a day trip
- 🔴 **Not this weekend**: never posted on its own, only if a weekend that looked good gets worse

The bot checks every hour and remembers what it already posted, so you only hear about changes.

## Commands

| Command | Who | |
|---|---|---|
| `/weekend` | everyone | forecast for all spots (or just one) right now |
| `/spot list` | everyone | all spots with a map link |
| `/spot add` | admins | add a spot, just start typing a place name or paste coordinates |
| `/spot remove` | admins | remove a spot |
| `/settings show` | admins | current rules and channel |
| `/settings rules` | admins | change the rules, e.g. `/settings rules wind_kmh:35` |
| `/settings channel` | admins | where the bot posts (default: the channel you run it in) |
| `/settings reset` | admins | rules back to the defaults |

"Admins" means everyone with the *Manage Server* permission. You can change that per command under Server Settings → Integrations.

## Setup

**1. Create the bot**

1. Make a new application in the [Discord Developer Portal](https://discord.com/developers/applications), go to *Bot* and copy the token.
2. Under *OAuth2 → URL Generator* pick the scopes `bot` and `applications.commands` and the permissions *View Channels*, *Send Messages* and *Embed Links*. Open the link and add the bot to your server.

**2. Run it**

With Docker:

```sh
git clone https://github.com/carlos-ngi/OpenSummit.git
cd OpenSummit
cp .env.example .env    # put your token in there
docker compose up -d
```

Or with Python 3.11 or newer:

```sh
git clone https://github.com/carlos-ngi/OpenSummit.git
cd OpenSummit
python3 -m venv .venv
source .venv/bin/activate
pip install .
cp .env.example .env    # put your token in there
opensummit
```

**3. In Discord**

Run `/settings channel` in the channel where the bot should post and add your first spot with `/spot add`. Done.

Slash commands can take a while to show up the first time. If you put your server ID in `GUILD_ID` they show up right away.

## Configuration

Everything except the token can also be changed in Discord. The values in `.env` are only the starting point.

| Variable | Default | |
|---|---|---|
| `DISCORD_TOKEN` | | required |
| `CHANNEL_ID` | | channel to post in, `/settings channel` overrides it |
| `GUILD_ID` | | your server ID, for instant slash commands |
| `POLL_MINUTES` | 60 | how often to check |
| `DATA_DIR` | `data` | where `data.json` is stored |
| `MIN_NIGHT_C` `MAX_DAY_C` `MAX_RAIN_MM` `MAX_RAIN_CHANCE` `MAX_WIND_KMH` | see above | default rules |

## Coming from the old version

The old single `main.py` is gone. Your `locations.json` is picked up automatically on the first start if you start the bot in the same folder. The `!` commands and the old `/addloc`, `/remloc`, `/listloc` and `/check` are replaced by the commands above. `LAT`, `LON` and `DEFAULT_LOCATION_NAME` aren't used anymore, add spots with `/spot add` instead.

## Development

```sh
pip install -e ".[dev]"
pytest
ruff check .
```

## Good to know

- "The weekend" is always the next Saturday and Sunday. On a Sunday that's already the next one.
- Weather in the mountains is hard to predict, especially a week ahead. Use this as a hint and check MeteoSwiss or your local weather service before you go. This is not a safety tool.

## License

MIT, see [LICENSE](LICENSE).
