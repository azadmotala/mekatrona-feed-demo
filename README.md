# MekaTrona feed demo

This repo tries out one way to get your own data onto a MekaTrona Dial. You write a recipe that
says where the number you want sits in a web API's JSON. A GitHub Action reads that API, pulls the
number out, and publishes a small file the Dial reads over HTTPS.

The recipe page is at https://azadmotala.github.io/mekatrona-feed-demo/. There are three demo
feeds, each at `https://azadmotala.github.io/mekatrona-feed-demo/feeds/<name>.json`:

- `jhb-temp`: the temperature in Johannesburg, from [Open-Meteo](https://open-meteo.com/)
- `jhb-pm25`: fine dust (PM2.5) in Johannesburg, from Open-Meteo's air quality API
- `btc-price`: the Bitcoin price in rand, from [CoinGecko](https://www.coingecko.com/en/api)

There's also a mock of a step-by-step setup at
https://azadmotala.github.io/mekatrona-feed-demo/wizard.html. You pick what the Dial should show,
choose a city or a coin, and set up the dial with a live preview of how it will look. It doesn't
save anything, and its last step, pairing with a Dial, isn't built yet.

It's a test. The Action runs whenever something is pushed to main, and it's set to run every 10
minutes as well, but GitHub runs that schedule far less often. On 24 October 2026, the repo's first
day, it had run twice by 17:30 UTC: at 13:45 and 17:00. So between pushes a feed can go hours
without a new reading. A feed with `staleAfterS` shows STALE on the Dial once its reading is older
than that. GitHub also stops scheduled runs after 60 days without a commit, and Pages can take up
to 10 minutes to serve a new file. Everything in here is public.

## What the Dial reads

This is `feeds/jhb-pm25.json` as one run published it:

```json
{"schema": "analog-dial/feed@0",
 "dial": {"name": "Jhb PM2.5", "unit": "μg/m³", "rangeLo": 0, "rangeHi": 50,
          "setHand": 15, "good": "low", "zoneMode": "mark",
          "value": "17.3", "at": "2026-10-24T14:00:00Z", "staleAfterS": 3600}}
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

This is `recipes/jhb-pm25.json`, the recipe behind that feed:

```json
{"schema": "mekatrona/recipe@0",
 "source": "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=-26.2&longitude=28.04&current=pm2_5",
 "pick": {"value": "current.pm2_5", "unit": "current_units.pm2_5",
          "at": "current.time", "atOffset": "utc_offset_seconds"},
 "dial": {"name": "Jhb PM2.5", "rangeLo": 0, "rangeHi": 50, "setHand": 15, "good": "low",
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

Weather and air quality data by [Open-Meteo.com](https://open-meteo.com/), under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Their free API is for non-commercial use.
Price data provided by [CoinGecko](https://www.coingecko.com/en/api).
