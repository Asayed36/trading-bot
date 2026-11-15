"""Checks for the X post watcher (screener/xposts.py, xposts_bot.py) and its report
(screener/xposts_report.py). A fake X connection only: nothing here reaches X or costs anything,
and no real token is used."""

import contextlib
import copy
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xposts_bot  # noqa: E402
from screener import xposts as xp  # noqa: E402
from screener import xposts_report as rep  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

CFG = load_config()
TOKEN = "FAKE-TOKEN-never-real-123"
NOW = datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)
IDS = {h.lower(): str(1000 + i) for i, h in enumerate(CFG["xposts"]["accounts"])}


class Resp:
    def __init__(self, status=200, body=None, headers=None, text_only=False):
        self.status_code, self.body, self.headers = status, body or {}, headers or {}
        self.text_only = text_only

    def json(self):
        if self.text_only:
            raise ValueError("not json")
        return self.body


class FakeX:
    """Plays X: user lookup by handles, and each account's posts (newest first), honouring
    since_id, start_time and max_results. `fail` maps an account ID to a Resp to send."""

    def __init__(self, posts=None, missing=(), fail=None, headers=None):
        self.posts = posts or {}            # user id -> [(id, created_at, text)]
        self.missing = {m.lower() for m in missing}
        self.fail, self.headers = fail or {}, headers or {}
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if url.endswith("/users/by"):
            names = params["usernames"].split(",")
            data = [{"id": IDS[n.lower()], "username": n, "name": n} for n in names
                    if n.lower() not in self.missing]
            body = {"data": data} if data else {}
            if self.missing & {n.lower() for n in names}:
                body["errors"] = [{"title": "Not Found Error"}]
            return Resp(200, body, self.headers)
        user_id = url.rsplit("/", 2)[-2]
        if user_id in self.fail:
            return self.fail[user_id]
        mine = sorted(self.posts.get(user_id, []), key=lambda p: -int(p[0]))
        if params.get("since_id"):
            mine = [p for p in mine if int(p[0]) > int(params["since_id"])]
        if params.get("start_time"):
            mine = [p for p in mine if p[1] >= params["start_time"].replace("Z", ".000Z")]
        page = mine[:params["max_results"]]
        body = {"meta": {"result_count": len(page)}}
        if page:
            body["data"] = [{"id": i, "created_at": c, "text": t} for i, c, t in page]
            body["meta"].update(newest_id=page[0][0], oldest_id=page[-1][0])
        if len(mine) > len(page):
            body["meta"]["next_token"] = "more"
        return Resp(200, body, self.headers)

    def timelines(self):
        return [c for c in self.calls if c[0].endswith("/tweets")]


def at(minutes=0):
    return NOW + timedelta(minutes=minutes)


def stamp(minutes):
    return at(minutes).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def watcher(self, fake, cfg=None, token=TOKEN):
        api = xp.XApi(token, session=fake) if token else None
        return xp.Watcher(cfg or CFG, self.d, api)

    def path(self, *parts):
        return os.path.join(self.d, "xposts", *parts)

    def rows(self, day="2027-01-15"):
        p = self.path(f"posts-{day}.csv")
        if not os.path.exists(p):
            return []
        with open(p, newline="") as fh:
            return list(csv.DictReader(fh))

    def health(self):
        with open(self.path("health.json")) as fh:
            return json.load(fh)

    def all_text(self):
        out = ""
        for root, _, files in os.walk(self.d):
            for f in files:
                with open(os.path.join(root, f), errors="replace") as fh:
                    out += fh.read()
        return out


class TokenTests(unittest.TestCase):
    def test_from_systemds_credential_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x_bearer_token"), "w") as fh:
                fh.write(TOKEN + "\n")
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d}, clear=True):
                self.assertEqual(xp.secret(), TOKEN)

    def test_from_the_environment_or_none(self):
        with mock.patch.dict(os.environ, {"X_BEARER_TOKEN": f" {TOKEN} "}, clear=True):
            self.assertEqual(xp.secret(), TOKEN)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(xp.secret())
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "x_bearer_token"), "w").close()     # an empty file
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d}, clear=True):
                self.assertIsNone(xp.secret())

    def test_the_repository_holds_no_token(self):
        out = subprocess.run(["git", "grep", "-n", "-I", "-E",
                              "AAAAAAAAAAAAAAAAAAAAA|Bearer [A-Za-z0-9%]{40,}",
                              "--", ".", ":!tests/test_xposts.py"],      # (not this pattern itself)
                             cwd=HERE, capture_output=True, text=True)
        self.assertEqual(out.stdout, "")


class ApiTests(Base):
    def test_the_request_is_read_only_and_asks_for_originals_newer_than_the_last(self):
        fake = FakeX()
        api = xp.XApi(TOKEN, session=fake)
        api.posts("1000", 5, since_id="77")
        url, params, headers = fake.calls[0]
        self.assertEqual(url, "https://api.x.com/2/users/1000/tweets")
        self.assertEqual(params, {"max_results": 5, "exclude": "replies,retweets",
                                  "tweet.fields": "created_at", "since_id": "77"})
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        api.posts("1000", 5, start_time=NOW)
        self.assertEqual(fake.calls[1][1]["start_time"], "2027-01-15T12:00:00Z")
        self.assertNotIn("since_id", fake.calls[1][1])

    def test_lookup_finds_and_reports_unknown_handles(self):
        fake = FakeX(missing=["MrBeast"])
        found, missing = xp.XApi(TOKEN, session=fake).lookup(["elonmusk", "MrBeast"])
        self.assertEqual(found, {"elonmusk": IDS["elonmusk"]})
        self.assertEqual(missing, ["MrBeast"])
        self.assertEqual(fake.calls[0][1], {"usernames": "elonmusk,MrBeast"})

    def test_errors_never_carry_the_token(self):
        cases = [Resp(401, {"title": "Unauthorized"}), Resp(403, {"detail": "Forbidden"}),
                 Resp(429, {}, {"x-rate-limit-reset": str(int(at(15).timestamp()))}),
                 Resp(500, text_only=True)]
        for resp in cases:
            fake = FakeX(fail={"1000": resp})
            with self.assertRaises(xp.XError) as got:
                xp.XApi(TOKEN, session=fake).posts("1000", 5)
            self.assertEqual(got.exception.status, resp.status_code)
            self.assertNotIn(TOKEN, str(got.exception))
        self.assertEqual(got.exception.status, 500)

    def test_a_rate_limit_says_when_to_try_again(self):
        fake = FakeX(fail={"1000": Resp(429, {}, {"x-rate-limit-reset": str(int(at(15).timestamp()))})})
        with self.assertRaises(xp.XError) as got:
            xp.XApi(TOKEN, session=fake).posts("1000", 5)
        self.assertEqual(got.exception.retry_at, at(15))

    def test_no_answer_is_an_error_without_details(self):
        import requests

        class Down:
            def get(self, *a, **k):
                raise requests.ConnectionError(f"failed with header Bearer {TOKEN}")
        with self.assertRaises(xp.XError) as got:
            xp.XApi(TOKEN, session=Down()).posts("1000", 5)
        self.assertNotIn(TOKEN, str(got.exception))
        self.assertIsNone(got.exception.status)

    def test_only_credit_headers_are_kept(self):
        fake = FakeX(headers={"X-Rate-Limit-Remaining": "1499", "x-credits-remaining": "9.95",
                              "x-usage-cost": "0.005"})
        api = xp.XApi(TOKEN, session=fake)
        api.posts("1000", 5)
        self.assertEqual(api.cost_headers(), {"x-credits-remaining": "9.95",
                                              "x-usage-cost": "0.005"})


class WatcherTests(Base):
    def test_first_round_looks_up_once_and_asks_only_for_posts_after_watching_began(self):
        fake = FakeX(posts={IDS["elonmusk"]: [("10", stamp(-30), "old post")]})
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(0))
        self.assertEqual(sum(1 for c in fake.calls if c[0].endswith("/users/by")), 1)
        self.assertEqual(len(fake.timelines()), 12)
        self.assertTrue(all(c[1]["start_time"] == "2027-01-15T12:00:00Z" for c in fake.timelines()))
        self.assertEqual(self.rows(), [])                             # the old post is not paid for

    def test_new_posts_are_saved_and_the_next_request_starts_after_them(self):
        elon = IDS["elonmusk"]
        fake = FakeX(posts={elon: []})
        w = self.watcher(fake)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            w.run_once(at(0))
            fake.posts[elon] = [("101", stamp(1), "Dogecoin to the moon"),
                                ("102", stamp(1.5), "second\nline")]
            w.run_once(at(2))
            w.run_once(at(4))
        got = self.rows()
        self.assertEqual([(r["account"], r["post_id"], r["posted_utc"], r["seen_utc"], r["text"])
                          for r in got],
                         [("elonmusk", "101", "2027-01-15T12:01:00Z", "2027-01-15T12:02:00Z",
                           "Dogecoin to the moon"),
                          ("elonmusk", "102", "2027-01-15T12:01:30Z", "2027-01-15T12:02:00Z",
                           "second\nline")])
        third = [c for c in fake.timelines() if c[0].endswith(f"/{elon}/tweets")][2]
        self.assertEqual(third[1]["since_id"], "102")
        self.assertNotIn("start_time", third[1])
        self.assertEqual(self.health()["posts_read_today"], 2)

    def test_the_ids_are_never_looked_up_again(self):
        fake = FakeX(missing=["pumpdotfun"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.watcher(fake).run_once(at(0))
            self.watcher(fake).run_once(at(2))                    # a restart
        lookups = [c for c in fake.calls if c[0].endswith("/users/by")]
        self.assertEqual(len(lookups), 1)
        with open(self.path("accounts.json")) as fh:
            saved = json.load(fh)
        self.assertEqual(saved["missing"], ["pumpdotfun"])
        self.assertNotIn("pumpdotfun", saved["ids"])
        self.assertEqual(len([c for c in fake.timelines() if c[0].endswith("/tweets")]), 22)
        self.assertEqual(self.health()["accounts_missing"], ["pumpdotfun"])

    def test_the_daily_limit_is_never_passed(self):
        cfg = copy.deepcopy(CFG)
        cfg["xposts"]["max_posts_per_day"] = 12
        posts = {uid: [(str(int(uid) * 100 + n), stamp(1), "post") for n in range(10)]
                 for uid in IDS.values()}
        fake = FakeX(posts=posts)
        w = self.watcher(fake, cfg)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(0))
            w.run_once(at(2))                     # up to 5 a request: 5 + 5 = 10, then no more
            w.run_once(at(4))
        self.assertLessEqual(len(self.rows()), 12)
        self.assertEqual(len(self.rows()), 10)
        h = self.health()
        self.assertEqual((h["posts_read_today"], h["limit_reached_today"]), (10, True))
        asked = len(fake.timelines())
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(6))
        self.assertEqual(len(fake.timelines()), asked)                 # nothing more today
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(12 * 60 + 10))                               # the next UTC day
        self.assertGreater(len(fake.timelines()), asked)

    def test_the_default_limit_is_60_and_never_passed_by_a_flood(self):
        posts = {uid: [(str(int(uid) * 100 + n), stamp(1), "post") for n in range(50)]
                 for uid in IDS.values()}
        fake = FakeX(posts=posts)
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            for m in range(0, 60, 2):
                w.run_once(at(m))
        self.assertLessEqual(self.health()["posts_read_today"], 60)
        self.assertEqual(self.health()["posts_read_today"], 60)

    def test_a_rate_limit_pauses_every_account(self):
        reset = str(int(at(15).timestamp()))
        fake = FakeX(fail={IDS["elonmusk"]: Resp(429, {}, {"x-rate-limit-reset": reset})})
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()), self.assertLogs("xposts", "WARNING"):
            w.run_once(at(0))
        self.assertEqual(len(fake.timelines()), 1)                    # it stopped at the first
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(5))
        self.assertEqual(len(fake.timelines()), 1)                    # still paused
        fake.fail = {}
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(16))
        self.assertEqual(len(fake.timelines()), 13)

    def test_a_rejected_token_stops_for_an_hour(self):
        fake = FakeX(fail={IDS["elonmusk"]: Resp(401, {"title": "Unauthorized"})})
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()), self.assertLogs("xposts", "WARNING"):
            w.run_once(at(0))
        h = self.health()
        self.assertIn("401", h["last_error"])
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(30))
        self.assertEqual(len(fake.timelines()), 1)

    def test_no_token_no_request(self):
        fake = FakeX()
        w = self.watcher(fake, token=None)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(0))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.health()["token"])

    def test_many_new_posts_are_marked_as_maybe_missed(self):
        elon = IDS["elonmusk"]
        fake = FakeX(posts={elon: []})
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(0))
            fake.posts[elon] = [(str(200 + n), stamp(1), "p") for n in range(8)]
            w.run_once(at(2))
        self.assertEqual(self.health()["maybe_missed"], {"elonmusk": 1})

    def test_the_token_is_in_no_file_and_no_log(self):
        fake = FakeX(posts={IDS["elonmusk"]: []},
                     fail={IDS["saylor"]: Resp(403, {"title": f"Forbidden {TOKEN}"})})
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                self.assertLogs("xposts", "DEBUG") as logged:
            fake.posts[IDS["elonmusk"]] = [("5", stamp(1), "hi")]
            w.run_once(at(2))
        # (X's own error text is cut short and logged; it never holds our token, but make sure
        # nothing we write repeats it either)
        written = self.all_text()
        self.assertNotIn("FAKE-TOKEN", written.replace(f"Forbidden {TOKEN}", ""))
        self.assertNotIn("Bearer", written + out.getvalue() + "\n".join(logged.output))

    def test_estimated_cost_and_credit_headers_in_the_health_file(self):
        fake = FakeX(posts={IDS["elonmusk"]: []}, headers={"x-credits-remaining": "9.90"})
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(0))
            fake.posts[IDS["elonmusk"]] = [("5", stamp(1), "hi"), ("6", stamp(1), "there")]
            w.run_once(at(2))
        h = self.health()
        self.assertAlmostEqual(h["estimated_cost_today_usd"], 2 * 0.005 + 12 * 0.010)
        self.assertEqual(h["cost_headers"], {"x-credits-remaining": "9.90"})
        self.assertEqual(h["requests_today"], 25)                     # 1 lookup + 2 x 12


class AccountShareTests(Base):
    def flood(self, n=50):
        return {uid: [(str(int(uid) * 1000 + k), stamp(1), "post") for k in range(n)]
                for uid in IDS.values()}

    def busy_elon(self, fake, rounds, start=0, per_round=3):
        """Elon posts `per_round` new posts before every round; the others post nothing."""
        elon = IDS["elonmusk"]
        w = self.watcher(fake)
        n = 0
        with contextlib.redirect_stdout(io.StringIO()):
            for m in range(start, start + 2 * rounds, 2):
                for _ in range(per_round):
                    n += 1
                    fake.posts.setdefault(elon, []).append((str(5000 + n), stamp(m), "elon"))
                w.run_once(at(m))
        return w

    def test_one_busy_account_cannot_take_the_whole_day(self):
        elon = IDS["elonmusk"]
        fake = FakeX()
        self.busy_elon(fake, rounds=30)
        h = self.health()
        self.assertLessEqual(h["posts_read_today_by_account"]["elonmusk"], 10)
        self.assertEqual(h["posts_read_today_by_account"]["elonmusk"], 6)   # 3 + 3, then 6 + 5 > 10
        self.assertEqual(h["posts_read_today"], 6)                    # the others still have room
        self.assertFalse(h["limit_reached_today"])
        elon_calls = [c for c in fake.timelines() if c[0].endswith(f"/{elon}/tweets")]
        others = [c for c in fake.timelines() if not c[0].endswith(f"/{elon}/tweets")]
        self.assertEqual(len(elon_calls), 2)                          # then skipped all day
        self.assertEqual(len(others), 11 * 30)                        # every other account, every round

    def test_the_overall_limit_still_caps_the_day(self):
        fake = FakeX(posts=self.flood())
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            for m in range(0, 60, 2):
                w.run_once(at(m))
        h = self.health()
        self.assertEqual(h["posts_read_today"], 60)
        self.assertTrue(all(n <= 10 for n in h["posts_read_today_by_account"].values()))

    def test_the_accounts_take_turns_at_the_start_of_a_round(self):
        fake = FakeX()
        w = self.watcher(fake)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(0))
            w.run_once(at(2))
        firsts = [c[0] for c in fake.timelines()][::12]
        self.assertNotEqual(firsts[0], firsts[1])

    def test_after_its_share_an_account_restarts_from_the_new_day_without_the_backlog(self):
        elon = IDS["elonmusk"]
        fake = FakeX()
        w = self.busy_elon(fake, rounds=5)
        with contextlib.redirect_stdout(io.StringIO()):
            w.run_once(at(12 * 60 + 2))                              # 00:02 the next day
        next_day = [c for c in fake.timelines() if c[0].endswith(f"/{elon}/tweets")][-1]
        self.assertEqual(next_day[1]["start_time"], "2027-01-16T00:02:00Z")
        self.assertNotIn("since_id", next_day[1])
        self.assertEqual(self.rows("2027-01-16"), [])                 # the backlog is not paid for

    def test_the_request_limit(self):
        cfg = copy.deepcopy(CFG)
        cfg["xposts"]["max_requests_per_day"] = 15
        fake = FakeX()
        w = self.watcher(fake, cfg)
        with contextlib.redirect_stdout(io.StringIO()):
            for m in range(0, 10, 2):
                w.run_once(at(m))
        self.assertEqual(self.health()["requests_today"], 15)          # 1 lookup + 14 checks
        self.assertTrue(self.health()["request_limit_reached_today"])


class EmptyTestTests(Base):
    def test_three_requests_that_can_only_be_empty_and_nothing_saved(self):
        elon = IDS["elonmusk"]
        fake = FakeX(posts={elon: [(xp.snowflake(at(-5)), stamp(-5), "newest post")]})
        w = self.watcher(fake)
        xposts_bot.do_lookup(w, lambda *a: None)
        before = json.dumps(w.state, sort_keys=True)
        out, sleeps = io.StringIO(), []
        self.assertEqual(xposts_bot.do_empty_test(w, "elonmusk", 3, out.write, sleeps.append,
                                                  clock=lambda: at(0)), 0)
        calls = fake.timelines()
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(int(c[1]["since_id"]) > int(xp.snowflake(at(-5))) for c in calls))
        text = out.getvalue()
        self.assertEqual(text.count(": 0 post(s) returned (X's count: 0)"), 3)
        self.assertIn("Done: 3 request(s), 0 post(s) returned", text)
        self.assertEqual(sleeps, [2, 2])
        self.assertEqual(json.dumps(w.state, sort_keys=True), before)
        self.assertEqual(self.rows(), [])

    def test_the_snowflake_is_newer_than_any_post_before_it(self):
        self.assertGreater(int(xp.snowflake(at(0))), int(xp.snowflake(at(-1))))
        # a real id: 1 Jan 2025 00:00 UTC is about 1874... (X's ids start with their time)
        self.assertTrue(xp.snowflake(datetime(2025, 1, 1, tzinfo=timezone.utc)).startswith("1874"))

    def test_needs_a_saved_id(self):
        out = io.StringIO()
        self.assertEqual(xposts_bot.do_empty_test(self.watcher(FakeX()), "elonmusk", 3,
                                                  out.write, lambda s: None), 1)
        self.assertIn("run --lookup first", out.getvalue())


class CommandTests(Base):
    def test_lookup_lists_found_and_missing_and_is_not_repeated(self):
        fake = FakeX(missing=["a1lon9"])
        w = self.watcher(fake)
        out = io.StringIO()
        self.assertEqual(xposts_bot.do_lookup(w, out.write), 0)
        text = out.getvalue()
        self.assertIn("@elonmusk: found, account ID 1000", text)
        self.assertIn("@a1lon9: NOT FOUND on X", text)
        self.assertIn("Estimated cost: 11 account(s)", text)
        again = io.StringIO()
        xposts_bot.do_lookup(self.watcher(fake), again.write)
        self.assertIn("nothing asked, nothing paid", again.getvalue())
        self.assertEqual(len(fake.calls), 1)

    def test_the_test_request_shows_the_posts_and_the_cost_and_saves_none(self):
        fake = FakeX(posts={IDS["saylor"]: [(str(n), stamp(-n), f"post {n}") for n in range(1, 9)]})
        w = self.watcher(fake)
        out = io.StringIO()
        self.assertEqual(xposts_bot.do_test(w, "@saylor", out.write), 0)
        text = out.getvalue()
        self.assertIn("5 original post(s) returned", text)
        self.assertIn("Estimated cost: 5 post(s) x $0.005 = $0.025", text)
        self.assertIn("Credit or usage information sent by X: none", text)
        self.assertEqual(len(fake.timelines()), 1)
        self.assertEqual(self.rows(), [])
        state = w.state.get("accounts", {})
        self.assertNotIn("saylor", state)                             # no since_id set
        self.assertNotIn(TOKEN, text)

    def test_the_test_refuses_an_account_that_is_not_watched(self):
        out = io.StringIO()
        self.assertEqual(xposts_bot.do_test(self.watcher(FakeX()), "someone", out.write), 1)
        self.assertIn("not in [xposts] accounts", out.getvalue())

    def test_without_a_token_the_commands_stop(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(xposts_bot.main(["--test", "elonmusk"]), 1)
        self.assertIn("No X token found", out.getvalue())


class ReportTests(Base):
    def write(self, rel, columns, rows):
        path = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)

    def setup_data(self):
        self.write("xposts/posts-2027-01-15.csv", xp.POST_COLUMNS, [
            {"account": "elonmusk", "post_id": "1", "posted_utc": "2027-01-15T12:00:00Z",
             "seen_utc": "2027-01-15T12:01:00Z", "text": "Dogecoin and the GROKPUP are great https://x.co/abc"},
            {"account": "saylor", "post_id": "2", "posted_utc": "2027-01-15T13:00:00Z",
             "seen_utc": "2027-01-15T13:01:00Z", "text": "Bitcoin is hope"}])
        cols = ["created_utc", "token_address", "symbol", "name", "symbol_key",
                "same_symbol_prev_30m", "first_of_name_24h", "watchlist_entry", "watchlist_category"]
        self.write("viral/launches-2027-01-15.csv", cols, [
            {"created_utc": "2027-01-15T12:02:00Z", "token_address": "A", "symbol": "GROKPUP",
             "name": "Grok Pup"},
            {"created_utc": "2027-01-15T12:05:00Z", "token_address": "B", "symbol": "DOGE2",
             "name": "Dogecoin Classic"},
            {"created_utc": "2027-01-15T12:20:00Z", "token_address": "C", "symbol": "GROKPUP",
             "name": "late"},                                         # after the 10 minutes
            {"created_utc": "2027-01-15T11:59:00Z", "token_address": "D", "symbol": "GROKPUP",
             "name": "before"},                                       # before the post
            {"created_utc": "2027-01-15T12:03:00Z", "token_address": "E", "symbol": "GREAT",
             "name": "The Great"},                                    # a common word only
        ])
        self.write("launch-record/launches-2027-01-15.csv",
                   ["created_at_utc", "token_address", "price_sol_5s", "price_sol_60s",
                    "price_sol_300s", "price_sol_900s", "price_sol_3600s", "peak_price_sol",
                    "seconds_to_peak"],
                   [{"created_at_utc": "2027-01-15T12:02:00Z", "token_address": "A",
                     "price_sol_5s": "1e-8", "price_sol_60s": "2e-8", "price_sol_300s": "1.5e-8",
                     "price_sol_900s": "0.5e-8", "price_sol_3600s": "", "peak_price_sol": "3e-8",
                     "seconds_to_peak": "40"}])

    def test_matches_within_ten_minutes_with_price_moves(self):
        self.setup_data()
        text = "\n".join(rep.build(self.d, CFG["xposts"], at(120)))
        self.assertIn("2 post(s), 2 matching launch(es).", text)
        self.assertIn("| 120 s | GROKPUP | Grok Pup | grokpup | +100% | +50% | -50% | – | "
                      "+200% (40 s) |", text)
        self.assertIn("| 300 s | DOGE2 | Dogecoin Classic | dogecoin | price not recorded", text)
        self.assertNotIn("| late |", text)
        self.assertNotIn("before", text.split("## @elonmusk")[1].split("## @saylor")[0])
        self.assertNotIn("The Great", text)
        self.assertIn("No matching launch in the next 10 minutes.", text)

    def test_post_words_skip_links_and_common_words(self):
        self.assertEqual(rep.post_words("The DOGE is great https://t.co/xyz $PEPE 2027 ai"),
                         {"doge", "pepe"})

    def test_the_report_file_and_no_posts(self):
        path = rep.write_report(self.d, CFG["xposts"], at(0))
        with open(path) as fh:
            self.assertIn("No posts saved yet.", fh.read())


class HealthRowTests(Base):
    def row(self, data, now=None):
        from screener.health import add_xposts
        got = []
        if data is not None:
            os.makedirs(self.path(), exist_ok=True)
            with open(self.path("health.json"), "w") as fh:
                json.dump(data, fh)
        add_xposts(lambda *a: got.append(a), self.d, CFG, now or at(10))
        return got[0]

    def good(self, **over):
        data = {"updated": "2027-01-15T12:08:00Z", "token": True, "last_ok": "2027-01-15T12:08:00Z",
                "accounts_watched": ["elonmusk", "saylor"], "accounts_missing": [],
                "posts_read_today": 7, "requests_today": 90, "max_posts_per_day": 60,
                "estimated_cost_today_usd": 0.035, "estimated_cost_month_usd": 0.157}
        data.update(over)
        return data

    def test_not_running_yet_is_information(self):
        from screener.health import INFO
        name, status, detail = self.row(None)[:3]
        self.assertEqual((name, status), ("xposts: server", INFO))

    def test_a_healthy_watcher(self):
        from screener.health import OK
        name, status, detail = self.row(self.good())[:3]
        self.assertEqual(status, OK)
        self.assertIn("7 of 60 posts read today (90 request(s))", detail)
        self.assertIn("estimated cost $0.04 today, $0.16 this month", detail)

    def test_warnings(self):
        from screener.health import WARN
        self.assertEqual(self.row(self.good(), now=at(5 * 60))[1], WARN)          # stale
        self.assertEqual(self.row(self.good(token=False))[1], WARN)
        failed = self.good(last_error="elonmusk: X answered 401 Unauthorized",
                           error_at="2027-01-15T12:09:00Z")
        self.assertEqual(self.row(failed)[1], WARN)

    def test_missing_handles_limit_and_credits_are_shown(self):
        _, _, detail = self.row(self.good(accounts_missing=["a1lon9"], limit_reached_today=True,
                                          cost_headers={"x-credits-remaining": "9.90"}))[:3]
        self.assertIn("not found on X: @a1lon9", detail)
        self.assertIn("the daily limit was reached", detail)
        self.assertIn("x-credits-remaining", detail)


class SetupTests(unittest.TestCase):
    def test_the_agreed_settings(self):
        c = CFG["xposts"]
        self.assertEqual((c["every_seconds"], c["max_posts_per_day"], c["max_results"]),
                         (120, 60, 5))
        self.assertEqual(c["accounts"], ["elonmusk", "realDonaldTrump", "MrBeast", "cz_binance",
                                         "VitalikButerin", "aeyakovenko", "blknoiz06",
                                         "MustStopMurad", "saylor", "justinsuntron", "pumpdotfun",
                                         "a1lon9"])

    def test_the_service_gets_the_token_from_a_root_only_file(self):
        with open(os.path.join(HERE, "deploy", "xposts.service")) as fh:
            text = fh.read()
        self.assertIn("LoadCredential=x_bearer_token:/etc/trading-bot/x_bearer_token", text)
        self.assertIn("ExecStart=/home/bot/trading-bot/.venv/bin/python xposts_bot.py", text)
        self.assertNotIn("Environment=X_BEARER", text)

    def test_files_pushed_and_kept(self):
        for path in ("data/xposts/posts-2027-01-15.csv", "data/xposts/accounts.json",
                     "data/xposts/health.json", "data/xposts/report.md"):
            self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                               cwd=HERE).returncode, 0, path)
        for path in ("data/xposts/state.json", "data/xposts/x_bearer_token", "data/xposts/x.env"):
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", path],
                                            cwd=HERE).returncode, 0, path)
        with open(os.path.join(HERE, "deploy", "push_results.sh")) as fh:
            self.assertIn("data/xposts)", fh.read())

    def test_restarts_on_its_own_config_and_no_wallet_or_posting(self):
        self.assertIn("xposts", xposts_bot.CONFIG_SECTIONS)
        for name in ("screener/xposts.py", "xposts_bot.py", "screener/xposts_report.py"):
            with open(os.path.join(HERE, name)) as fh:
                source = fh.read().lower()
            for word in ("private_key", "keypair", "sign_transaction", ".post(", "requests.post"):
                self.assertNotIn(word, source, name)


if __name__ == "__main__":
    unittest.main()
