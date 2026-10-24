# MekaTrona feed demo

A test of one way to bring your own data to a MekaTrona Dial: a **recipe** says where a reading is
in the JSON some web address answers with, and a GitHub Action turns it, every 10 minutes, into the
one small file the dial reads over HTTPS.

**Recipe page:** https://azadmotala.github.io/mekatrona-feed-demo/
**Demo feed:** https://azadmotala.github.io/mekatrona-feed-demo/feeds/jhb-temp.json, the current
temperature in Johannesburg from [Open-Meteo](https://open-meteo.com/).

This is a test, not a service: scheduled runs can start late, GitHub stops them after 60 days
without a commit, and everything here is public.

## The dial's file

```json
{"schema": "analog-dial/feed@0",
 "dial": {"name": "Johannesburg", "unit": "°C", "rangeLo": 0, "rangeHi": 40,
          "value": "26.0", "at": "2026-10-24T09:45:00Z", "staleAfterS": 3600}}
```

- `value` is decimal text, copied from the source digit for digit (at most 12 characters), or
  `null` when the source has no reading. The dial rounds it to suit its scale.
- `at` is when the source says it took the reading, in UTC. With `staleAfterS`, the dial shows
  `STALE` and the reading's age once it is older than that, even while the file keeps being published.
- `name`, `unit`, `rangeLo`, `rangeHi` (0 and 100 if left out) and `setHand` (a target) are optional.

## A recipe

```json
{"schema": "mekatrona/recipe@0",
 "source": "https://api.open-meteo.com/v1/forecast?latitude=-26.2&longitude=28.04&current=temperature_2m",
 "pick": {"value": "current.temperature_2m", "unit": "current_units.temperature_2m",
          "at": "current.time", "atOffset": "utc_offset_seconds"},
 "dial": {"name": "Johannesburg", "rangeLo": 0, "rangeHi": 40, "staleAfterS": 3600}}
```

`pick` holds paths into the source's answer (`data[0].price` and `data.0.price` both work); `dial`
holds fields written into the file as given. A reading time that names no zone needs `atOffset`
(a field holding its UTC offset in seconds) or `"atZone": "UTC"`; it is never guessed. The page
builds a recipe by clicking fields in a live answer, then opens GitHub to save it as
`recipes/<name>.json`.

## Each run

[`convert.py`](convert.py) (Python standard library only) fetches every recipe's source and writes
`feeds/<name>.json`. If a source cannot be read, or its answer does not have what the recipe points
at, last run's file is published again unchanged, and its `at` lets the dial show how old it is.
`feeds/index.json` says what each run did. Tests: `python3 -m unittest -v test_convert.py`.

Weather data by [Open-Meteo.com](https://open-meteo.com/), under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), free for non-commercial use.
