"""Checks for convert.py: python3 -m unittest -v test_convert.py

No network: every source is a fake that answers from memory. The Open-Meteo answer below is a
real one, captured 2026-10-24.
"""

import datetime
import json
import os
import re
import tempfile
import unittest

import convert as C

OPEN_METEO = ('{"latitude":-26.186293,"longitude":28.026318,"generationtime_ms":0.015139579772949219,'
              '"utc_offset_seconds":0,"timezone":"GMT","timezone_abbreviation":"GMT","elevation":1734.0,'
              '"current_units":{"time":"iso8601","interval":"seconds","temperature_2m":"\u00b0C"},'
              '"current":{"time":"2026-10-24T09:45","interval":900,"temperature_2m":26.0}}')
SOURCE = "https://api.open-meteo.com/v1/forecast?latitude=-26.2&longitude=28.04&current=temperature_2m"
RECIPE = {
    "schema": "mekatrona/recipe@0",
    "source": SOURCE,
    "pick": {"value": "current.temperature_2m", "unit": "current_units.temperature_2m",
             "at": "current.time", "atOffset": "utc_offset_seconds"},
    "dial": {"name": "Johannesburg", "rangeLo": 0, "rangeHi": 40, "staleAfterS": 3600},
}
PUBLISHED = "https://example.github.io/demo"


def refused(f, *a):
    try:
        f(*a)
    except C.Refused as e:
        return str(e)
    return None


def dial_accepts(feed):
    """The dial's own rules for a feed file (analog-dial/feed@0), as its firmware checks them."""
    body = C.dump(feed)
    d = feed["dial"]
    v = d["value"]
    return (len(body) <= 2048 and feed["schema"] == "analog-dial/feed@0"
            and (v is None or (isinstance(v, str) and len(v) <= 12 and re.match(r"^[+-]?[0-9]+(\.[0-9]+)?$", v)))
            and ("at" not in d or re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", d["at"])))


class Picking(unittest.TestCase):
    def test_numbers_keep_their_own_digits(self):
        doc = C.parse_json('{"a": 26.0, "b": 1.10, "c": -0, "d": 1e3, "e": 12}')
        self.assertEqual([doc[k] for k in "abcde"], ["26.0", "1.10", "-0", "1e3", "12"])
        self.assertTrue(all(isinstance(doc[k], C.Raw) for k in "abcde"))

    def test_paths(self):
        self.assertEqual(C.steps("current.temperature_2m"), ["current", "temperature_2m"])
        self.assertEqual(C.steps("data[0].price"), ["data", 0, "price"])
        self.assertEqual(C.steps("data.0.price"), ["data", 0, "price"])
        self.assertEqual(C.steps("a[1][2]"), ["a", 1, 2])
        for bad in ("", "a..b", "a[x]", ".a", 5):
            self.assertIsNotNone(refused(C.steps, bad), bad)

    def test_pick(self):
        doc = C.parse_json('{"data": [{"price": 1.5}, {"price": 2.25}], "0": "zero"}')
        self.assertEqual(C.pick(doc, "data[1].price"), "2.25")
        self.assertEqual(C.pick(doc, "0"), "zero")
        self.assertIn("nothing at data[2].price", refused(C.pick, doc, "data[2].price"))


class Values(unittest.TestCase):
    def test_kept_digit_for_digit(self):
        self.assertEqual(C.value_of(C.Raw("26.0")), "26.0")
        self.assertEqual(C.value_of(C.Raw("26.10")), "26.10")
        self.assertEqual(C.value_of(C.Raw("-3")), "-3")

    def test_an_exponent_written_out(self):
        self.assertEqual(C.value_of(C.Raw("1.5e3")), "1500")
        self.assertEqual(C.value_of(C.Raw("2E-4")), "0.0002")

    def test_a_number_sent_as_text(self):
        self.assertEqual(C.value_of("26.0"), "26.0")
        self.assertEqual(C.value_of(" 7 "), "7")

    def test_no_reading_is_no_reading(self):
        self.assertIsNone(C.value_of(None))

    def test_what_is_not_a_number(self):
        for bad in (True, "1,234", "warm", {"a": 1}, [1], C.Raw("NaN"), C.Raw("Infinity")):
            self.assertIsNotNone(refused(C.value_of, bad), bad)

    def test_too_many_places_rounded_half_away_from_zero(self):
        self.assertEqual(C.fit_value("0.000012345678901"), "0.0000123457")
        self.assertEqual(C.fit_value("-1234.56789012"), "-1234.567890")
        self.assertEqual(C.fit_value("123456789012.5"), "123456789013")
        self.assertEqual(C.fit_value("1.00000000005"), "1.0000000001")
        self.assertEqual(C.fit_value("-0.000000000004"), "0.000000000")     # 9 places fit beside the sign
        self.assertEqual(C.fit_value("123456789012"), "123456789012")
        self.assertIn("too long", refused(C.fit_value, "1234567890123"))


class Times(unittest.TestCase):
    def test_a_time_with_no_zone_takes_the_offset(self):
        self.assertEqual(C.at_of("2026-10-24T09:45", 0), "2026-10-24T09:45:00Z")
        self.assertEqual(C.at_of("2026-10-24T09:45", 7200), "2026-10-24T07:45:00Z")

    def test_a_time_that_names_its_zone(self):
        self.assertEqual(C.at_of("2026-10-24T09:45:00+02:00", None), "2026-10-24T07:45:00Z")
        self.assertEqual(C.at_of("2026-10-24T09:45:30.5Z", None), "2026-10-24T09:45:30Z")

    def test_seconds_and_milliseconds_since_1970(self):
        self.assertEqual(C.at_of(C.Raw("1792835100"), None), "2026-10-24T09:45:00Z")
        self.assertEqual(C.at_of(C.Raw("1792835100000"), None), "2026-10-24T09:45:00Z")

    def test_never_guessed(self):
        self.assertIn("names no zone", refused(C.at_of, "2026-10-24T09:45", None))
        self.assertIsNotNone(refused(C.at_of, "yesterday", 0))
        self.assertIsNotNone(refused(C.at_of, None, 0))


class Recipes(unittest.TestCase):
    def test_the_demo_recipe(self):
        C.check_recipe(RECIPE)

    def test_refused(self):
        def but(**changes):
            r = json.loads(json.dumps(RECIPE))
            for k, v in changes.items():
                part, _, key = k.partition("__")
                if key:
                    r[part][key] = v
                else:
                    r[part] = v
            return refused(C.check_recipe, r)
        self.assertIsNotNone(but(schema="x"))
        self.assertIn("https://", but(source="http://example.com/x.json"))
        self.assertIsNotNone(but(pick={"unit": "a"}))
        self.assertIsNotNone(but(pick__colour="a"))
        self.assertIsNotNone(but(dial__name=5))
        self.assertIsNotNone(but(dial__colour="red"))
        self.assertIn("keep one", but(dial__unit="C"))
        self.assertIsNotNone(but(dial__rangeLo=40))
        self.assertIsNotNone(but(dial__staleAfterS=0))
        self.assertIsNotNone(but(atZone="SAST"))


class Feeds(unittest.TestCase):
    def test_the_demo_feed_from_a_real_answer(self):
        feed = C.feed_from(RECIPE, OPEN_METEO)
        self.assertEqual(feed, {"schema": "analog-dial/feed@0", "dial": {
            "name": "Johannesburg", "unit": "\u00b0C", "rangeLo": 0, "rangeHi": 40,
            "value": "26.0", "at": "2026-10-24T09:45:00Z", "staleAfterS": 3600}})
        self.assertTrue(dial_accepts(feed))

    def test_the_file_is_small_and_utf8(self):
        body = C.dump(C.feed_from(RECIPE, OPEN_METEO))
        self.assertLess(len(body), 300)
        self.assertIn("\u00b0C".encode("utf-8"), body)

    def test_atZone_utc(self):
        r = dict(RECIPE, pick={"value": "current.temperature_2m", "at": "current.time"}, atZone="UTC")
        self.assertEqual(C.feed_from(r, OPEN_METEO)["dial"]["at"], "2026-10-24T09:45:00Z")

    def test_a_time_picked_with_no_zone_and_no_offset(self):
        r = dict(RECIPE, pick={"value": "current.temperature_2m", "at": "current.time"})
        self.assertIn("names no zone", refused(C.feed_from, r, OPEN_METEO))

    def test_a_null_reading_is_published_as_none(self):
        feed = C.feed_from(RECIPE, OPEN_METEO.replace('"temperature_2m":26.0', '"temperature_2m":null'))
        self.assertIsNone(feed["dial"]["value"])
        self.assertTrue(dial_accepts(feed))

    def test_not_json(self):
        self.assertIn("JSON", refused(C.feed_from, RECIPE, "<html>busy</html>"))


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.recipes = os.path.join(self.tmp.name, "recipes")
        self.out = os.path.join(self.tmp.name, "site")
        os.makedirs(self.recipes)
        with open(os.path.join(self.recipes, "jhb-temp.json"), "w", encoding="utf-8") as f:
            json.dump(RECIPE, f)
        self.asked = []
        self.answers = {SOURCE: OPEN_METEO.encode("utf-8")}
        self.now = datetime.datetime(2026, 10, 24, 9, 50, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, url):
        self.asked.append(url)
        a = self.answers.get(url)
        if isinstance(a, Exception):
            raise a
        if a is None:
            raise OSError("no answer")
        return a

    def feed_file(self):
        p = os.path.join(self.out, "feeds", "jhb-temp.json")
        return open(p, "rb").read() if os.path.exists(p) else None

    def test_a_good_run(self):
        s = C.run(self.recipes, self.out, PUBLISHED, self.get, self.now)
        self.assertEqual(json.loads(self.feed_file())["dial"]["value"], "26.0")
        self.assertEqual(s["feeds"][0]["result"], "new")
        self.assertEqual(s["ranAt"], "2026-10-24T09:50:00Z")
        index = json.load(open(os.path.join(self.out, "feeds", "index.json"), encoding="utf-8"))
        self.assertEqual(index["feeds"][0]["at"], "2026-10-24T09:45:00Z")
        self.assertEqual(self.asked, [SOURCE])

    def test_the_source_down_publishes_last_time_s_file_unchanged(self):
        old = C.dump({"schema": "analog-dial/feed@0", "dial": {"name": "Johannesburg", "value": "19.5",
                                                               "at": "2026-10-24T07:45:00Z", "staleAfterS": 3600}})
        self.answers = {SOURCE: OSError("down"), PUBLISHED + "/feeds/jhb-temp.json": old}
        s = C.run(self.recipes, self.out, PUBLISHED, self.get, self.now)
        self.assertEqual(self.feed_file(), old)
        self.assertEqual((s["feeds"][0]["result"], s["feeds"][0]["value"]), ("kept", "19.5"))
        self.assertIn("could not be read", s["feeds"][0]["why"])

    def test_the_source_down_and_nothing_published_yet(self):
        self.answers = {}
        s = C.run(self.recipes, self.out, PUBLISHED, self.get, self.now)
        self.assertIsNone(self.feed_file())
        self.assertEqual(s["feeds"][0]["result"], "none")

    def test_a_published_file_that_is_not_a_feed_is_not_kept(self):
        self.answers = {SOURCE: b"<html>busy</html>", PUBLISHED + "/feeds/jhb-temp.json": b"<html>404</html>"}
        s = C.run(self.recipes, self.out, PUBLISHED, self.get, self.now)
        self.assertIsNone(self.feed_file())
        self.assertEqual(s["feeds"][0]["result"], "none")

    def test_a_badly_named_recipe(self):
        os.rename(os.path.join(self.recipes, "jhb-temp.json"), os.path.join(self.recipes, "Jhb Temp.json"))
        s = C.run(self.recipes, self.out, None, self.get, self.now)
        self.assertIn("file name", s["feeds"][0]["why"])
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
