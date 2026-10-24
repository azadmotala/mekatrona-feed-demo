#!/usr/bin/env python3
"""Turn each recipe in recipes/ into the one small file a MekaTrona Dial reads.

A recipe names a web address that answers with JSON, and where in that answer the reading, its
unit and its time are. Each run fetches every recipe's source, picks those out, and writes
feeds/<recipe name>.json in the dial's format, analog-dial/feed@0:

    {"schema": "analog-dial/feed@0",
     "dial": {"name": "Johannesburg", "unit": "°C", "rangeLo": 0, "rangeHi": 40,
              "value": "26.0", "at": "2026-10-24T09:45:00Z", "staleAfterS": 3600}}

The value is copied as the source wrote it, digit for digit, as text: a number read into a float
and printed back can change its last digit, and the dial rounds the text itself. "at" is when the
source says it took the reading, in UTC, so a dial can tell an old reading from a fresh one even
while this file keeps being published.

When a source cannot be read, or answers with something the recipe cannot find, the file
published last time is published again unchanged, and its "at" lets the dial show how old it is.
Nothing is ever made up to fill a gap.

    python3 convert.py --out _site --published https://<owner>.github.io/<repo>

Standard library only.
"""

import argparse
import datetime
import decimal
import json
import os
import re
import sys
import urllib.request

FEED_SCHEMA = "analog-dial/feed@0"
RECIPE_SCHEMA = "mekatrona/recipe@0"
TIMEOUT_S = 10
MAX_REPLY_BYTES = 1_000_000
FEED_MAX_BYTES = 2048           # the largest file the dial accepts
VALUE_MAX_CHARS = 12            # the longest value the dial accepts
USER_AGENT = "mekatrona-feed-demo (+https://github.com/azadmotala/mekatrona-feed-demo)"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
DECIMAL_RE = re.compile(r"^[+-]?[0-9]+(\.[0-9]+)?$")
DIAL_TEXT = ("name", "unit")
DIAL_NUMBERS = ("rangeLo", "rangeHi", "setHand")
DIAL_CHOICES = {"good": ("high", "low", "mid"), "zoneMode": ("fixed", "mark")}
DIAL_PERCENT = ("zoneLow", "zoneHigh")
DIAL_ORDER = ("name", "unit", "rangeLo", "rangeHi", "setHand", "good", "zoneMode", "zoneLow", "zoneHigh")


class Refused(Exception):
    """Why a recipe could not be turned into a feed this time, in words for the run's log."""


class Raw(str):
    """A JSON number exactly as the source wrote it."""


def parse_json(text):
    """JSON with every number kept as its own text (Raw), never a float."""
    return json.loads(text, parse_float=Raw, parse_int=Raw, parse_constant=lambda c: Raw(c))


# ---- finding things in the source's answer ----

_STEP = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def steps(path):
    """current.temperature_2m -> ["current", "temperature_2m"]; data[0].price and data.0.price
    -> ["data", 0, "price"]."""
    if not isinstance(path, str) or not path.strip():
        raise Refused("a path is empty")
    out = []
    for part in path.split("."):
        if not part:
            raise Refused("the path %r has an empty step" % path)
        found = _STEP.findall(part)
        if "".join(k or "[%s]" % i for k, i in found) != part:
            raise Refused("the path %r cannot be read" % path)
        for key, index in found:
            out.append(int(index) if index else (int(key) if key.isdigit() else key))
    return out


def pick(doc, path):
    here = doc
    for step in steps(path):
        if isinstance(here, list) and isinstance(step, int) and 0 <= step < len(here):
            here = here[step]
        elif isinstance(here, dict) and str(step) in here:
            here = here[str(step)]
        else:
            raise Refused("the source's answer has nothing at %s" % path)
    return here


# ---- turning what was found into the dial's fields ----

def plain_decimal(text):
    """A number's text with any exponent written out: 1.5e3 -> 1500, 2E-4 -> 0.0002. Digits are
    never added or dropped otherwise."""
    if DECIMAL_RE.match(text):
        return text
    try:
        d = decimal.Decimal(text)
    except decimal.InvalidOperation:
        raise Refused("the value %r is not a number" % text)
    if not d.is_finite():
        raise Refused("the value %r is not a number" % text)
    return format(d, "f")


def fit_value(text):
    """The value as at most VALUE_MAX_CHARS characters: places after the point are rounded off,
    half away from zero, only when there are too many to fit. A whole part too long to fit is
    refused rather than cut."""
    if len(text) <= VALUE_MAX_CHARS:
        return text
    sign = "-" if text.startswith("-") else ""
    whole, _, frac = text.lstrip("+-").partition(".")
    room = VALUE_MAX_CHARS - len(sign) - len(whole) - 1     # places that fit after the point
    if room < 1:
        if len(sign) + len(whole) > VALUE_MAX_CHARS:
            raise Refused("the value %s is too long for the dial (%d characters at most)" % (text, VALUE_MAX_CHARS))
        room = 0
    with decimal.localcontext() as ctx:
        ctx.prec = 100              # enough that quantize never runs out of digits
        q = decimal.Decimal(1).scaleb(-room)
        out = format(decimal.Decimal(text).quantize(q, rounding=decimal.ROUND_HALF_UP), "f")
    if out.startswith("-") and decimal.Decimal(out) == 0:
        out = out[1:]
    return out


def value_of(found):
    if found is None:
        return None                     # the source has no reading: the dial shows NO DATA
    if isinstance(found, Raw):
        return fit_value(plain_decimal(str(found)))
    if isinstance(found, str) and DECIMAL_RE.match(found.strip()):
        return fit_value(found.strip())
    raise Refused("the value found is %s, not a number" % (json.dumps(found, ensure_ascii=False)[:40],))


def utc_text(t):
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def at_of(found, offset_s):
    """When the source took the reading, as 2026-10-24T09:45:00Z. found is an ISO 8601 time, or
    seconds (or milliseconds) since 1970. A time that names no zone needs offset_s, its offset
    from UTC in seconds, which the recipe says how to find; without it the time is refused rather
    than guessed."""
    if isinstance(found, Raw):
        n = decimal.Decimal(str(found))
        if n > 100_000_000_000:          # milliseconds
            n = n / 1000
        return utc_text(datetime.datetime.fromtimestamp(int(n), datetime.timezone.utc))
    if not isinstance(found, str):
        raise Refused("the reading time found is not a time")
    try:
        t = datetime.datetime.fromisoformat(found.strip())
    except ValueError:
        raise Refused("the reading time %r is not an ISO 8601 time" % found)
    if t.tzinfo is None:
        if offset_s is None:
            raise Refused("the reading time %r names no zone; the recipe must say its UTC offset" % found)
        t = t.replace(tzinfo=datetime.timezone(datetime.timedelta(seconds=offset_s)))
    return utc_text(t)


def offset_of(found):
    if isinstance(found, Raw) and re.match(r"^-?[0-9]+$", str(found)) and abs(int(found)) < 86400:
        return int(found)
    raise Refused("the UTC offset found is not a whole number of seconds")


# ---- one recipe ----

def check_recipe(recipe):
    if not isinstance(recipe, dict) or recipe.get("schema") != RECIPE_SCHEMA:
        raise Refused("not a recipe (schema %s)" % RECIPE_SCHEMA)
    src = recipe.get("source")
    if not isinstance(src, str) or not src.startswith("https://"):
        raise Refused("the source must be an https:// address")
    picks = recipe.get("pick")
    if not isinstance(picks, dict) or "value" not in picks:
        raise Refused("the recipe must say where the value is (pick.value)")
    for key in picks:
        if key not in ("value", "unit", "at", "atOffset"):
            raise Refused("pick.%s is not something a recipe can pick" % key)
        steps(picks[key])
    dial = recipe.get("dial", {})
    if not isinstance(dial, dict):
        raise Refused("dial must be an object")
    for key, v in dial.items():
        if key in DIAL_TEXT:
            if not isinstance(v, str):
                raise Refused("dial.%s must be text" % key)
        elif key in DIAL_NUMBERS:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise Refused("dial.%s must be a number" % key)
        elif key in DIAL_CHOICES:
            if v not in DIAL_CHOICES[key]:
                raise Refused("dial.%s must be one of %s" % (key, ", ".join(DIAL_CHOICES[key])))
        elif key in DIAL_PERCENT:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
                raise Refused("dial.%s must be a per cent of the scale, 0 to 100" % key)
        elif key == "staleAfterS":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise Refused("dial.staleAfterS must be a number of seconds above 0")
        else:
            raise Refused("dial.%s is not a field the dial reads" % key)
    if "unit" in dial and "unit" in picks:
        raise Refused("the unit is both given (dial.unit) and picked (pick.unit); keep one")
    if "rangeLo" in dial and "rangeHi" in dial and not dial["rangeLo"] < dial["rangeHi"]:
        raise Refused("dial.rangeLo must be below dial.rangeHi")
    if recipe.get("atZone") not in (None, "UTC"):
        raise Refused('atZone can only be "UTC"')


def feed_from(recipe, answer):
    """The feed document for a recipe and the text of its source's answer."""
    try:
        doc = parse_json(answer)
    except ValueError:
        raise Refused("the source did not answer with JSON")
    picks, given = recipe["pick"], recipe.get("dial", {})
    dial = {}
    for key in DIAL_ORDER:
        if key in given:
            dial[key] = given[key]
        elif key == "unit" and "unit" in picks:
            unit = pick(doc, picks["unit"])
            if not isinstance(unit, str):
                raise Refused("the unit found is not text")
            dial["unit"] = unit
    dial["value"] = value_of(pick(doc, picks["value"]))
    if "at" in picks:
        offset = None
        if "atOffset" in picks:
            offset = offset_of(pick(doc, picks["atOffset"]))
        elif recipe.get("atZone") == "UTC":
            offset = 0
        dial["at"] = at_of(pick(doc, picks["at"]), offset)
    if "staleAfterS" in given:
        dial["staleAfterS"] = given["staleAfterS"]
    feed = {"schema": FEED_SCHEMA, "dial": dial}
    if len(dump(feed)) > FEED_MAX_BYTES:
        raise Refused("the file would be over %d bytes" % FEED_MAX_BYTES)
    return feed


def dump(feed):
    return json.dumps(feed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def is_feed(body):
    try:
        doc = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        return False
    return isinstance(doc, dict) and doc.get("schema") == FEED_SCHEMA and isinstance(doc.get("dial"), dict)


# ---- the network ----

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        body = r.read(MAX_REPLY_BYTES + 1)
    if len(body) > MAX_REPLY_BYTES:
        raise Refused("the source's answer is over %d bytes" % MAX_REPLY_BYTES)
    return body


def read_source(url, get):
    try:
        body = get(url)
    except Refused:
        raise
    except Exception as e:      # a source that is down, slow or refusing: named, never fatal
        raise Refused("the source could not be read (%s)" % (getattr(e, "reason", None) or type(e).__name__))
    try:
        return body.decode("utf-8")
    except UnicodeError:
        raise Refused("the source's answer is not UTF-8 text")


# ---- a run ----

def run(recipes_dir, out_dir, published=None, get=fetch, now=None):
    """Convert every recipe. Returns the run's summary, which is also written to feeds/index.json."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    feeds_dir = os.path.join(out_dir, "feeds")
    os.makedirs(feeds_dir, exist_ok=True)
    summary = {"ranAt": utc_text(now), "feeds": []}
    for fn in sorted(os.listdir(recipes_dir)):
        if not fn.endswith(".json"):
            continue
        name = fn[:-5]
        entry = {"id": name, "file": "feeds/%s.json" % name}
        try:
            if not NAME_RE.match(name):
                raise Refused("a recipe's file name must be lower-case letters, digits and dashes")
            with open(os.path.join(recipes_dir, fn), encoding="utf-8") as f:
                try:
                    recipe = json.load(f)
                except ValueError:
                    raise Refused("the recipe is not JSON")
            check_recipe(recipe)
            entry["name"] = recipe.get("dial", {}).get("name", "")
            feed = feed_from(recipe, read_source(recipe["source"], get))
            body = dump(feed)
            entry.update(result="new", value=feed["dial"]["value"], at=feed["dial"].get("at"))
        except Refused as why:
            entry["why"] = str(why)
            body = None
            if published:
                try:
                    old = get("%s/feeds/%s.json" % (published.rstrip("/"), name))
                    if is_feed(old):
                        body = old
                except Exception:
                    pass
            if body is not None:
                d = json.loads(body.decode("utf-8"))["dial"]
                entry.update(result="kept", value=d.get("value"), at=d.get("at"))
            else:
                entry["result"] = "none"
        if body is not None:
            with open(os.path.join(feeds_dir, name + ".json"), "wb") as f:
                f.write(body)
        summary["feeds"].append(entry)
        print("%-24s %-4s %s" % (name, entry["result"], entry.get("why") or "%s at %s" % (entry["value"], entry["at"])))
    with open(os.path.join(feeds_dir, "index.json"), "wb") as f:
        f.write(json.dumps(summary, ensure_ascii=False, indent=1).encode("utf-8"))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--recipes", default="recipes")
    ap.add_argument("--out", default="_site")
    ap.add_argument("--published", default=None, help="the published site, for re-publishing a feed whose source failed")
    a = ap.parse_args(argv)
    run(a.recipes, a.out, a.published)
    return 0


if __name__ == "__main__":
    sys.exit(main())
