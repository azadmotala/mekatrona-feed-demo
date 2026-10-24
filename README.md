# MekaTrona feed demo

This repo tries out one way to get your own data onto a MekaTrona Dial. You write a recipe that
says where the number you want sits in a web API's JSON. Every 10 minutes a GitHub Action reads
that API, pulls the number out, and publishes a small file the Dial reads over HTTPS.

The recipe page is at https://azadmotala.github.io/mekatrona-feed-demo/. The demo feed is
Johannesburg's current temperature from [Open-Meteo](https://open-meteo.com/), at
https://azadmotala.github.io/mekatrona-feed-demo/feeds/jhb-temp.json.

It's a test. GitHub can start scheduled runs late and stops them after 60 days without a commit,
and Pages can take up to 10 minutes to serve a new file. Everything in here is public.

## What the Dial reads

```json
{"schema": "analog-dial/feed@0",
 "dial": {"name": "Johannesburg", "unit": "°C", "rangeLo": 0, "rangeHi": 40,
          "setHand": 22, "good": "mid", "zoneMode": "mark",
          "value": "26.0", "at": "2026-10-24T09:45:00Z", "staleAfterS": 3600}}
```

`value` is the reading as text, with the source's own digits, or `null` when the source has no
reading. It can be up to 12 characters: extra decimal places get rounded off, and an exponent like
`1.5e3` is written out as `1500`. The Dial does its own rounding to suit its scale.

`at` is when the source says it took the reading, in UTC. Add `staleAfterS` and the Dial shows
`STALE` with the reading's age once it's older than that, even while the file keeps being
republished.

The rest is optional: `name`, `unit`, `rangeLo` and `rangeHi` (0 and 100 if you leave them out),
and `setHand` for a target. With a target, the Dial's ring lights round it as the web dial's does:
`good` says which way is good (`high`, `low`, or `mid` for near the target), and `zoneMode`
(`fixed` or `mark`), `zoneLow` and `zoneHigh` (per cent of the scale, 33 and 66 if left out) say
where the colours change. With no target the ring stays dark.

## Recipes

```json
{"schema": "mekatrona/recipe@0",
 "source": "https://api.open-meteo.com/v1/forecast?latitude=-26.2&longitude=28.04&current=temperature_2m",
 "pick": {"value": "current.temperature_2m", "unit": "current_units.temperature_2m",
          "at": "current.time", "atOffset": "utc_offset_seconds"},
 "dial": {"name": "Johannesburg", "rangeLo": 0, "rangeHi": 40, "setHand": 22, "good": "mid",
          "zoneMode": "mark", "staleAfterS": 3600}}
```

`pick` points at fields in the source's JSON, and `data[0].price` and `data.0.price` both work.
`dial` holds fields that go into the file as you typed them.

If the source gives a time without a time zone, tell the recipe how to read it: `atOffset` names
the field that holds its UTC offset in seconds, or `"atZone": "UTC"` says it's already UTC. With
neither, the run refuses the time instead of guessing.

You don't have to write recipes by hand. On the recipe page, paste an API address, click the
fields you want, fill in the dial's name and scale, and it opens GitHub with `recipes/<name>.json`
ready to save.

## What each run does

[`convert.py`](convert.py) uses only Python's standard library. For each recipe it fetches the
source and writes `feeds/<name>.json`. If a source is down, or its answer is missing a field the
recipe points at, the run publishes the previous file again, unchanged, if there is one. Its `at`
stays the same, so the Dial can tell the reading is getting old. `feeds/index.json` records what
happened to each feed on the last run.

Run the tests with `python3 -m unittest -v test_convert.py`.

Weather data by [Open-Meteo.com](https://open-meteo.com/), under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Their free API is for non-commercial use.
