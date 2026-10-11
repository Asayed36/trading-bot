import io
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import date

import helpers  # noqa: F401

from backtest import data


def zipped(rows, header=False):
    text = ("open_time,open,high,low,close,volume\n" if header else "") + "\n".join(
        ",".join(str(x) for x in r) + ",0,0,0,0,0" for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", text)
    return buf.getvalue()


class FakeFetcher:
    """Pretends to be data.Fetcher with a dict of url -> bytes."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def get(self, url):
        self.asked.append(url)
        return self.files.get(url)


def day_rows(first_day, n, price=100.0):
    return [((first_day + k) * data.DAY_MS, price, price + 1, price - 1, price, 1.0) for k in range(n)]


class ParseTests(unittest.TestCase):
    def test_milliseconds_microseconds_and_header(self):
        ms = "1654041600000,1.5,2,1,1.8,10,1654045199999,0,0,0,0,0"
        us = "1740787200000000,3,4,2,3.5,10,1740790799999999,0,0,0,0,0"
        rows = data.parse_klines("open_time,open,high,low,close\n" + ms + "\n" + us + "\n\n")
        self.assertEqual([r[0] for r in rows], [1654041600000, 1740787200000])   # both in ms
        self.assertEqual(rows[0][1:], (1.5, 2.0, 1.0, 1.8, 10.0))

    def test_urls(self):
        self.assertEqual(data.monthly_url("BTCUSDT", "1h", 2022, 6),
                         "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2022-06.zip")
        self.assertEqual(data.daily_url("BTCUSDT", "1d", date(2026, 10, 9)),
                         "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2026-10-09.zip")


class FetcherTests(unittest.TestCase):
    def fetcher(self, responses, **kw):
        calls = []

        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body

        def opener(req, timeout=None):
            calls.append(req.full_url)
            answer = responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return Resp(answer)

        f = data.Fetcher(tempfile.mkdtemp(), opener=opener, **kw)
        return f, calls

    def test_missing_file_is_none_and_not_retried(self):
        f, calls = self.fetcher([urllib.error.HTTPError("u", 404, "nf", {}, None)])
        self.assertIsNone(f.get("https://data.binance.vision/data/spot/x"))
        self.assertEqual(len(calls), 1)

    def test_cached_after_the_first_download(self):
        f, calls = self.fetcher([b"abc"])
        self.assertEqual(f.get("https://data.binance.vision/data/spot/y"), b"abc")
        self.assertEqual(f.get("https://data.binance.vision/data/spot/y"), b"abc")
        self.assertEqual((len(calls), f.downloaded), (1, 1))

    def test_a_real_failure_is_raised_not_skipped(self):
        import backtest.data as d
        slept = []
        original = d.time.sleep
        d.time.sleep = slept.append
        try:
            err = urllib.error.HTTPError("u", 500, "boom", {}, None)
            f, calls = self.fetcher([err, err, err, err], retries=4)
            with self.assertRaises(data.DataError):
                f.get("https://data.binance.vision/data/spot/z")
            self.assertEqual(len(calls), 4)
            f2, _ = self.fetcher([OSError("reset"), b"ok"])
            self.assertEqual(f2.get("https://data.binance.vision/data/spot/w"), b"ok")   # a retry works
        finally:
            d.time.sleep = original

    def test_offline_uses_only_the_cache(self):
        f, calls = self.fetcher([b"abc"])
        f.get("https://data.binance.vision/data/spot/v")
        off = data.Fetcher(f.cache_dir, offline=True)
        self.assertEqual(off.get("https://data.binance.vision/data/spot/v"), b"abc")
        self.assertIsNone(off.get("https://data.binance.vision/data/spot/other"))


class LoadTests(unittest.TestCase):
    today = date(2026, 10, 11)

    def test_months_current_month_days_and_a_missing_last_month(self):
        d0 = helpers.day_number(date(2026, 7, 1))
        files = {
            data.monthly_url("AAAUSDT", "1d", 2026, 7): zipped(day_rows(d0, 31)),
            # August's monthly file is not published yet: its days are used
            **{data.daily_url("AAAUSDT", "1d", date(2026, 9, k)): zipped(day_rows(helpers.day_number(date(2026, 9, k)), 1))
               for k in range(1, 31)},
            data.monthly_url("AAAUSDT", "1d", 2026, 8): zipped(day_rows(d0 + 31, 31)),
            # the current month: days up to the 9th exist, the 10th is not out yet
            **{data.daily_url("AAAUSDT", "1d", date(2026, 10, k)): zipped(day_rows(helpers.day_number(date(2026, 10, k)), 1))
               for k in range(1, 10)},
        }
        f = FakeFetcher(files)
        self.assertEqual(data.find_first_month(f, "AAAUSDT", self.today), (2026, 7))
        rows = data.load_rows(f, "AAAUSDT", "1d", (2026, 7), self.today)
        days = [r[0] // data.DAY_MS for r in rows]
        self.assertEqual(days, sorted(set(days)))
        self.assertEqual(len(rows), 31 + 31 + 30 + 9)                      # Jul, Aug, Sep (by days), Oct 1-9
        self.assertEqual(days[-1], helpers.day_number(date(2026, 10, 9)))

    def test_a_coin_that_does_not_exist(self):
        self.assertIsNone(data.find_first_month(FakeFetcher({}), "NOPEUSDT", self.today))
        self.assertIsNone(data.load_coin(FakeFetcher({}), "NOPE", ["NOPEUSDT"], self.today))

    def test_renamed_coin_is_stitched(self):
        a = helpers.day_number(date(2026, 7, 1))
        files = {
            data.monthly_url("OLDUSDT", "1d", 2026, 7): zipped(day_rows(a, 20, 10.0)),
            data.monthly_url("OLDUSDT", "1h", 2026, 7): zipped([]),
            data.monthly_url("NEWUSDT", "1d", 2026, 7): zipped(day_rows(a + 15, 16, 12.0)),   # overlaps 5 days
            data.monthly_url("NEWUSDT", "1h", 2026, 7): zipped([]),
        }
        coin = data.load_coin(FakeFetcher(files), "X", ["OLDUSDT", "NEWUSDT"], date(2026, 8, 5))
        self.assertEqual(len(coin), 31)
        self.assertEqual(coin.c[0], 10.0)
        self.assertEqual(coin.c[16], 12.0)                  # the later symbol wins on the overlap

    def test_build_coin_checks_hourly_against_daily(self):
        coin = helpers.make_coin("T", date(2022, 1, 1), helpers.flat_days(3))
        self.assertEqual(coin.notes["days_where_hourly_and_daily_disagree"], 0)
        self.assertEqual(coin.notes["days_with_fewer_than_24_hours"], 0)
        self.assertEqual(coin.day_hours, [(0, 24), (24, 48), (48, 72)])
        # drop three hours from day 2 and corrupt day 3's high
        t0 = helpers.day_number(date(2022, 1, 1)) * data.DAY_MS
        daily = [(t0 + k * data.DAY_MS, 100, 100 + (5 if k == 2 else 0), 100, 100, 1) for k in range(3)]
        hourly = [(t0 + k * data.DAY_MS + h * helpers.HOUR_MS, 100, 100, 100, 100, 1)
                  for k in range(3) for h in range(24) if not (k == 1 and h < 3)]
        c = data.build_coin("T", ["TUSDT"], daily, hourly)
        self.assertEqual(c.notes["days_with_fewer_than_24_hours"], 1)
        self.assertEqual(c.notes["days_where_hourly_and_daily_disagree"], 1)

    def test_truncate_removes_everything_after(self):
        coin = helpers.make_coin("T", date(2022, 1, 1), helpers.flat_days(10))
        cut = coin.truncate(date(2022, 1, 4))
        self.assertEqual(len(cut), 4)
        self.assertEqual(cut.date_of(len(cut) - 1), date(2022, 1, 4))
        self.assertEqual(len(cut.h_open), 4 * 24)
        self.assertEqual(cut.day_hours[-1], (72, 96))


if __name__ == "__main__":
    unittest.main()
