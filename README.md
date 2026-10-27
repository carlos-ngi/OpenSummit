# OpenSummit

Small Discord bot that checks the weather forecast for the next weekend and posts in a channel when it looks good enough for a hike or a night out camping.

It doesn't send you the forecast every day. It only posts when a weekend turns into a **GO**, and again if a GO weekend gets worse and becomes a **NO-GO**.

## How it decides

For every location the bot gets the daily forecast for Saturday and Sunday from [Open-Meteo](https://open-meteo.com/) (free, no API key). Both days have to pass all of these:

| Setting | Default | Meaning |
|---|---|---|
| `MIN_NIGHT_C` | 8 | lowest temperature of the day must be at least this |
| `MAX_DAY_C` | 26 | highest temperature must not be above this |
| `MAX_RAIN_MM` | 0.2 | total rain of the day in mm |
| `MAX_WIND_KMH` | 25 | max wind speed, gusts count too |

If one of them fails it's a NO-GO and the embed lists the reasons.

The check runs every `POLL_MINUTES` (default 10). The last decision per location is saved in `state.json`, so you don't get the same message twice.

## Setup

1. Create an application and a bot in the [Discord Developer Portal](https://discord.com/developers/applications) and copy the token.
2. Invite the bot with the scopes `bot` and `applications.commands`. It needs *View Channel*, *Send Messages* and *Embed Links* in the channel you want the messages in.
3. Turn on developer mode in Discord, right click the channel and copy its ID.
4. Then:

```sh
git clone https://github.com/carlos-ngi/OpenSummit.git
cd OpenSummit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # put in your token and channel id
python main.py
```

Python 3.10 or newer is needed.

On the first start a `locations.json` with the default location from `.env` is created. After that you manage the locations with the commands below.

## Commands

| Command | |
|---|---|
| `/listloc` | show all locations |
| `/addloc name lat lon` | add a location, it gets checked right away |
| `/remloc name` | remove a location |
| `/check` | run the check now instead of waiting for the next poll |

It can take a moment after the first start until Discord shows the slash commands.

## Notes

- The weekend is always the next Saturday + Sunday. On a Sunday that already means the next weekend.
- Mountain forecasts can be quite off, so use it as a hint and still check MeteoSwiss or similar before you go. This is not a safety tool.

## Ideas

- thresholds per location
- ping a role on GO
- Saturday-only / Sunday-only option

## License

MIT, see [LICENSE](LICENSE).
