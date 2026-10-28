"""A DexScreener 5xx or timeout must not make a main (1 min) run fail or lose its data: one
retry after 2 seconds, then only that call is skipped for the minute (screener/api.py,
main_1min.py). Fake answers only; nothing here touches the network."""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

import main_1min as m1  # noqa: E402
import requests  # noqa: E402
from run import load_config  # noqa: E402
from screener import api as api_module  # noqa: E402
from screener.api import (ApiError, PublicApi, RateLimited, ServerError,  # noqa: E402
                          Unavailable, Unreachable)
from screener.demo import GOOD, DemoApi  # noqa: E402

CFG = running(load_config())
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
BOOSTS = "https://api.dexscreener.com/token-boosts/latest/v1"


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def answer(status, body=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else []
    return resp


class HttpTests(unittest.TestCase):
    def get(self, results, **kw):
        api = PublicApi(**kw)
        with mock.patch.object(api_module.requests, "get", side_effect=results) as fake, \
                mock.patch.object(api_module.time, "sleep"):
            try:
                return api, fake, api._get(BOOSTS)
            except Exception as exc:
                return api, fake, exc

    def test_a_5xx_is_a_server_error_and_still_an_api_error(self):
        _, _, exc = self.get([answer(502)])
        self.assertIsInstance(exc, ServerError)
        self.assertIsInstance(exc, Unavailable)
        self.assertIsInstance(exc, ApiError)
        self.assertIn("answered with error 502", str(exc))

    def test_other_errors_are_not_unavailable(self):
        _, _, exc = self.get([answer(403)])
        self.assertIs(type(exc), ApiError)
        self.assertEqual(self.get([answer(404)])[2], None)

    def test_a_timeout_is_unreachable_after_one_try_when_asked_to(self):
        _, fake, exc = self.get([requests.Timeout("slow")], dexscreener_attempts=1)
        self.assertIsInstance(exc, Unreachable)
        self.assertEqual(fake.call_count, 1)

    def test_other_sites_and_the_default_keep_their_three_tries(self):
        _, fake, exc = self.get([requests.Timeout("slow")] * 3)
        self.assertIsInstance(exc, Unreachable)
        self.assertEqual(fake.call_count, 3)
        api = PublicApi(dexscreener_attempts=1)
        with mock.patch.object(api_module.requests, "get",
                               side_effect=[requests.Timeout("slow")] * 3) as fake, \
                mock.patch.object(api_module.time, "sleep"):
            with self.assertRaises(Unreachable):
                api._get("https://api.rugcheck.xyz/v1/tokens/x/report")
        self.assertEqual(fake.call_count, 3)                  # RugCheck is unchanged

    def test_a_429_is_still_rate_limited(self):
        _, _, exc = self.get([answer(429)] * 3)
        self.assertIsInstance(exc, RateLimited)


class Flaky(DemoApi):
    """DemoApi whose calls fail with the errors queued for them, in order."""

    def __init__(self, **fails):
        super().__init__()
        self.fails = {k: list(v) for k, v in fails.items()}
        self.asked = {}

    def _maybe(self, name):
        self.asked[name] = self.asked.get(name, 0) + 1
        if self.fails.get(name):
            raise self.fails[name].pop(0)

    def latest_profiles(self):
        self._maybe("profiles")
        return super().latest_profiles()

    def latest_boosts(self):
        self._maybe("boosts")
        return super().latest_boosts()

    def pairs_for_tokens(self, addresses):
        self._maybe("pairs")
        return super().pairs_for_tokens(addresses)


def bad(kind=ServerError, text="https://api.dexscreener.com/token-boosts/latest/v1 answered "
                                "with error 502"):
    return kind(text)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def bot(self, api, folder=None):
        bot = m1.MainOneMinute(CFG, folder or self.d, api)
        bot.api.sleep = self.sleeps.append
        return bot

    def main(self, name):
        return os.path.join(self.d, "main-1min", name)

    def health_counts(self):
        with open(self.main("health.json")) as fh:
            data = json.load(fh)
        total = {}
        for hour in data["calls_per_hour"].values():
            for k, v in hour.items():
                total[k] = total.get(k, 0) + v
        return data, total

    def clean_rows(self):
        with tempfile.TemporaryDirectory() as other:
            self.bot(Flaky(), other).run_once(NOW, lambda *a: None)
            return (rows(os.path.join(other, "main-1min", "candidates.csv")),
                    rows(os.path.join(other, "main-1min", "journal.csv")))

    def test_a_502_then_a_200_loses_nothing(self):
        api = Flaky(boosts=[bad()])
        lines = []
        self.bot(api).run_once(NOW, lines.append)
        self.assertEqual(self.sleeps, [2])
        self.assertEqual(api.asked["boosts"], 2)
        data, total = self.health_counts()
        self.assertEqual(total["dexscreener retries"], 1)
        self.assertNotIn("dexscreener skipped", total)
        self.assertNotIn("last_error", data)
        clean_candidates, clean_journal = self.clean_rows()
        self.assertEqual(rows(self.main("candidates.csv")), clean_candidates)
        self.assertEqual(rows(self.main("journal.csv")), clean_journal)
        self.assertTrue(clean_candidates)
        # the retry is an extra request, counted in the free-limit budget
        self.assertEqual(total["dexscreener"], 4)

    def test_two_502s_skip_only_that_call_and_the_run_still_writes_its_rows(self):
        api = Flaky(boosts=[bad(), bad()])
        with self.assertLogs("main_1min", level="WARNING") as logged:
            result = self.bot(api).run_once(NOW, lambda *a: None)
        self.assertIsNotNone(result)
        self.assertEqual(self.sleeps, [2])
        self.assertEqual(len([r for r in logged.records if "skipped this minute" in r.getMessage()]), 1)
        self.assertIn("DexScreener boosts skipped", logged.output[0])
        data, total = self.health_counts()
        self.assertEqual((total["dexscreener retries"], total["dexscreener skipped"]), (1, 1))
        self.assertNotIn("last_error", data)
        self.assertIn("last_ok", data)
        got = rows(self.main("candidates.csv"))
        self.assertTrue(got)                                  # the profiles list still worked
        clean = {r["token_address"]: r for r in self.clean_rows()[0]}
        for r in got:                                         # each row is the same as a clean run's
            self.assertEqual(r, clean[r["token_address"]])
        self.assertTrue(rows(self.main("journal.csv")))       # and buys still happen

    def test_a_timeout_is_retried_and_a_second_one_skips_the_pairs_call(self):
        api = Flaky(pairs=[bad(Unreachable, "could not reach x: timed out")] * 2)
        with self.assertLogs("main_1min", level="WARNING"):
            result = self.bot(api).run_once(NOW, lambda *a: None)
        self.assertIsNotNone(result)
        data, total = self.health_counts()
        self.assertEqual((total["dexscreener retries"], total["dexscreener skipped"]), (1, 1))
        self.assertNotIn("last_error", data)
        # nothing could be checked, so nothing is invented: no rows, no buys, no FAIL rows
        self.assertEqual(rows(self.main("candidates.csv")), [])
        self.assertEqual(rows(self.main("journal.csv")), [])
        # the next minute works as normal
        bot_again = self.bot(Flaky())
        bot_again.run_once(NOW + timedelta(minutes=1), lambda *a: None)
        self.assertTrue(rows(self.main("candidates.csv")))
        self.assertTrue(rows(self.main("journal.csv")))

    def test_one_timeout_then_an_answer_is_just_a_retry(self):
        api = Flaky(profiles=[bad(Unreachable, "could not reach x: timed out")])
        self.bot(api).run_once(NOW, lambda *a: None)
        _, total = self.health_counts()
        self.assertEqual(total["dexscreener retries"], 1)
        self.assertNotIn("dexscreener skipped", total)
        self.assertEqual(rows(self.main("candidates.csv")), self.clean_rows()[0])

    def test_no_list_at_all_still_skips_the_run_as_before(self):
        api = Flaky(profiles=[bad(), bad()], boosts=[bad(), bad()])
        lines = []
        with self.assertLogs("main_1min", level="WARNING"):
            result = self.bot(api).run_once(NOW, lines.append)
        self.assertIsNone(result)
        self.assertIn("skipped, nothing changed", lines[0])
        data, _ = self.health_counts()
        self.assertIn("last_error", data)
        self.assertEqual(rows(self.main("candidates.csv")), [])

    def test_rate_limits_and_other_errors_still_skip_the_run(self):
        for error in (RateLimited("too many requests"), ApiError("answered with error 403")):
            with tempfile.TemporaryDirectory() as d:
                api = Flaky(boosts=[error])
                lines = []
                self.assertIsNone(self.bot(api, d).run_once(NOW, lines.append))
                self.assertEqual(api.asked["boosts"], 1)      # no retry
                self.assertEqual(self.sleeps, [])

    def test_an_open_position_waits_for_the_next_minute_when_its_price_call_fails(self):
        self.bot(Flaky()).run_once(NOW, lambda *a: None)
        before = rows(self.main("journal.csv"))
        self.assertTrue(before)
        api = Flaky(pairs=[bad(), bad()])
        api.price_moves = {GOOD: 0.1}                         # it would have hit the stop loss
        with self.assertLogs("main_1min", level="WARNING"):
            self.bot(api).run_once(NOW + timedelta(minutes=1), lambda *a: None)
        self.assertEqual(rows(self.main("journal.csv")), before)   # no sale on a missing price
        with open(self.main("positions.json")) as fh:
            self.assertTrue(json.load(fh)["open_positions"])
        again = Flaky()
        again.price_moves = {GOOD: 0.1}
        self.bot(again).run_once(NOW + timedelta(minutes=2), lambda *a: None)
        self.assertTrue([r for r in rows(self.main("journal.csv")) if r["action"] == "SELL"])

    def test_the_counters_start_empty_and_the_request_count_is_unchanged_when_nothing_fails(self):
        api = m1.CountingApi(Flaky())
        self.assertEqual(api.calls, {"dexscreener": 0, "rugcheck": 0, "jupiter": 0})
        api.latest_profiles()
        api.pairs_for_tokens(["a"] * 31)
        self.assertEqual(api.calls, {"dexscreener": 3, "rugcheck": 0, "jupiter": 0})


if __name__ == "__main__":
    unittest.main()
