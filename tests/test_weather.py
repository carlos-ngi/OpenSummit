import datetime as dt

import pytest

from opensummit.weather import Rules, Spot, Status, change, evaluate, parse_coords, weekend_dates

SPOT = Spot("Test", 46.75, 9.95)
FRIDAY = dt.date(2026, 10, 30)

GOOD = {
    "weather_code": 1,
    "temperature_2m_min": 10,
    "temperature_2m_max": 20,
    "precipitation_sum": 0,
    "precipitation_probability_max": 10,
    "wind_speed_10m_max": 10,
    "wind_gusts_10m_max": 20,
}


def forecast(sat=None, sun=None):
    sat = {**GOOD, **(sat or {})}
    sun = {**GOOD, **(sun or {})}
    daily = {"time": ["2026-10-31", "2026-11-01"]}
    for key in GOOD:
        daily[key] = [sat[key], sun[key]]
    return {"daily": daily, "elevation": 1820}


def run(sat=None, sun=None, rules=None):
    return evaluate(SPOT, forecast(sat, sun), rules or Rules(), today=FRIDAY)


@pytest.mark.parametrize(
    "today, sat",
    [
        (dt.date(2026, 10, 26), dt.date(2026, 10, 31)),  # monday
        (dt.date(2026, 10, 30), dt.date(2026, 10, 31)),  # friday
        (dt.date(2026, 10, 31), dt.date(2026, 10, 31)),  # saturday
        (dt.date(2026, 11, 1), dt.date(2026, 11, 7)),  # sunday -> next weekend
    ],
)
def test_weekend_dates(today, sat):
    assert weekend_dates(today) == (sat, sat + dt.timedelta(days=1))


def test_good_weekend():
    w = run()
    assert w.status == Status.GO
    assert w.key == "2026-10-31"
    assert w.elevation == 1820


def test_only_saturday():
    w = run(sun={"precipitation_sum": 4})
    assert w.status == Status.SATURDAY
    assert w.sunday.problems == ["rain (4.0 mm)"]


def test_only_sunday():
    assert run(sat={"temperature_2m_min": 2}).status == Status.SUNDAY


def test_gusts_count_as_wind():
    w = run(sat={"wind_gusts_10m_max": 40})
    assert w.status == Status.SUNDAY
    assert "too windy (40 km/h)" in w.saturday.problems


def test_thunderstorm_is_never_ok():
    assert "thunderstorms" in run(sat={"weather_code": 95}).saturday.problems


def test_rain_chance():
    assert run(sat={"precipitation_probability_max": 80}).status == Status.SUNDAY
    # some models have no probability, that shouldn't block a GO
    assert run(sat={"precipitation_probability_max": None}).status == Status.GO


def test_rules_are_used():
    assert run(sat={"temperature_2m_max": 28}).status == Status.SUNDAY
    assert run(sat={"temperature_2m_max": 28}, rules=Rules(max_day_c=30)).status == Status.GO


def test_missing_data():
    w = run(sat={"temperature_2m_min": None})
    assert w.saturday.problems == ["no forecast data yet"]
    assert w.status == Status.SUNDAY


def test_weekend_not_in_forecast():
    w = evaluate(SPOT, forecast(), Rules(), today=dt.date(2026, 11, 1))
    assert w.saturday is None and w.sunday is None
    assert w.status == Status.NO_GO


def test_change():
    go = run()
    no_go = run(sat={"precipitation_sum": 5}, sun={"precipitation_sum": 5})
    sat_only = run(sun={"precipitation_sum": 5})
    sun_only = run(sat={"precipitation_sum": 5})

    def prev(w, weekend="2026-10-31"):
        return {"weekend": weekend, "status": w.status.value}

    assert change(None, go) == "new"
    assert change(None, no_go) is None
    assert change(prev(go, "2026-10-24"), go) == "new"
    assert change(prev(go), go) is None
    assert change(prev(no_go), sat_only) == "better"
    assert change(prev(sat_only), go) == "better"
    assert change(prev(go), no_go) == "worse"
    assert change(prev(sat_only), no_go) == "worse"
    assert change(prev(sat_only), sun_only) == "changed"
    assert change(prev(no_go), no_go) is None
    # state from the old version used "decision" instead of "status"
    assert change({"weekend": "2026-10-31", "decision": "GO"}, go) == "new"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("46.75, 9.95", (46.75, 9.95)),
        ("46.75 9.95", (46.75, 9.95)),
        ("-33.9;18.4", (-33.9, 18.4)),
        ("95, 10", None),
        ("Davos", None),
        ("", None),
    ],
)
def test_parse_coords(text, expected):
    assert parse_coords(text) == expected
