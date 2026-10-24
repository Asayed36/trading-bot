"""Checks for stopped strategies (stopped = true in config.toml): no new
buys, open positions still finish under their normal exits, the files are
kept, and the comparison and health check say "stopped".
Run with:  python -m unittest -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402
from tests import test_robinhood as trh  # noqa: E402

import compare  # noqa: E402
import run as run_module  # noqa: E402
from run import load_config, run  # noqa: E402
from screener.compare import helius_lines  # noqa: E402
from screener.convergence import ConvergenceStrategy  # noqa: E402
from screener.demo import (EARLY_GOOD, GOOD, DemoApi, DemoRpc,  # noqa: E402
                           _swap as demo_swap, demo_trader_history)
from screener.paper_trader import now_utc  # noqa: E402
from screener.health import INFO, health_lines  # noqa: E402
from screener.launch import LaunchEngine  # noqa: E402
from screener.momentum import MomentumEngine  # noqa: E402
from screener.paper_trader import PaperTrader  # noqa: E402

REAL = load_config()              # as it is now: the stopped strategies stopped
TRACKED = ["whale", "h0", "h1"]
QUIET = dict(out=lambda *a: None)


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class ConfigTests(unittest.TestCase):
    def test_what_is_stopped_and_what_runs(self):
        self.assertTrue(REAL["main"]["stopped"])
        self.assertTrue(REAL["early"]["stopped"])
        self.assertTrue(REAL["launch"]["stopped"])
        momentum = {v["name"]: bool(v.get("stopped")) for v in REAL["momentum"]["variants"]}
        self.assertEqual(momentum, {"30pct-2min": True, "50pct-3min": True,
                                    "100pct-5min": True})
        # 2026-10-07: main (1 min)'s own buying and version A stopped too. 2026-10-23: B, C,
        # convergence and robinhood stopped as well (robinhood had been restarted on
        # 2026-10-11). main (1 min) itself keeps running its checks for the records.
        self.assertTrue(REAL["main_1min"]["stopped"])
        versions = {v["name"]: bool(v.get("stopped")) for v in REAL["main_1min"]["versions"]}
        self.assertEqual(versions, {"A": True, "B": True, "C": True})
        for name in ("main_1min", "convergence", "news", "news_listings", "robinhood"):
            self.assertTrue(REAL[name]["enabled"], name)
        for name in ("convergence", "robinhood"):
            self.assertTrue(REAL[name]["stopped"], name)

    def test_what_keeps_running(self):
        for name in ("news", "news_listings", "trend", "launch_record"):
            self.assertTrue(REAL[name]["enabled"], name)
            self.assertFalse(REAL[name].get("stopped"), name)
        self.assertFalse(REAL["scanner_alert"].get("stopped"))      # the alerts have no switch
        self.assertEqual([v["name"] for v in REAL["news_listings"].get("versions", [])
                          if v.get("stopped")], [])


class MainAndEarlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def test_main_screens_nothing_but_still_sells(self):
        run(DemoApi(), running(REAL), self.d, **QUIET)           # bought while running
        held = json.load(open(os.path.join(self.d, "positions.json")))["open_positions"]
        self.assertTrue(held)
        before = rows(os.path.join(self.d, "journal.csv"))
        lines = []
        with mock.patch("run.screen") as screen:
            run(DemoApi({GOOD: 0.5}), REAL, self.d, out=lines.append)   # -50%: the -30% stop
        screen.assert_not_called()                               # no screening at all
        after = rows(os.path.join(self.d, "journal.csv"))
        self.assertEqual(after[:len(before)], before)            # the journal is kept
        new = after[len(before):]
        self.assertTrue(new and all(r["action"] == "SELL" for r in new))
        self.assertIn("GOODCAT", [r["symbol"] for r in new])
        self.assertTrue(any("main strategy is stopped" in line for line in lines))

    def test_main_never_buys_when_stopped(self):
        run(DemoApi(), REAL, self.d, **QUIET)
        self.assertEqual(rows(os.path.join(self.d, "journal.csv")), [])

    def test_early_only_runs_while_it_holds_a_position(self):
        lines = []
        run(DemoApi(), REAL, self.d, out=lines.append)
        self.assertFalse(any("STEP 5" in line for line in lines))     # nothing held: not run
        self.assertEqual(rows(os.path.join(self.d, "early", "journal.csv")), [])

    def test_a_stopped_trader_still_sells(self):
        t = PaperTrader(REAL["paper_trading"], self.d)
        from types import SimpleNamespace
        r = SimpleNamespace(address="X", symbol="X", name="X", price=1.0, pair={}, insider=None)
        t.organic = None
        self.assertTrue(t.buy(r))
        t.buying = False
        self.assertFalse(t.can_buy("Y"))
        (sale,) = t.update({"X": 0.5})
        self.assertTrue(sale["closed"])


class ServerStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_launch_speeds_make_no_new_buys(self):
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: 0.0)
        self.assertEqual({n: t.buying for n, t in engine.traders.items()},
                         {"5s": False, "30s": False, "90s": False})
        engine = LaunchEngine(running(REAL), self.tmp.name, clock=lambda: 0.0)
        self.assertTrue(all(t.buying for t in engine.traders.values()))

    def stuck(self, minutes_ago):
        """The real stuck position (ATISWATER, 2026-10-05): bought at the
        creation price, never listed on DexScreener, so never priced again."""
        from datetime import datetime, timedelta, timezone
        entry = datetime(2026, 10, 5, 9, 13, 54, tzinfo=timezone.utc)
        for speed in ("5s", "30s", "90s"):
            folder = os.path.join(self.tmp.name, "launch", speed)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "positions.json"), "w") as fh:
                json.dump({"open_positions": [{
                    "address": "2esPLfhEwwNRHkE9vFazVGyPRH21LU4dzgztVhzBeRMP",
                    "symbol": "ATISWATER", "pair_address": None, "entry_time": entry.isoformat(),
                    "entry_price": 3.379403541472507e-06, "peak_price": 3.379403541472507e-06,
                    "tokens": 1378164.7982681117, "cost_usd": 5.36261, "remaining_fraction": 1.0,
                    "took_profit": False, "last_price": 3.372413793103448e-06,
                    "sol_usd_at_entry": 120.87}],
                    "ever_bought": ["2esPLfhEwwNRHkE9vFazVGyPRH21LU4dzgztVhzBeRMP"],
                    "running_total_pnl_usd": -100.0}, fh)
        return (entry + timedelta(minutes=minutes_ago)).timestamp()

    def test_stuck_positions_close_at_the_last_known_price(self):
        t = self.stuck(110)
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: t)
        self.assertEqual(len(engine.closed_stopped), 3)          # one per speed
        for speed, trader in engine.traders.items():
            self.assertEqual(trader.open_positions, [], speed)
            (row,) = rows(os.path.join(self.tmp.name, "launch", speed, "journal.csv"))
            self.assertEqual((row["action"], row["symbol"]), ("SELL", "ATISWATER"))
            self.assertEqual(row["reason"], "closed after the bot was stopped: at the last "
                                            "known price (-0%), no price after 110 min")
            self.assertAlmostEqual(float(row["price_usd"]), 3.3724137931e-06)
            # the normal costs: fees, slippage and the priority fee
            self.assertLess(float(row["pnl_usd"]), -1)
            saved = json.load(open(os.path.join(self.tmp.name, "launch", speed,
                                                "positions.json")))
            self.assertEqual(saved["open_positions"], [])
            self.assertAlmostEqual(saved["running_total_pnl_usd"], -100 + float(row["pnl_usd"]),
                                   places=1)

    def test_not_before_the_time_stop_and_grace_nor_when_running(self):
        t = self.stuck(35)
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: t)
        self.assertEqual(engine.closed_stopped, [])               # 30 min + 10 min grace
        t = self.stuck(500)
        engine = LaunchEngine(running(REAL), self.tmp.name, clock=lambda: t)
        self.assertEqual(engine.closed_stopped, [])               # running: normal exits only
        self.assertEqual(engine.close_stopped(t), [])

    def test_a_priced_position_keeps_its_normal_exits(self):
        t = self.stuck(20)
        engine = LaunchEngine(REAL, self.tmp.name, clock=lambda: t)
        mint = "2esPLfhEwwNRHkE9vFazVGyPRH21LU4dzgztVhzBeRMP"
        engine.set_sol_price(120.87)
        engine.set_external_prices({mint: 3.5e-06}, t)
        engine.migrated.add(mint)
        engine.tick(t + 30 * 60)                                  # its time stop, priced
        (row,) = rows(os.path.join(self.tmp.name, "launch", "5s", "journal.csv"))
        self.assertTrue(row["reason"].startswith("time stop: 50 min"), row["reason"])

    def test_close_stuck_command(self):
        import launch_bot
        self.stuck(0)
        lines = []
        self.assertEqual(launch_bot.close_stuck(REAL, self.tmp.name, out=lines.append), 0)
        self.assertEqual(len([x for x in lines if "SELL ATISWATER closed after the bot was "
                              "stopped" in x]), 3)
        self.assertIn("Closed 3 stuck position(s); 0 still open.", lines[-1])
        self.assertEqual(launch_bot.close_stuck(running(REAL), self.tmp.name,
                                                out=lines.append), 1)

    def test_no_momentum_variant_buys(self):
        engine = MomentumEngine(REAL, self.tmp.name, clock=lambda: 0.0)
        self.assertEqual({n: t.buying for n, t in engine.traders.items()},
                         {"30pct-2min": False, "50pct-3min": False, "100pct-5min": False})


class RobinhoodStoppedAgainTests(unittest.TestCase):
    """2026-10-23: robinhood is stopped again (no new buys), with its rules, costs and exits
    exactly as they were; unlike the others it keeps running its checks for candidates.csv."""

    def test_the_rules_costs_and_exits_are_unchanged(self):
        rh = REAL["robinhood"]
        self.assertTrue(rh["enabled"])
        self.assertTrue(rh["stopped"])
        self.assertEqual(rh["paper_trading"], {
            "buy_amount_usd": 10, "take_profit_pct": 50, "take_profit_sell_fraction": 0.5,
            "stop_loss_pct": 30, "trailing_stop_pct": 40, "max_hold_hours": 48,
            "stale_move_pct": 10, "allow_rebuy": False, "max_open_positions": 20,
            "slippage_pct": 2, "gas_usd_per_trade": 0.05})
        for key, value in (("min_pool_age_minutes", 30), ("max_pool_age_hours", 6),
                           ("recheck_minutes", 60), ("max_candidates_per_run", 10),
                           ("min_liquidity_usd", 10000), ("min_market_cap_usd", 25000),
                           ("max_drop_24h_pct", 50), ("max_creator_pct", 5),
                           ("max_top10_pct", 30), ("gecko_calls_per_run", 2),
                           ("goplus_max_per_run", 8), ("holder_checks_per_run", 4)):
            self.assertEqual(rh[key], value, key)

    def test_the_report_says_stopped_and_the_health_check_keeps_watching_its_sources(self):
        self.assertTrue(compare.stopped(REAL, "robinhood"))
        with tempfile.TemporaryDirectory() as d:
            from datetime import datetime, timezone
            text = "\n".join(health_lines(d, REAL, datetime(2026, 10, 24, tzinfo=timezone.utc)))
        self.assertIn(f"{INFO} stopped (no new buys); 0 open position(s): finished; its checks "
                      "still run, for candidates.csv", text)
        self.assertNotIn("robinhood: data sources", text)       # no "stopped" source row...
        self.assertIn("robinhood: geckoterminal", text)         # ...they are still watched
        self.assertIn("robinhood: rpc", text)

    def test_a_run_still_runs_the_strategy_but_does_not_buy(self):
        with tempfile.TemporaryDirectory() as d:
            strategies = []
            real = run_module.RobinhoodStrategy

            class Spy(real):
                def __init__(self, *a, **k):
                    super().__init__(*a, **k)
                    strategies.append(self)
            with mock.patch.object(run_module, "RobinhoodStrategy", Spy):
                run(DemoApi(), REAL, d, robinhood_http=object(), out=lambda *a: None)
        self.assertTrue(strategies)                             # it still runs...
        self.assertFalse(strategies[0].trader.buying)           # ...and cannot buy


class RobinhoodStoppedRunTests(trh.Base):
    """The strategy against made-up GeckoTerminal, DexScreener, GoPlus and RPC answers."""

    STOPPED = dict(trh.CFG, robinhood=dict(trh.C, stopped=True))

    def test_candidates_are_still_discovered_checked_and_recorded_but_nothing_is_bought(self):
        s, bought, text = self.run_once(cfg=self.STOPPED)
        self.assertEqual(bought, [])
        self.assertEqual(trh.rows(self.path("journal.csv")), [])
        self.assertEqual(trh.rows(self.path("entries.csv")), [])
        recorded = {r["symbol"]: r for r in trh.rows(self.path("candidates.csv"))}
        self.assertEqual(set(recorded), {"FROG", "GLITCH"})       # the same two as when running
        self.assertEqual({r["result"] for r in recorded.values()}, {"PASS"})
        self.assertIn("[PASS] FROG (Pons)", text)
        self.assertIn("Stopped: nothing is bought.", text)
        self.assertTrue(any(c[0] == "geckoterminal" for c in self.http.calls))
        self.assertTrue(any(c[0] == "goplus" for c in self.http.calls))
        self.assertTrue(any(c[0] == "rpc" for c in self.http.calls))

    def test_the_records_are_the_same_as_when_running(self):
        self.run_once(cfg=self.STOPPED)
        stopped_rows = {r["symbol"]: r for r in trh.rows(self.path("candidates.csv"))}
        self.tmp.cleanup()
        self.setUp()
        self.run_once()
        running_rows = {r["symbol"]: r for r in trh.rows(self.path("candidates.csv"))}
        keep = lambda r: {k: v for k, v in r.items() if k not in ("time_utc",)}   # noqa: E731
        self.assertEqual({k: keep(v) for k, v in stopped_rows.items()},
                         {k: keep(v) for k, v in running_rows.items()})

    def test_a_pool_that_passed_is_not_rechecked_every_hour_while_stopped(self):
        self.run_once(cfg=self.STOPPED)
        self.http.calls.clear()
        _, _, text = self.run_once(trh.NOW + timedelta(minutes=trh.C["recheck_minutes"] + 1),
                                   cfg=self.STOPPED)
        self.assertNotIn("FROG", text)
        self.assertEqual([c for c in self.http.calls if c[0] in ("goplus",)], [])

    def test_a_failed_pool_is_still_rechecked_so_the_records_follow_it(self):
        self.http.goplus[trh.PONS] = {"is_honeypot": "1"}
        self.run_once(cfg=self.STOPPED)
        _, _, text = self.run_once(trh.NOW + timedelta(minutes=trh.C["recheck_minutes"] + 1),
                                   cfg=self.STOPPED)
        self.assertIn("[FAIL] FROG", text)

    def test_positions_bought_while_running_still_close_under_the_normal_exits(self):
        self.run_once()                                          # running: FROG and GLITCH bought
        self.assertEqual(len(trh.rows(self.path("journal.csv"))), 2)
        self.http.pairs[trh.PONS] = [trh.pair(trh.PONS, trh.PONS_POOL, "FROG", 150, price=0.00016)]
        self.http.pairs[trh.POOLS] = [trh.pair(trh.POOLS, trh.POOLS_POOL, "GLITCH", 90,
                                               price=0.00006)]
        s = self.strategy(self.STOPPED)
        self.assertFalse(s.trader.buying)
        s.apply(s.fetch(trh.NOW + timedelta(hours=1)), lambda *_: None)
        sells = {r["symbol"]: r["reason"] for r in trh.rows(self.path("journal.csv"))
                 if r["action"] == "SELL"}
        self.assertIn("take profit: up 60%", sells["FROG"])
        self.assertIn("stop loss: down 40%", sells["GLITCH"])
        self.assertEqual(len([r for r in trh.rows(self.path("journal.csv"))
                              if r["action"] == "BUY"]), 2)      # and no third buy


class ConvergenceStoppedTests(unittest.TestCase):
    """2026-10-23: convergence is stopped: no new buys, and no Helius use to find them."""

    RUN = running(REAL)
    FAST = dict(RUN, convergence=dict(RUN["convergence"], helius_every_minutes=2))
    STOP = dict(RUN, convergence=dict(RUN["convergence"], helius_every_minutes=2, stopped=True))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "convergence")
        self.live, self.history = {}, demo_trader_history()

    def go(self, cfg, api=None, now=None):
        self.rpcs = []

        def factory(meter):
            rpc = SpyRpc(meter, self.history, self.live)
            self.rpcs.append(rpc)
            return rpc, rpc
        strategy = ConvergenceStrategy(cfg, self.tmp.name, rpc_factory=factory)
        lines = []
        plan = strategy.fetch(api or SpyApi(), now=now)
        strategy.apply(plan, lines.append)
        return strategy, plan, lines

    def state(self):
        with open(os.path.join(self.folder, "positions.json")) as fh:
            return json.load(fh)

    def swap(self, wallet, minutes_ago, mint=EARLY_GOOD, side="buy"):
        when = now_utc() - timedelta(minutes=minutes_ago)
        self.live.setdefault(wallet, []).append(demo_swap(mint, side, 0.5, 100.0, when))

    def hold_a_position(self):
        """Running: build the list, then three tracked wallets buy EARLY_GOOD together."""
        self.go(self.FAST)
        self.go(self.FAST)
        for wallet, ago in zip(TRACKED, (15, 9, 3)):
            self.swap(wallet, ago)
        strategy, _, _ = self.go(self.FAST)
        self.assertEqual(len(strategy.trader.open_positions), 1)
        return strategy

    def test_it_is_stopped_in_the_real_config_and_cannot_buy(self):
        self.assertTrue(REAL["convergence"]["stopped"])
        strategy = ConvergenceStrategy(self.STOP, self.tmp.name)
        self.assertFalse(strategy.trader.buying)
        self.assertTrue(ConvergenceStrategy(self.FAST, self.tmp.name).trader.buying)

    def test_a_signal_is_not_bought_and_no_wallet_checks_are_made(self):
        self.go(self.FAST)
        self.go(self.FAST)                                       # the tracked list exists
        for wallet, ago in zip(TRACKED, (15, 9, 3)):
            self.swap(wallet, ago)
        api = SpyApi()
        strategy, plan, lines = self.go(self.STOP, api)
        self.assertEqual(strategy.trader.open_positions, [])
        self.assertEqual(plan["signals"], [])
        self.assertTrue(all(r.calls == 0 for r in self.rpcs))    # not one Helius call
        self.assertEqual((api.profiles, api.boosts, api.rugchecks), (0, 0, 0))
        self.assertTrue(any("stopped" in line.lower() for line in lines))
        self.assertEqual(rows(os.path.join(self.folder, "journal.csv")), [])

    def test_the_list_building_the_winners_and_the_credits_are_left_alone(self):
        self.go(self.FAST)
        before = self.state()
        self.go(self.STOP)
        after = self.state()
        for key in ("tracked", "winners", "helius", "refresh", "list_updated"):
            self.assertEqual(after.get(key), before.get(key), key)

    def test_the_files_and_the_history_are_kept(self):
        self.hold_a_position()
        journal = rows(os.path.join(self.folder, "journal.csv"))
        self.go(self.STOP)
        self.assertEqual(rows(os.path.join(self.folder, "journal.csv"))[:len(journal)], journal)
        for name in ("positions.json", "journal.csv", "entries.csv", "candidates.csv",
                     "creator_ledger.json"):
            self.assertTrue(os.path.exists(os.path.join(self.folder, name)), name)

    def test_an_open_position_closes_on_its_normal_exits_at_the_price(self):
        self.hold_a_position()
        strategy, _, lines = self.go(self.STOP, SpyApi({EARLY_GOOD: 0.5}))     # -50%
        self.assertEqual(strategy.trader.open_positions, [])
        self.assertTrue(any("hard stop" in line for line in lines))
        sells = [r for r in rows(os.path.join(self.folder, "journal.csv")) if r["action"] == "SELL"]
        self.assertTrue(sells)

    def test_only_the_trigger_wallets_of_an_open_position_are_watched_for_the_wallet_exit(self):
        self.hold_a_position()
        state = self.state()
        state["tracked"].append({"wallet": "other-wallet", "stats": {}})
        with open(os.path.join(self.folder, "positions.json"), "w") as fh:
            json.dump(state, fh)
        self.swap("whale", 1, side="sell")
        self.swap("h0", 0, side="sell")                          # 2 of the 3 trigger wallets sold
        strategy, _, lines = self.go(self.STOP)
        asked = {w for r in self.rpcs for w in r.asked}
        self.assertEqual(asked, set(TRACKED))                    # never "other-wallet"
        self.assertEqual(strategy.trader.open_positions, [])
        self.assertTrue(any("smart money exit: 2 of the buyers sold" in line for line in lines))

    def test_candidate_prices_already_due_are_still_filled_in(self):
        from screener.token_record import CandidateLog
        os.makedirs(self.folder, exist_ok=True)
        log = CandidateLog(self.folder, "convergence")
        from datetime import datetime, timezone
        from screener.filters import Result
        first = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
        pair = {"dexId": "pumpswap", "pairAddress": "P1", "priceUsd": "0.5", "marketCap": 250000,
                "liquidity": {"usd": 40000}, "baseToken": {"address": EARLY_GOOD}}
        log.add(Result(EARLY_GOOD, "AAA", "Aaa", pair), None, {}, first, "PASS", "", True,
                "convergence=not bought")
        self.assertEqual(rows(log.path)[0]["time_1h_utc"], "")
        later = first + timedelta(minutes=70)
        strategy, plan, _ = self.go(self.STOP, now=later)
        self.assertIn(EARLY_GOOD, plan["reprice"])
        self.assertNotEqual(rows(log.path)[0]["time_1h_utc"], "")      # filled by DexScreener

    def test_the_comparison_and_health_say_stopped(self):
        self.assertTrue(compare.stopped(REAL, "convergence"))
        text = "\n".join(helius_lines(self.folder, "2026-10-24", True))
        self.assertIn("no data yet", text)
        os.makedirs(self.folder, exist_ok=True)
        self.go(self.FAST)
        text = "\n".join(helius_lines(self.folder, now_utc().date().isoformat(), True))
        self.assertIn("**stopped**", text)
        self.assertNotIn("| Status | active |", text)
        from datetime import datetime, timezone
        health = "\n".join(health_lines(self.tmp.name, REAL, datetime(2026, 10, 24,
                                                                     tzinfo=timezone.utc)))
        self.assertIn(f"{INFO} stopped (no new buys); 0 open position(s): finished", health)
        self.assertIn(f"{INFO} stopped (no new buys): no wallet checks", health)
        self.assertNotIn("convergence: wallets | ⚠️", health)


class SpyApi(DemoApi):
    """DemoApi that counts the lookups that exist to find buys."""

    def __init__(self, moves=None):
        super().__init__(moves)
        self.profiles = self.boosts = self.rugchecks = 0

    def latest_profiles(self):
        self.profiles += 1
        return super().latest_profiles()

    def latest_boosts(self):
        self.boosts += 1
        return super().latest_boosts()

    def rugcheck_report(self, address):
        self.rugchecks += 1
        return super().rugcheck_report(address)


class SpyRpc(DemoRpc):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.asked = []

    def signatures(self, wallet, limit, until=None):
        self.asked.append(wallet)
        return super().signatures(wallet, limit, until)


class ReportTests(unittest.TestCase):
    def test_comparison_columns_say_stopped(self):
        names = ["main", "main (1 min)", "main (1 min) A", "main (1 min) B", "main (1 min) C",
                 "early", "launch 5s", "momentum 30pct-2min", "momentum 100pct-5min",
                 "robinhood", "convergence", "news"]
        self.assertEqual([n for n in names if compare.stopped(REAL, n)],
                         ["main", "main (1 min)", "main (1 min) A", "main (1 min) B",
                          "main (1 min) C", "early", "launch 5s", "momentum 30pct-2min",
                          "momentum 100pct-5min", "robinhood", "convergence"])
        for name in ("news", "news (listings)", "news (listings) fast"):
            self.assertFalse(compare.stopped(REAL, name), name)

    def test_health_says_stopped_with_open_positions(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "early"))
            with open(os.path.join(d, "early", "positions.json"), "w") as fh:
                json.dump({"open_positions": [{"address": "X"}]}, fh)
            from datetime import datetime, timezone
            text = "\n".join(health_lines(d, REAL, datetime(2026, 10, 5, tzinfo=timezone.utc)))
        rows_ = {line.split(" | ")[0][2:]: line for line in text.splitlines()
                 if line.startswith("| ")}
        self.assertIn(f"{INFO} stopped (no new buys); 1 open position(s) finishing",
                      rows_["early: last successful run"])
        self.assertIn(f"{INFO} stopped (no new buys); 0 open position(s): finished",
                      rows_["main: last successful run"])
        # the real config runs the launch recorder inside the launch-bot service
        self.assertIn("service must stay on because it runs the launch recorder",
                      rows_["launch: server push"])
        self.assertNotIn("can be turned off", rows_["launch: server push"])


if __name__ == "__main__":
    unittest.main()
