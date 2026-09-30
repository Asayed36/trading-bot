"""Automated checks that the screener and paper trader follow the rules.
Run with:  python -m unittest -v
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run as run_module  # noqa: E402
from run import EXIT_RATE_LIMITED, load_config, run  # noqa: E402
from screener.api import PublicApi, RateLimited  # noqa: E402
from screener.github_issues import GitHubError, GitHubIssues, MARKER  # noqa: E402
from screener import filters  # noqa: E402
from screener.demo import GOOD, TOKENS, DemoApi  # noqa: E402
from screener.filters import FAIL, PASS, WARN, Result  # noqa: E402
from screener.paper_trader import PaperTrader, now_utc  # noqa: E402

CFG = load_config()


def read(path):
    with open(path) as fh:
        return fh.read()


def status(checks, name):
    return next(c.status for c in checks if c.name.startswith(name))


class FilterTests(unittest.TestCase):
    def test_demo_run_only_buys_clean_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            results = run(DemoApi(), CFG, d, out=lambda *a: None)
        passed = sorted(r.symbol for r in results if r.passed)
        self.assertEqual(passed, ["FRENS", "GOODCAT"])  # FRENS passes with a WARN
        self.assertEqual(len(results), len(TOKENS))  # the ethereum token was ignored

    def test_insiders_are_warning_by_default_but_can_fail(self):
        pair, report = TOKENS["DEMOinsider"]
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Insider"), WARN)
        strict = dict(CFG["filters"], insider_networks_are_fail=True)
        self.assertEqual(status(filters.safety_checks(report, pair, strict), "Insider"), FAIL)

    def test_missing_data_fails(self):
        f = CFG["filters"]
        self.assertEqual(filters.market_checks(None, f)[0].status, FAIL)
        self.assertEqual(filters.safety_checks(None, None, f)[0].status, FAIL)
        pair = dict(TOKENS[GOOD][0], liquidity={}, marketCap=None, fdv=None)
        checks = filters.market_checks(pair, f)
        self.assertEqual(status(checks, "Liquidity"), FAIL)
        self.assertEqual(status(checks, "Market cap"), FAIL)

    def test_pool_wallet_not_counted_as_holder(self):
        pair, report = TOKENS[GOOD]
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Top 10"), PASS)
        keep_pools = dict(CFG["filters"], exclude_pools_from_holders=False)
        self.assertEqual(status(filters.safety_checks(report, pair, keep_pools), "Top 10"), FAIL)

    def test_live_rugcheck_market_shape(self):
        # Real RugCheck reports give liquidityA/B as vault addresses and
        # liquidityAAccount/BAccount as parsed account dicts, not strings.
        pair, report = TOKENS[GOOD]
        vault = {"mint": "x", "owner": pair["pairAddress"], "amount": 1}
        markets = [dict(m, liquidityA="VAULT-A", liquidityB="VAULT-B",
                        liquidityAAccount=vault, liquidityBAccount=dict(vault))
                   for m in report["markets"]]
        report = dict(report, markets=markets)
        checks = filters.safety_checks(report, pair, CFG["filters"])
        self.assertEqual(status(checks, "Top 10"), PASS)
        self.assertEqual(status(checks, "LP locked"), PASS)

    def test_lp_fails_when_traded_pool_missing(self):
        # Another pool being 100% locked must not vouch for the one we trade in.
        pair, report = TOKENS[GOOD]
        pair = dict(pair, pairAddress="SOME-OTHER-POOL")
        checks = filters.safety_checks(report, pair, CFG["filters"])
        self.assertEqual(status(checks, "LP locked"), FAIL)

    def test_creator_check_without_balance_field(self):
        pair, report = TOKENS[GOOD]
        report = dict(report, creatorBalance=None)
        # creator isn't among the holders, all of whom hold < 5%
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Creator"), PASS)
        report["topHolders"] = report["topHolders"] + [{"address": "x", "owner": "CREATOR", "pct": 9}]
        self.assertEqual(status(filters.safety_checks(report, pair, CFG["filters"]), "Creator"), FAIL)

    def test_prefers_allowed_dex_pool(self):
        curve = dict(TOKENS[GOOD][0], dexId="pumpfun", liquidity={"usd": 999_999})
        chosen = filters.best_pair([curve, TOKENS[GOOD][0]], GOOD, ["pumpswap", "raydium"])
        self.assertEqual(chosen["dexId"], "pumpswap")


class RateLimitedDemoApi(DemoApi):
    def rugcheck_report(self, address):
        raise RateLimited("RugCheck kept saying 'too many requests'")


class RateLimitTests(unittest.TestCase):
    def test_repeated_429_raises_rate_limited(self):
        api = PublicApi()
        with mock.patch("screener.api.requests.get",
                        return_value=mock.Mock(status_code=429)) as get, \
                mock.patch("screener.api.time.sleep"):
            with self.assertRaises(RateLimited):
                api.latest_profiles()
        self.assertEqual(get.call_count, 3)

    def test_rate_limited_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            run(DemoApi(), CFG, d, out=lambda *a: None)  # buys GOODCAT and FRENS
            files = [os.path.join(d, n) for n in ("positions.json", "journal.csv")]
            before = [read(p) for p in files]
            # GOODCAT's price has halved (a stop loss would sell), but RugCheck
            # is rate limited, so the whole run must be skipped untouched.
            with self.assertRaises(RateLimited):
                run(RateLimitedDemoApi({GOOD: 0.5}), CFG, d, out=lambda *a: None)
            self.assertEqual([read(p) for p in files], before)

    def test_main_exits_with_skip_code_when_rate_limited(self):
        with mock.patch.object(run_module, "run", side_effect=RateLimited("429")), \
                mock.patch.object(sys, "argv", ["run.py"]), \
                mock.patch("builtins.print"):
            self.assertEqual(run_module.main(), EXIT_RATE_LIMITED)


class FakeGitHub(GitHubIssues):
    """Records what would be sent to GitHub. Set `down` to make calls fail."""

    def __init__(self, existing=None):
        super().__init__("token", "me/repo")
        self.issues, self.comments, self.closed = {}, [], []
        self.known = dict(existing or {})
        self.down = set()  # names of methods that should fail

    def _check(self, name):
        if name in self.down:
            raise GitHubError(f"{name} failed")

    def ensure_label(self):
        self._check("ensure_label")

    def existing(self):
        self._check("existing")
        return dict(self.known)

    def create(self, title, body):
        self._check("create")
        number = 100 + len(self.issues)
        self.issues[number] = {"title": title, "body": body}
        return number

    def comment(self, number, body):
        self._check("comment")
        self.comments.append((number, body))

    def close(self, number):
        self._check("close")
        self.closed.append(number)


class GitHubIssueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gh = FakeGitHub()

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, moves=None):
        run(DemoApi(moves), CFG, self.tmp.name, out=lambda *a: None, issues=self.gh)
        return PaperTrader(CFG["paper_trading"], self.tmp.name)

    def issue_for(self, symbol):
        return next(i for i in self.gh.issues.values() if i["title"] == f"PASSED: {symbol}")

    def test_issue_opened_with_details_and_exit_levels(self):
        trader = self.go()
        self.assertEqual(sorted(i["title"] for i in self.gh.issues.values()),
                         ["PASSED: FRENS", "PASSED: GOODCAT"])
        body = self.issue_for("GOODCAT")["body"]
        pair = TOKENS[GOOD][0]
        for text in (MARKER.format(GOOD), "Demo GOODCAT", f"`{GOOD}`", pair["url"],
                     "$0.0008 |", "$800,000", "$60,000", "+45%",
                     "$0.0012 (+50%)", "$0.00056 (-30%)", "Starts at $0.00048",
                     "if the price is still within ±10% of entry",
                     CFG["github_issues"]["note"]):
            self.assertIn(text, body)
        self.assertEqual(body.count("| `h"), 9)  # 10 real wallets: whale + 9 of h0..h11
        self.assertIn("| 1 | `whale` | 2.00% |", body)
        self.assertNotIn("AMM-AUTH", body)  # the pool wallet isn't a holder
        pos = trader.position(GOOD)
        self.assertEqual(self.gh.issues[pos["issue"]]["title"], "PASSED: GOODCAT")

    def test_no_duplicate_issues(self):
        self.go()
        self.go()
        self.assertEqual(len(self.gh.issues), 2)

    def test_reuses_issue_already_on_github(self):
        # e.g. the issue was opened but the commit saving its number was lost
        self.gh.known = {GOOD: 7}
        trader = self.go()
        self.assertEqual(trader.position(GOOD)["issue"], 7)
        self.assertEqual(len(self.gh.issues), 1)  # only FRENS is new

    def test_closing_position_comments_and_closes(self):
        self.go()
        number = PaperTrader(CFG["paper_trading"], self.tmp.name).position(GOOD)["issue"]
        trader = self.go({GOOD: 0.5})  # down 50%: stop loss sells everything
        self.assertEqual(self.gh.closed, [number])
        (commented, text), = self.gh.comments
        self.assertEqual(commented, number)
        self.assertIn("stop loss: down 50% from entry", text)
        self.assertIn("$0.0004", text)
        self.assertIn("**Result:** $-5.30 (-53.0% on $10, after fees)", text)
        self.assertFalse(trader.state["issues_to_close"])

    def test_github_down_is_retried_next_run(self):
        self.gh.down = {"create"}
        trader = self.go()  # trading still happens
        self.assertEqual(len(trader.open_positions), 2)
        self.assertFalse(self.gh.issues)
        self.gh.down = set()
        self.go()
        self.assertEqual(len(self.gh.issues), 2)

    def test_close_retry_does_not_comment_twice(self):
        self.go()
        self.gh.down = {"close"}
        trader = self.go({GOOD: 0.5})
        self.assertEqual(len(trader.state["issues_to_close"]), 1)
        self.gh.down = set()
        trader = self.go({GOOD: 0.5})
        self.assertEqual(len(self.gh.comments), 1)
        self.assertEqual(len(self.gh.closed), 1)
        self.assertFalse(trader.state["issues_to_close"])

    def test_position_closed_before_issue_opened(self):
        self.gh.down = {"create"}
        self.go()
        self.gh.down = set()
        self.go({GOOD: 0.5})  # issue opened, commented on and closed in one go
        number = next(n for n, i in self.gh.issues.items() if i["title"] == "PASSED: GOODCAT")
        self.assertEqual(self.gh.closed, [number])

    def test_http_requests(self):
        gh = GitHubIssues("tok123", "me/repo")
        created = mock.Mock(status_code=201)
        created.json.return_value = {"number": 42}
        ok = mock.Mock(status_code=200)
        missing = mock.Mock(status_code=404)
        with mock.patch("screener.github_issues.requests.request",
                        side_effect=[missing, created, created, ok, ok]) as req:
            gh.ensure_label()
            self.assertEqual(gh.create("PASSED: X", "body"), 42)
            gh.comment(42, "done")
            gh.close(42)
        calls = [(c.args[0], c.args[1], c.kwargs.get("json")) for c in req.call_args_list]
        base = "https://api.github.com/repos/me/repo"
        self.assertEqual(calls[0][:2], ("GET", f"{base}/labels/passed"))
        self.assertEqual(calls[1][:2], ("POST", f"{base}/labels"))
        self.assertEqual(calls[2], ("POST", f"{base}/issues",
                                    {"title": "PASSED: X", "body": "body", "labels": ["passed"]}))
        self.assertEqual(calls[3], ("POST", f"{base}/issues/42/comments", {"body": "done"}))
        self.assertEqual(calls[4], ("PATCH", f"{base}/issues/42",
                                    {"state": "closed", "state_reason": "completed"}))
        self.assertEqual(req.call_args.kwargs["headers"]["Authorization"], "Bearer tok123")
        with mock.patch("screener.github_issues.requests.request",
                        return_value=mock.Mock(status_code=403, text="forbidden")):
            with self.assertRaises(GitHubError):
                gh.create("t", "b")

    def test_existing_reads_markers_across_pages(self):
        gh = GitHubIssues("token", "me/repo")
        page1 = mock.Mock(status_code=200, links={"next": {"url": "https://api.github.com/p2"}})
        page1.json.return_value = [{"number": 1, "body": MARKER.format("AAA") + "\nhi"},
                                   {"number": 2, "body": "no marker"}]
        page2 = mock.Mock(status_code=200, links={})
        page2.json.return_value = [{"number": 3, "body": MARKER.format("BBB")}]
        with mock.patch("screener.github_issues.requests.request",
                        side_effect=[page1, page2]) as req:
            self.assertEqual(gh.existing(), {"AAA": 1, "BBB": 3})
        self.assertIn("labels=passed&state=all", req.call_args_list[0].args[1])


class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trader = PaperTrader(CFG["paper_trading"], self.tmp.name)
        self.t0 = now_utc()
        pair = dict(TOKENS[GOOD][0], priceUsd="1.0")
        self.trader.buy(Result(GOOD, "GOODCAT", "Demo", pair), when=self.t0)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, price, hours):
        return self.trader.update({GOOD: price}, when=self.t0 + timedelta(hours=hours))

    def journal(self):
        with open(self.trader.journal_path) as fh:
            return list(csv.DictReader(fh))

    def test_take_profit_sells_half(self):
        sells = self.at(1.5, 1)
        # half = $5 cost -> worth $7.50, minus 3% of $5 ($0.15) = +$2.35
        self.assertEqual(len(sells), 1)
        self.assertAlmostEqual(sells[0]["pnl_usd"], 2.35)
        self.assertEqual(self.trader.open_positions[0]["remaining_fraction"], 0.5)
        self.assertEqual(self.at(1.6, 2), [])  # doesn't sell half again

    def test_stop_loss(self):
        sells = self.at(0.7, 1)
        self.assertAlmostEqual(sells[0]["pnl_usd"], 7 - 10 - 0.3)
        self.assertEqual(self.trader.open_positions, [])

    def test_trailing_stop_after_peak(self):
        self.at(2.0, 1)                # take profit on half, peak = 2.0
        self.assertEqual(self.at(1.3, 2), [])   # 35% below peak: hold
        sells = self.at(1.2, 3)        # 40% below peak: sell the rest
        self.assertIn("trailing stop", sells[0]["reason"])
        self.assertAlmostEqual(sells[0]["pnl_usd"], 6 - 5 - 0.15)
        self.assertAlmostEqual(self.trader.state["running_total_pnl_usd"], 4.85 + 0.85)

    def test_time_exit_only_when_flat(self):
        self.assertEqual(self.at(1.05, 47), [])          # not 48h yet
        self.assertEqual(self.trader.update({GOOD: 1.15}, when=self.t0 + timedelta(hours=49)), [])
        sells = self.at(0.95, 50)
        self.assertIn("time exit", sells[0]["reason"])
        self.assertAlmostEqual(sells[0]["pnl_usd"], 9.5 - 10 - 0.3)

    def test_no_price_means_no_action(self):
        self.assertEqual(self.trader.update({}, when=self.t0 + timedelta(hours=100)), [])
        self.assertEqual(len(self.trader.open_positions), 1)

    def test_no_rebuy_and_journal(self):
        self.assertIsNone(self.trader.buy(Result(GOOD, "GOODCAT", "Demo", TOKENS[GOOD][0])))
        self.at(1.5, 1)
        self.at(0.8, 2)  # more than 40% below the 1.5 peak
        rows = self.journal()
        self.assertEqual([r["action"] for r in rows], ["BUY", "SELL", "SELL"])
        # first sell +2.35, second sell $4.00 - $5 - $0.15 = -1.15, total +1.20
        self.assertEqual(rows[-1]["pnl_usd"], "-1.15")
        self.assertEqual(rows[-1]["running_total_pnl_usd"], "1.20")
        self.assertIsNone(self.trader.buy(Result(GOOD, "GOODCAT", "Demo", TOKENS[GOOD][0])))

    def test_state_survives_restart(self):
        self.trader.save()
        again = PaperTrader(CFG["paper_trading"], self.tmp.name)
        self.assertEqual(len(again.open_positions), 1)


if __name__ == "__main__":
    unittest.main()
