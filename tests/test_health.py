"""Checks for the health section at the top of the daily comparison.
Run with:  python -m unittest -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

from run import load_config, run  # noqa: E402
from screener.compare import report  # noqa: E402
from screener.demo import DemoApi, DemoNewsHttp, demo_rpc_factory  # noqa: E402
from screener.github_issues import GitHubIssues  # noqa: E402
from screener.health import INFO, OK, WARN, health_lines, record_health  # noqa: E402

CFG = running(load_config())
NOW = datetime(2026, 10, 2, 0, 7, tzinfo=timezone.utc)


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


class FakeGitHub:
    def __init__(self, runs=(), pushed=None, broken=False, pushed_1min=None, reasons=None):
        self.runs, self.pushed, self.broken = list(runs), pushed, broken
        self.pushed_1min = pushed_1min
        self.reasons = reasons      # run id -> why it failed (run_failure)

    def run_failure(self, run_id):
        if self.reasons is None:
            raise RuntimeError("not asked in this test")
        return self.reasons[run_id]

    def workflow_runs(self, workflow, since):
        if self.broken:
            raise RuntimeError("GitHub answered with error 502")
        assert workflow == "screener.yml" and since == NOW - timedelta(hours=24)
        return self.runs

    def last_commit_time(self, path):
        assert path in ("data/launch", "data/main-1min", "data/momentum", "data/news-listings")
        return self.pushed if path == "data/launch" else self.pushed_1min


def run_(conclusion, minutes_ago):
    return {"conclusion": conclusion, "updated_at": ago(minutes=minutes_ago)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, data):
        path = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)

    def healthy(self):
        for name in ("main", "early", "convergence", "news", "robinhood"):
            record_health(self.d, NOW - timedelta(minutes=4), {name: None})
        self.write("convergence/positions.json", {
            "helius": {"used": 1}, "tracked": [{"wallet": f"w{i}"} for i in range(5)],
            "list_updated": ago(days=1)})
        self.write("news/positions.json", {"sources": {
            "PR Newswire crypto": {"ok": True, "items": 20}}})
        self.write("robinhood/positions.json", {"sources": {
            name: {"ok": True, "calls": 3, "errors": 0, "rate_limited": 0, "at": ago(minutes=4)}
            for name in ("geckoterminal", "dexscreener", "goplus", "rpc")}})
        self.write("main-1min/health.json", {
            "last_ok": ago(minutes=50),
            "calls_per_hour": {"2026-10-01T23:00": {"runs": 60, "dexscreener": 250,
                                                    "rugcheck": 31}}})
        self.write("momentum/health.json", {"last_ok": ago(minutes=49), "feed_up": True})
        self.write("news-listings/health.json", {
            "last_ok": ago(minutes=48), "ai_key": True,
            "calls_per_hour": {"2026-10-01T23:00": {"runs": 60, "binance.com": 60,
                                                    "coingecko.com": 4}}})
        self.write("momentum/stats.json", {
            "2026-10-01 23:00": {"feed disconnects": 2, "launches seen": 1800,
                                 "30pct-2min: signals": 4, "30pct-2min: buys": 3}})
        return FakeGitHub([run_("success", 4), run_("success", 9)],
                          pushed=NOW - timedelta(minutes=50),
                          pushed_1min=NOW - timedelta(minutes=48))

    def lines(self, gh):
        text = "\n".join(health_lines(self.d, CFG, NOW, gh))
        rows = {line.split(" | ")[0][2:]: line for line in text.splitlines()
                if line.startswith("| ") and not line.startswith("| Check")}
        return text, rows


class HealthTests(Base):
    def test_news_listings_rows(self):
        gh = self.healthy()
        text, rows = self.lines(gh)
        self.assertIn(f"{OK} last good run 2026-10-01 23:19 UTC (48 min ago); 60 runs in 1 h, "
                      "4 CoinGecko call(s); last push", rows["news (listings): server"])
        self.assertNotIn("news: Binance listings", rows)        # read on the server now
        self.assertIn(INFO, rows["news (listings): AI check"])
        self.write("news-listings/positions.json", {
            "sources": {"Binance listings": {"ok": False, "error": "error 502"},
                        "Coinbase new pairs": {"ok": True, "items": 0, "markets": 406}},
            "ai": {"day": "2026-10-02", "calls": 3, "last_ok": ago(minutes=30)}})
        text, rows = self.lines(gh)
        self.assertIn(f"{WARN} failing: error 502", rows["news (listings): Binance listings"])
        self.assertIn("406 coin(s) listed", rows["news (listings): Coinbase new pairs"])
        self.assertIn(f"{INFO} not checked yet", rows["news (listings): Kraken blog"])
        self.assertIn(f"{OK} 3 of 50 checks today", rows["news (listings): AI check"])
        self.write("news-listings/health.json", {"last_ok": ago(hours=5)})
        _, rows = self.lines(gh)
        self.assertIn("(older than 3 h)", rows["news (listings): server"])
        self.write("news-listings/health.json", {})
        _, rows = self.lines(gh)
        self.assertIn("Part J", rows["news (listings): server"])

    def test_news_listings_fast_row(self):
        gh = self.healthy()
        _, rows = self.lines(gh)
        self.assertEqual(rows["news (listings) fast"],
                         f"| news (listings) fast | {INFO} half at +20%, the rest 10% below its "
                         "peak, everything at -10% or after 6 h; 0 open |")
        self.write("news-listings/fast/positions.json", {
            "last_prices": ago(minutes=4),
            "open_positions": [{"symbol": "NEW", "entry_time": ago(hours=2)}]})
        _, rows = self.lines(gh)
        self.assertIn(f"{INFO} half at", rows["news (listings) fast"])
        self.assertIn("1 open; prices checked 2026-10-02 00:03 UTC (4 min ago)",
                      rows["news (listings) fast"])
        self.write("news-listings/fast/positions.json", {
            "open_positions": [{"symbol": "OLD", "entry_time": ago(hours=10)}]})
        text, rows = self.lines(gh)
        self.assertIn(f"{WARN}", rows["news (listings) fast"])
        self.assertIn("still open past the 6 h limit: OLD", rows["news (listings) fast"])

    def test_all_ok(self):
        text, rows = self.lines(self.healthy())
        self.assertIn("**All checks OK.**", text)
        self.assertNotIn(WARN, text)
        self.assertIn("0 failed of 2; last successful run 2026-10-02 00:03 UTC (4 min ago)",
                      rows["Scheduled runs (last 24h)"])
        self.assertIn("5 tracked (list from 2026-10-01)", rows["convergence: wallets"])
        self.assertIn(f"{OK} 20 item(s)", rows["news: PR Newswire crypto"])
        self.assertIn("last push 2026-10-01 23:17 UTC (50 min ago)", rows["launch: server push"])

    def test_runs_github_never_started_are_not_the_codes_failures(self):
        self.healthy()
        runs = [dict(run_("failure", 50 + i), id=i) for i in range(9)]
        runs += [dict(run_("failure", 40), id=9), run_("success", 4)]
        gh = FakeGitHub(runs, pushed=NOW - timedelta(minutes=50),
                        pushed_1min=NOW - timedelta(minutes=48),
                        reasons={**{i: "no machine" for i in range(9)},
                                 9: "Save results to the repository"})
        cfg = dict(CFG, health=dict(CFG["health"], max_failed_runs_24h=1))
        text = "\n".join(health_lines(self.d, cfg, NOW, gh))
        row = next(r for r in text.splitlines() if r.startswith("| Scheduled runs"))
        self.assertIn("ℹ️ 10 failed of 11 (9 never started: GitHub had no machine free, "
                      "which is GitHub's trouble, not the code's); failed at \"Save results to "
                      "the repository\"; last successful run", row)
        # more real failures than allowed: a warning again
        found = []
        health_lines(self.d, CFG, NOW, gh, found=found)
        self.assertEqual(found[0]["check"], "Scheduled runs (last 24h)")

    def test_failed_runs_and_no_success(self):
        gh = self.healthy()
        gh.runs = [run_("failure", 5), run_("success", 10), run_("cancelled", 12)]
        text, rows = self.lines(gh)
        self.assertIn(f"{WARN} 1 failed of 3", rows["Scheduled runs (last 24h)"])
        self.assertIn("1 problem(s) need a look", text)
        gh.runs = [run_("failure", 5), run_("timed_out", 30)]
        _, rows = self.lines(gh)
        self.assertIn("2 failed of 2; no successful run in 24h", rows["Scheduled runs (last 24h)"])

    def test_stale_and_skipped_strategies(self):
        gh = self.healthy()
        record_health(self.d, NOW - timedelta(minutes=2), {"early": "GeckoTerminal down"})
        with open(os.path.join(self.d, "health.json")) as fh:
            data = json.load(fh)
        data["strategies"]["news"]["last_ok"] = ago(hours=3)
        self.write("health.json", data)
        text, rows = self.lines(gh)
        self.assertIn(WARN, rows["early: last successful run"])
        self.assertIn("skipped since 00:05 UTC: GeckoTerminal down",
                      rows["early: last successful run"])
        self.assertIn("(older than 60 min)", rows["news: last successful run"])
        self.assertIn(OK, rows["main: last successful run"])
        self.assertIn("2 problem(s)", text)
        # a later good run clears the error
        record_health(self.d, NOW - timedelta(minutes=1), {"early": None})
        _, rows = self.lines(gh)
        self.assertIn(OK, rows["early: last successful run"])

    def test_convergence_problems(self):
        gh = self.healthy()
        self.write("convergence/positions.json", {
            "helius": {"used": 1}, "tracked": [{"wallet": "w"}], "paused_until": ago(days=-3),
            "refresh": {"scored": {"a": {}}, "queue": ["b", "c"]}})
        _, rows = self.lines(gh)
        self.assertIn("1 tracked; rebuilding: 1 scored, 2 to go - fewer than 3",
                      rows["convergence: wallets"])
        self.assertIn(WARN, rows["convergence: Helius"])
        self.write("convergence/positions.json", {})
        _, rows = self.lines(gh)
        self.assertIn("HELIUS_API_KEY", rows["convergence: wallets"])

    def test_failing_news_source(self):
        gh = self.healthy()
        self.write("news/positions.json", {"sources": {
            "Chainlink press releases": {"ok": False, "error": "not a valid feed | bad"}}})
        text, rows = self.lines(gh)
        self.assertIn(f"{WARN} failing: not a valid feed / bad",
                      rows["news: Chainlink press releases"])
        self.assertIn("> - news: Chainlink press releases: failing", text)

    def test_a_row_for_every_news_source(self):
        gh = self.healthy()
        self.write("news/positions.json", {"sources": {
            "PR Newswire": {"ok": True, "items": 20, "newest": ago(hours=2)},
            "Quant blog": {"ok": True, "items": 10, "newest": ago(days=40)}}})
        self.write("news-listings/positions.json", {"sources": {
            "Binance listings": {"ok": True, "items": 20, "newest": ago(days=3)},
            "Coinbase new pairs": {"ok": True, "items": 0, "markets": 420},
            "Upbit new markets": {"ok": True, "items": 0, "markets": 250,
                                  "newest": ago(days=2)}}})
        text, rows = self.lines(gh)
        self.assertIn(f"{OK} 20 item(s), newest 2026-10-01", rows["news: PR Newswire"])
        self.assertIn(f"{WARN} 10 item(s), newest 2026-08-23: nothing new for 40 days "
                      "(expected within 30)", rows["news: Quant blog"])
        self.assertIn(OK, rows["news (listings): Binance listings"])
        self.assertIn(f"{OK} 420 coin(s) listed; no new listing seen yet",
                      rows["news (listings): Coinbase new pairs"])
        self.assertIn(f"{OK} 250 coin(s) listed, newest",
                      rows["news (listings): Upbit new markets"])
        self.assertIn(f"{INFO} not checked yet", rows["news: SEC EDGAR fund filings"])
        self.assertIn(f"{INFO} turned off: Bybit blocks", rows["news: Bybit listings"])
        names = [s["name"] for s in CFG["news"]["sources"] if s.get("runs_on") != "server"]
        self.assertEqual(sorted(k[6:] for k in rows if k.startswith("news: ")
                                and k not in ("news: last successful run", "news: AI check")),
                         sorted(names))

    def test_launch_never_or_late(self):
        gh = self.healthy()
        gh.pushed = None
        _, rows = self.lines(gh)
        self.assertIn("no results pushed yet", rows["launch: server push"])
        gh.pushed = NOW - timedelta(hours=5)
        _, rows = self.lines(gh)
        self.assertIn("(older than 3 h)", rows["launch: server push"])
        self.assertIn(WARN, rows["launch: server push"])

    def test_launch_from_stats_without_github(self):
        self.healthy()
        self.write("launch/stats.json", {"2026-10-01 23:00": {"launches_seen": 9}})
        text, rows = self.lines(None)
        self.assertIn("latest hour in stats.json 2026-10-01 23:00 UTC", rows["launch: server push"])
        self.assertIn("not checked: no GitHub token", rows["Scheduled runs (last 24h)"])

    def test_github_down_doesnt_break_the_report(self):
        gh = self.healthy()
        gh.broken = True
        _, rows = self.lines(gh)
        self.assertIn("couldn't ask GitHub: GitHub answered with error 502",
                      rows["Scheduled runs (last 24h)"])

    def test_health_is_at_the_top_of_the_report(self):
        # under the real-money checklist (none for a stopped strategy)
        body = report([("main (stopped)", self.d, 3)], "2026-10-01",
                      health=["### Health (x)", ""])
        lines = body.splitlines()
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "### Health (x)")
        self.assertTrue(lines[5].startswith("| | main"))
        body = report([("main", self.d, 3)], "2026-10-01", health=["### Health (x)", ""])
        lines = body.splitlines()
        self.assertEqual(lines[3], "### Real-money checklist")
        self.assertLess(lines.index("### Real-money checklist"), lines.index("### Health (x)"))


class MainOneMinuteHealthTests(Base):
    def row(self, gh):
        return self.lines(gh)[1]["main (1 min): server"]

    def test_stopped_main_versions_and_c(self):
        """The real config (2026-10-07): main (1 min)'s own buying and A
        stopped, B and C running; robinhood and momentum stopped."""
        gh = self.healthy()
        self.write("main-1min/positions.json", {"open_positions": [{"address": "X"}]})
        self.write("main-1min/a/positions.json", {"open_positions": [{"address": "Y"}]})
        h = json.load(open(os.path.join(self.d, "main-1min", "health.json")))
        h["versions"] = {"B": {"open": 1}, "C": {"open": 0, "decided": 37}}
        hour = list(h["calls_per_hour"])[0]
        h["calls_per_hour"][hour].update({"C buys": 2, "C skipped": 5})
        self.write("main-1min/health.json", h)
        real = load_config()
        text = "\n".join(health_lines(self.d, real, NOW, gh))
        rows = {line.split(" | ")[0][2:]: line for line in text.splitlines()
                if line.startswith("| ") and not line.startswith("| Check")}
        self.assertIn("its own buying is stopped (1 open position(s) finishing), its checks "
                      "still run for the versions", rows["main (1 min): server"])
        self.assertIn(f"{INFO} stopped (no new buys); 1 open position(s) finishing",
                      rows["main (1 min) A: server"])
        c = rows["main (1 min) C: server"]
        self.assertIn(OK, c)
        self.assertIn("0 open; last 24 h: 2 buy(s), 5 passed main but skipped by its rules", c)
        self.assertIn("37 token(s) decided (kept 14 days)", c)
        self.assertIn("decided once, at a token's first passing minute", c)
        self.assertIn(f"{INFO} stopped: finished, no sources read", rows["robinhood: data sources"])
        self.assertNotIn("robinhood: geckoterminal", rows)
        self.assertIn(f"{INFO} stopped (no new buys); 0 open position(s): finished, the "
                      "momentum-bot service can be turned off", rows["momentum: server"])

    def test_ok_with_runs_requests_and_push(self):
        row = self.row(self.healthy())
        self.assertIn(OK, row)
        self.assertIn("last good run 2026-10-01 23:17 UTC (50 min ago); 60 runs in 1 h; "
                      "busiest hour: 250 DexScreener, 31 RugCheck requests; "
                      "last push 2026-10-01 23:19 UTC (48 min ago)", row)

    def test_never_pushed(self):
        gh = self.healthy()
        os.remove(os.path.join(self.d, "main-1min", "health.json"))
        row = self.row(gh)
        self.assertIn(WARN, row)
        self.assertIn("no results pushed yet", row)
        self.assertIn("Part G", row)

    def test_late_or_skipped(self):
        gh = self.healthy()
        gh.pushed_1min = NOW - timedelta(hours=4)
        self.assertIn("(older than 3 h)", self.row(gh))
        self.assertIn(WARN, self.row(gh))
        gh = self.healthy()
        self.write("main-1min/health.json", {
            "last_ok": ago(minutes=50), "last_error": "api.dexscreener.com kept saying "
            "'too many requests'", "error_at": ago(minutes=49),
            "rugcheck_paused_until": ago(minutes=-3)})
        row = self.row(gh)
        self.assertIn(WARN, row)
        self.assertIn("skipped since 23:18 UTC: api.dexscreener.com kept saying", row)
        self.assertIn("RugCheck paused until 00:10 UTC", row)

    def test_no_row_when_turned_off(self):
        cfg = dict(CFG, main_1min=dict(CFG["main_1min"], enabled=False))
        text = "\n".join(health_lines(self.d, cfg, NOW, self.healthy()))
        self.assertNotIn("main (1 min)", text)


class MomentumHealthTests(Base):
    def test_ok_with_feed_disconnects_signals_and_buys(self):
        row = self.lines(self.healthy())[1]["momentum: server"]
        self.assertIn(OK, row)
        self.assertIn("feed last up 2026-10-01 23:18 UTC (49 min ago); last 24 h: 2 "
                      "disconnect(s) (2.0 an hour, 0 this hour), down 0 min (0.0%), 1800 "
                      "launches, 4 signal(s), 3 buy(s); last push", row)

    def test_disconnect_rate_endpoints_and_down_time(self):
        gh = self.healthy()
        self.write("momentum/health.json", {"last_ok": ago(minutes=49), "feed_up": True,
                                            "endpoint": "solana-rpc.publicnode.com"})
        self.write("momentum/stats.json", {
            "2026-10-01 22:00": {"feed disconnects": 12, "feed down seconds": 150,
                                 "feed disconnects: api.mainnet-beta.solana.com": 11,
                                 "feed disconnects: solana-rpc.publicnode.com": 1},
            "2026-10-01 23:00": {"feed disconnects": 3, "feed down seconds": 30,
                                 "feed disconnects: solana-rpc.publicnode.com": 3,
                                 "feed endpoint switches": 1}})
        row = self.lines(gh)[1]["momentum: server"]
        self.assertIn(OK, row)
        self.assertIn("on solana-rpc.publicnode.com; last 24 h: 15 disconnect(s) (7.5 an hour, "
                      "0 this hour; api.mainnet-beta.solana.com 11, solana-rpc.publicnode.com 4)"
                      ", down 3 min (2.5%), 1 endpoint switch(es)", row)
        # down more than max_down_pct (5%) of the time: a warning
        self.write("momentum/stats.json", {"2026-10-01 23:00": {"feed disconnects": 40,
                                                                "feed down seconds": 600}})
        row = self.lines(gh)[1]["momentum: server"]
        self.assertIn(WARN, row)
        self.assertIn("down 10 min (16.7%)", row)
        self.assertIn("(down more than 5% of the time)", row)

    def test_never_pushed_or_late(self):
        gh = self.healthy()
        os.remove(os.path.join(self.d, "momentum", "health.json"))
        row = self.lines(gh)[1]["momentum: server"]
        self.assertIn(WARN, row)
        self.assertIn("Part I", row)
        gh = self.healthy()
        self.write("momentum/health.json", {"last_ok": ago(hours=4), "feed_up": False})
        row = self.lines(gh)[1]["momentum: server"]
        self.assertIn(WARN, row)
        self.assertIn("(older than 3 h)", row)
        self.assertIn("the feed was down at the last save", row)


class RunIntervalTests(Base):
    def test_time_between_runs(self):
        gh = self.healthy()
        start = NOW - timedelta(hours=2)
        gh.runs = [{"conclusion": "success", "event": "schedule", "updated_at": ago(minutes=1),
                    "run_started_at": (start + timedelta(minutes=m)).isoformat()}
                   for m in (0, 15, 35, 50)]
        gh.runs.append({"conclusion": "success", "event": "workflow_dispatch",
                        "updated_at": ago(minutes=1),
                        "run_started_at": (start + timedelta(minutes=40)).isoformat()})
        text, rows = self.lines(gh)
        # The run the server started (workflow_dispatch) counts too.
        self.assertIn("ℹ️ average 12.5 min, median 15 min, longest 20 min (5 runs: 4 scheduled "
                      "by GitHub, 1 started by the server or by hand; the schedule asks for "
                      "every 5 min)", rows["Time between runs (last 24h)"])
        self.assertIn("**All checks OK.**", text)            # information, not a problem

    def test_actual_intervals_for_the_before_after_table(self):
        from screener.compare import actual_intervals, schedule_lines
        path = os.path.join(self.d, "schedule.json")
        self.write("schedule.json", {"history": [
            {"every_minutes": 15, "since": "2026-09-30T00:00:00+00:00"},
            {"every_minutes": 5, "since": "2026-10-01T00:00:00+00:00"}]})
        asked = []

        def count(a, b):
            asked.append((a, b))
            return 72 if a.day == 30 else 55        # 24h / 72 = 20 min; 24h7m / 55

        actual = actual_intervals(path, count, NOW)
        self.assertEqual(asked[0][1], asked[1][0])           # the change time
        self.assertEqual(round(actual["before"]), 20)
        self.assertEqual(round(actual["after"]), 26)
        lines = schedule_lines([("main", self.d, 3)], path, actual)
        self.assertIn("| main, every 15 min (actually ~20) | main, every 5 min (actually ~26) |",
                      lines[2])
        self.assertIn("real average time between runs comes from GitHub", lines[0])
        plain = schedule_lines([("main", self.d, 3)], path)
        self.assertIn("| main, every 15 min | main, every 5 min |", plain[2])
        self.assertIn("real intervals not checked", plain[0])


class GitHubApiTests(unittest.TestCase):
    def test_workflow_runs_and_last_commit(self):
        def answer(json_body, next_url=None):
            links = {"next": {"url": next_url}} if next_url else {}
            return mock.Mock(status_code=200, json=lambda: json_body, links=links)

        gh = GitHubIssues("tok", "me/repo")
        with mock.patch("screener.github_issues.requests.request", side_effect=[
                answer({"workflow_runs": [{"id": 1}]}, "https://api.github.com/next"),
                answer({"workflow_runs": [{"id": 2}]}),
                answer([{"commit": {"committer": {"date": "2026-10-01T23:17:00Z"}}}])]) as req:
            runs = gh.workflow_runs("screener.yml", NOW - timedelta(hours=24))
            pushed = gh.last_commit_time("data/launch")
        self.assertEqual([r["id"] for r in runs], [1, 2])
        first = req.call_args_list[0].args[1]
        self.assertIn("/repos/me/repo/actions/workflows/screener.yml/runs?created=%3E%3D"
                      "2026-10-01T00:07:00Z", first)
        self.assertIn("/commits?path=data/launch&per_page=1", req.call_args_list[2].args[1])
        self.assertEqual(pushed, datetime(2026, 10, 1, 23, 17, tzinfo=timezone.utc))

    def test_count_runs(self):
        gh = GitHubIssues("tok", "me/repo")
        answer = mock.Mock(status_code=200, json=lambda: {"total_count": 72}, links={})
        with mock.patch("screener.github_issues.requests.request", return_value=answer) as req:
            n = gh.count_runs("screener.yml", datetime(2026, 9, 30, tzinfo=timezone.utc),
                              datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(n, 72)
        url = req.call_args.args[1]
        self.assertIn("created=2026-09-30T00%3A00%3A00Z..2026-10-01T00%3A00%3A00Z", url)
        self.assertIn("event=schedule&per_page=1", url)


class RobinhoodSourceTests(Base):
    def test_a_row_for_each_data_source(self):
        gh = self.healthy()
        self.write("robinhood/positions.json", {"sources": {
            "geckoterminal": {"ok": True, "calls": 3, "errors": 1, "rate_limited": 1,
                              "at": ago(minutes=4)},
            "dexscreener": {"ok": True, "calls": 2, "errors": 0, "rate_limited": 0,
                            "at": ago(minutes=4)},
            "goplus": {"ok": False, "calls": 2, "errors": 2, "rate_limited": 0,
                       "error": "api.gopluslabs.io answered with error 500",
                       "at": ago(minutes=4)}},
            "gecko_hours": {"2026-09-30 20:00": [9, 9, 9],          # over 24 h ago
                            "2026-10-01 22:00": [10, 3, 1], "2026-10-01 23:00": [11, 1, 0]}})
        text, rows = self.lines(gh)
        self.assertIn("✅ 3 call(s), 1 failed, 1 rate-limited", rows["robinhood: geckoterminal"])
        self.assertIn("; last 24 h: a 429 in 4 of 21 run(s), 1 missed a list",
                      rows["robinhood: geckoterminal"])
        self.assertIn("✅", rows["robinhood: dexscreener"])
        self.assertIn("⚠️ failing", rows["robinhood: goplus"])
        self.assertIn("error 500", rows["robinhood: goplus"])
        self.assertIn("ℹ️ not used yet", rows["robinhood: rpc"])
        self.assertIn("1 problem(s)", text)


class RecordTests(Base):
    def test_every_run_records_each_strategy(self):
        run(DemoApi(), CFG, self.d, out=lambda *a: None, rpc_factory=demo_rpc_factory(),
            news_http=DemoNewsHttp())
        with open(os.path.join(self.d, "health.json")) as fh:
            data = json.load(fh)
        self.assertEqual(sorted(data["strategies"]), ["convergence", "early", "main", "news"])
        self.assertTrue(all("last_ok" in s for s in data["strategies"].values()))

    def test_skipped_strategy_is_recorded(self):
        record_health(self.d, NOW, {"main": None, "news": "CoinGecko said 'too many requests'"})
        with open(os.path.join(self.d, "health.json")) as fh:
            data = json.load(fh)
        self.assertEqual(data["updated"], NOW.isoformat())
        self.assertNotIn("last_ok", data["strategies"]["news"])
        self.assertEqual(data["strategies"]["news"]["last_error"],
                         "CoinGecko said 'too many requests'")


if __name__ == "__main__":
    unittest.main()
