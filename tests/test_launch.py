"""Checks for the "launch" paper strategy (screener/launch.py) and its runner
(launch_bot.py), using made-up feed messages and a made-up clock.
Run with:  python -m unittest -v
"""

import csv
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import HERE, load_config  # noqa: E402
from screener.launch import LaunchEngine  # noqa: E402

CFG = load_config()
L = CFG["launch"]
T0 = 1_790_000_000.0          # a fixed moment, in seconds
SOL = 100.0                   # $100 per SOL keeps the arithmetic simple
KEPT = (1 - (L["paper_trading"]["bot_fee_pct"] + L["paper_trading"]["platform_fee_pct"]) / 100) \
    * (1 - 0.05)              # what fees and 5% extra slippage leave on each trade


def cfg_with(**launch):
    return dict(CFG, launch=dict(L, **launch))


def create(mint, name=None, symbol=None, creator="DEV", initial=0.0, v_sol=30.0,
           v_tok=1_000_000_000.0):
    return {"txType": "create", "mint": mint, "name": name or f"Token {mint}",
            "symbol": symbol or mint.upper(), "traderPublicKey": creator, "initialBuy": initial,
            "vSolInBondingCurve": v_sol, "vTokensInBondingCurve": v_tok, "marketCapSol": 30}


def trade(mint, kind="buy", who="W1", v_sol=30.0, v_tok=1_000_000_000.0):
    return {"txType": kind, "mint": mint, "traderPublicKey": who,
            "vSolInBondingCurve": v_sol, "vTokensInBondingCurve": v_tok}


def price_msg(mint, usd_price, kind="buy", who="W1"):
    """A trade that puts the curve price at `usd_price` per token."""
    return trade(mint, kind, who, v_sol=usd_price / SOL * 1e9, v_tok=1e9)


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = self.make()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, cfg=CFG, trade_feed=True):
        # Most checks feed made-up trades, as if the trade feed were on; the
        # bot itself runs without it (NoTradeFeedTests).
        engine = LaunchEngine(cfg, self.tmp.name, clock=lambda: T0, trade_feed=trade_feed)
        engine.set_sol_price(SOL)
        return engine

    def at(self, seconds, msg=None, engine=None):
        engine = engine or self.engine
        if msg is not None:
            return engine.on_message(msg, T0 + seconds)
        return engine.tick(T0 + seconds)

    def journal(self, speed):
        return rows(os.path.join(self.tmp.name, "launch", speed, "journal.csv"))

    def launches(self):
        return rows(os.path.join(self.tmp.name, "launch", "launches.csv"))

    def run_through(self, mint="m1", seconds=91, step=0.5, start=0.0):
        t = start
        while t <= seconds:
            self.at(t)
            t += step


class FlowTests(Base):
    def test_three_speeds_buy_the_same_launch_with_separate_journals(self):
        sub, _ = self.at(0, create("m1"))
        self.assertEqual(sub, ["m1"])                      # follow its trades
        self.at(2, price_msg("m1", 3e-6))                  # price before the 5s buy
        self.run_through(seconds=10)
        self.at(20, price_msg("m1", 4e-6))                 # before the 30s buy
        self.run_through(seconds=40, start=10.5)
        self.at(60, price_msg("m1", 5e-6))                 # before the 90s buy
        self.run_through(seconds=91, start=40.5)
        prices = {s: [r for r in self.journal(s) if r["action"] == "BUY"][0]["price_usd"]
                  for s in ("5s", "30s", "90s")}
        self.assertEqual(prices, {"5s": "3e-06", "30s": "4e-06", "90s": "5e-06"})
        self.assertEqual(self.launches()[0]["decision"], "selected")
        (entry,) = rows(os.path.join(self.tmp.name, "launch", "5s", "entries.csv"))
        self.assertEqual(entry["seconds_after_creation"], "5.0")
        # price change since creation (3e-06 at creation), saved as the 5m and 1h change
        change = {s: rows(os.path.join(self.tmp.name, "launch", s, "entries.csv"))[0]
                  for s in ("5s", "30s", "90s")}
        self.assertEqual({s: (r["price_change_5m_pct"], r["price_change_1h_pct"])
                          for s, r in change.items()},
                         {"5s": ("0", "0"), "30s": ("33.33", "33.33"), "90s": ("66.67", "66.67")})

    def test_costs_on_a_flat_round_trip(self):
        self.at(0, create("m1"))
        self.at(2, price_msg("m1", 3e-6))
        self.run_through(seconds=6)
        pos = self.engine.traders["5s"].open_positions[0]
        self.assertAlmostEqual(pos["cost_usd"], 5 + 0.003 * SOL)          # $5 + priority fee
        self.assertAlmostEqual(pos["tokens"] * 3e-6, 5 * KEPT)
        # nothing happens for 30 minutes: the time stop sells at the same price
        self.at(5 + 30 * 60 + 1)
        (sell,) = [r for r in self.journal("5s") if r["action"] == "SELL"]
        self.assertIn("time stop", sell["reason"])
        expected = 5 * KEPT * KEPT - 0.003 * SOL - (5 + 0.003 * SOL)
        self.assertAlmostEqual(float(sell["pnl_usd"]), round(expected, 2), places=2)
        self.assertLess(expected, -1.2)        # costs alone lose about a quarter of $5

    def test_take_profit_then_stop(self):
        self.at(0, create("m1"))
        self.at(2, price_msg("m1", 1e-6))
        self.run_through(seconds=6)
        self.at(10, price_msg("m1", 2.1e-6))   # 2.1x: sell half
        self.at(12, price_msg("m1", 0.6e-6))   # -40% from entry: sell the rest
        reasons = [r["reason"] for r in self.journal("5s") if r["action"] == "SELL"]
        self.assertEqual(len(reasons), 2)
        self.assertIn("take profit", reasons[0])
        self.assertIn("stop loss", reasons[1])
        self.assertFalse(self.engine.traders["5s"].open_positions)

    def test_finished_launches_are_dropped(self):
        self.at(0, create("m1"))
        self.at(2, price_msg("m1", 1e-6))
        self.run_through(seconds=91)
        self.at(95, price_msg("m1", 0.1e-6))   # everyone stopped out
        _, drop = self.at(96)
        self.assertEqual(drop, ["m1"])
        self.assertNotIn("m1", self.engine.watch)

    def test_feed_noise_is_ignored(self):
        self.assertEqual(self.at(0, {"message": "Successfully subscribed"}), ([], []))
        self.assertEqual(self.at(0, "not json"), ([], []))
        self.assertEqual(self.at(0, trade("unknown")), ([], []))


class FlagTests(Base):
    def test_flags_are_recorded(self):
        self.at(0, create("dev", initial=30_000_000))       # creator bought 3%
        self.at(0, create("clean"))
        self.at(0.5, trade("clean", who="EARLY"))           # bought in the first block
        self.at(0.6, create("late"))
        self.at(2.0, trade("late", who="LATER"))            # after the first block
        self.at(3)
        got = {r["mint"]: r for r in self.launches()}
        self.assertEqual((got["dev"]["flagged"], got["dev"]["dev_buy_pct"]), ("yes", "3.00"))
        self.assertEqual((got["clean"]["flagged"], got["clean"]["first_block_buyers"]), ("yes", "1"))
        self.assertEqual(got["late"]["flagged"], "no")
        self.assertTrue(all(r["decision"] == "selected" for r in got.values()))  # skip_flagged off

    def test_skip_flagged_frees_the_hourly_slot(self):
        self.engine = self.make(cfg_with(skip_flagged=True, max_new_trades_per_hour=1))
        self.at(0, create("dev", initial=30_000_000))
        self.at(2)
        self.assertEqual(self.launches()[0]["decision"], "skipped")
        sub, _ = self.at(3, create("next"))                 # the slot is free again
        self.assertEqual(sub, ["next"])


class SkipTests(Base):
    def test_copycat_names(self):
        self.at(0, create("a", name="Moon Cat", symbol="MCAT"))
        self.assertEqual(self.at(10, create("b", name="moon cat", symbol="OTHER")), ([], []))
        self.assertEqual(self.at(11, create("c", name="x", symbol="mcat")), ([], []))
        later = 8 * 86400                                   # outside the 7-day window
        self.engine.prune(T0 + later)
        self.assertEqual(self.at(later, create("d", name="Moon Cat")), (["d"], []))

    def test_creator_with_a_dead_token(self):
        self.at(0, create("first", creator="SERIAL"))
        sub, _ = self.at(30 * 60, create("second", creator="SERIAL"))
        self.assertEqual(sub, ["second"])                   # first isn't an hour old yet
        sub, _ = self.at(61 * 60, create("third", creator="SERIAL"))
        self.assertEqual(sub, [])                           # first is dead now
        self.at(0, create("grad", creator="GOOD"))
        self.at(10 * 60, {"txType": "migrate", "mint": "grad"})
        sub, _ = self.at(2 * 3600, create("again", creator="GOOD"))
        self.assertEqual(sub, ["again"])                    # graduated: not dead

    def test_hourly_cap(self):
        engine = self.make(cfg_with(max_new_trades_per_hour=10))
        for i in range(10):
            self.assertEqual(self.at(i, create(f"m{i}", creator=f"D{i}"), engine)[0], [f"m{i}"])
        self.assertEqual(self.at(20, create("m10", creator="D10"), engine), ([], []))
        self.assertEqual(self.at(3601, create("m11", creator="D11"), engine)[0], ["m11"])

    def test_unpriced_launch_is_skipped_without_using_the_cap(self):
        engine = self.make(cfg_with(max_new_trades_per_hour=1))
        unpriced = create("x1", creator="DX")
        del unpriced["vSolInBondingCurve"], unpriced["vTokensInBondingCurve"]
        self.assertEqual(self.at(0, unpriced, engine), ([], []))
        self.assertEqual(self.at(1, create("m1", creator="D1"), engine)[0], ["m1"])
        hour = next(iter(engine.stats.values()))
        self.assertEqual(hour["skipped: no price in the feed"], 1)

    def test_restarts_are_counted(self):
        self.engine.save()                   # started once (setUp), stopped
        engine = self.make()                 # started again
        engine.save()
        self.assertEqual(sum(h.get("bot started", 0) for h in engine.stats.values()), 2)

    def test_open_cap_per_speed(self):
        engine = self.make(cfg_with(max_open_per_speed=2, max_new_trades_per_hour=10))
        for i in range(3):
            self.at(i, create(f"m{i}"), engine)
            self.at(i + 0.9, price_msg(f"m{i}", 1e-6), engine)
        t = 0.0
        while t < 10:
            self.at(t, engine=engine)
            t += 0.5
        self.assertEqual(len(engine.traders["5s"].open_positions), 2)

    def test_no_sol_price_no_trades(self):
        engine = LaunchEngine(CFG, self.tmp.name)
        self.assertEqual(engine.on_message(create("m1"), T0), ([], []))


class PriceSourceTests(Base):
    def test_graduated_tokens_priced_from_dexscreener(self):
        self.at(0, create("m1"))
        self.at(2, price_msg("m1", 1e-6))
        self.run_through(seconds=6)
        self.at(7, {"txType": "migrate", "mint": "m1", "pool": "pump-amm"})
        self.assertEqual(self.engine.needs_external(T0 + 8), ["m1"])
        self.engine.set_external_prices({"m1": 0.5e-6}, T0 + 9)   # -50% on PumpSwap
        self.assertIn("stop loss", self.journal("5s")[-1]["reason"])

    def test_quiet_token_uses_dexscreener(self):
        self.at(0, create("m1"))
        self.at(2, price_msg("m1", 1e-6))
        self.run_through(seconds=6)
        self.assertEqual(self.engine.needs_external(T0 + 30), [])
        self.assertEqual(self.engine.needs_external(T0 + 2 + L["stale_price_seconds"] + 1),
                         ["m1"])

    def test_restart_keeps_positions_and_resubscribes(self):
        self.at(0, create("m1"))
        self.at(2, price_msg("m1", 1e-6))
        self.run_through(seconds=6)
        self.engine.save()
        again = self.make()
        self.assertEqual(len(again.traders["5s"].open_positions), 1)
        self.assertEqual(again.subscriptions(), ["m1"])
        self.assertEqual(again.needs_external(T0 + 7), ["m1"])     # no feed price yet
        again.set_external_prices({"m1": 1e-6}, T0 + 8)
        again.tick(T0 + 5 + 30 * 60 + 1)                            # time stop still fires
        self.assertFalse(again.traders["5s"].open_positions)


class NoTradeFeedTests(Base):
    """How the bot runs: new tokens and migrations only, no trades."""

    def setUp(self):
        super().setUp()
        self.engine = self.make(trade_feed=False)

    def test_nothing_subscribed_and_unknowns_saved_blank(self):
        self.assertEqual(self.at(0, create("m1", initial=20_000_000)), ([], []))
        self.assertEqual(self.engine.subscriptions(), [])
        self.run_through(seconds=10)
        (launch,) = self.launches()
        self.assertEqual((launch["dev_buy_pct"], launch["first_block_buyers"], launch["flagged"]),
                         ("2.00", "", "yes"))           # the creator's buy is still known
        (entry,) = rows(os.path.join(self.tmp.name, "launch", "5s", "entries.csv"))
        self.assertEqual({k: entry[k] for k in ("buys_so_far", "sells_so_far",
                                                "first_block_buyers", "price_change_5m_pct",
                                                "price_change_1h_pct")},
                         dict.fromkeys(("buys_so_far", "sells_so_far", "first_block_buyers",
                                        "price_change_5m_pct", "price_change_1h_pct"), ""))
        self.assertEqual(entry["price_usd"], "3e-06")   # the curve price at creation
        pos = self.engine.traders["5s"].open_positions[0]
        self.assertIsNone(pos["launch"]["buys"])

    def test_same_trading_rules_with_dexscreener_prices(self):
        self.at(0, create("m1"))
        self.run_through(seconds=91)
        buys = {s: [r for r in self.journal(s) if r["action"] == "BUY"]
                for s in ("5s", "30s", "90s")}
        self.assertEqual({s: len(b) for s, b in buys.items()}, {"5s": 1, "30s": 1, "90s": 1})
        stale = L["stale_price_seconds"]
        self.assertEqual(self.engine.needs_external(T0 + stale + 1), ["m1"])
        self.engine.set_external_prices({"m1": 6.3e-6}, T0 + stale + 2)      # 2.1x
        self.assertIn("take profit", self.journal("5s")[-1]["reason"])
        self.engine.set_external_prices({"m1": 2e-6}, T0 + stale + 30)       # -33%
        self.assertIn("stop loss", self.journal("5s")[-1]["reason"])
        _, drop = self.at(stale + 31)
        self.assertEqual(drop, [])                      # nothing to unsubscribe


class JupiterTests(Base):
    """Jupiter's organic score in the launch entries (logging only)."""

    def test_due_while_selected_then_saved_with_its_age(self):
        self.at(0, create("m1"))
        self.assertEqual(self.engine.jupiter_due(T0 + 0.5), [])          # still evaluating
        self.at(1.5)                                                      # selected
        self.assertEqual(self.engine.jupiter_due(T0 + 1.5), ["m1"])
        values = {"jupiter_organic_score": 12.0, "jupiter_organic_label": "low",
                  "jupiter_organic_volume_1h_pct": 3.0, "jupiter_organic_buyers_1h_pct": 1.0}
        self.engine.set_jupiter("m1", values, T0 + 2)
        self.assertEqual(self.engine.jupiter_due(T0 + 5), [])            # fresh enough
        self.run_through(seconds=91, start=2)
        e5 = rows(os.path.join(self.tmp.name, "launch", "5s", "entries.csv"))[0]
        self.assertEqual((e5["jupiter_organic_label"],
                          e5["jupiter_checked_seconds_after_creation"]), ("low", "2.0"))
        self.assertEqual(self.engine.jupiter_due(T0 + 92), [])           # every speed bought

    def test_no_reading_means_blank(self):
        self.at(0, create("m1"))
        self.run_through(seconds=10)
        (e,) = rows(os.path.join(self.tmp.name, "launch", "5s", "entries.csv"))
        self.assertEqual({k: e[k] for k in ("jupiter_organic_score", "jupiter_organic_label",
                                            "jupiter_checked_seconds_after_creation")},
                         dict.fromkeys(("jupiter_organic_score", "jupiter_organic_label",
                                        "jupiter_checked_seconds_after_creation"), ""))


class PaperOnlyTests(unittest.TestCase):
    def test_runner_only_sends_read_only_requests(self):
        import launch_bot
        self.assertEqual(launch_bot.ALLOWED_METHODS, {"subscribeNewToken", "subscribeMigration"})
        for method in ("trade", "sell", "buy", "subscribeAccountTrade", "subscribeTokenTrade"):
            with self.assertRaises(ValueError):
                launch_bot.request(method)

    def test_no_wallet_or_trading_code_anywhere(self):
        forbidden = re.compile(r"api/trade|trade-local|private.?key|secret.?key|keypair|"
                               r"solders|solana\.rpc|sign_transaction|sendTransaction|mnemonic",
                               re.IGNORECASE)
        for folder, _, files in os.walk(HERE):
            if any(part in folder for part in (".git", "__pycache__", "tests", ".venv")):
                continue
            for name in files:
                if name.endswith((".py", ".sh", ".service", ".timer", ".txt", ".toml")):
                    with open(os.path.join(folder, name)) as fh:
                        text = fh.read()
                    hits = [m for m in forbidden.findall(text)]
                    allowed = all("never" in line.lower() or "no " in line.lower()
                                  for line in text.splitlines() if forbidden.search(line))
                    self.assertTrue(allowed, f"{name}: {hits}")


if __name__ == "__main__":
    unittest.main()


class RunnerTests(unittest.TestCase):
    """The real runner against a fake PumpPortal on this computer."""

    def test_end_to_end_with_a_fake_feed(self):
        import asyncio
        import json
        from unittest import mock

        import websockets

        import launch_bot

        received = []

        async def fake_pumpportal(ws):
            async for raw in ws:
                msg = json.loads(raw)
                received.append(msg)
                if msg["method"] == "subscribeNewToken":
                    await ws.send(json.dumps({"message": "Successfully subscribed to token "
                                                         "creation events."}))
                    await ws.send(json.dumps(create("live1")))
                    await ws.send(json.dumps({"errors": "made-up reply"}))

        speeds = [dict(s, delay_seconds=d) for s, d in zip(L["speeds"], (0.6, 1.2, 1.8))]

        async def scenario(folder):
            async with websockets.serve(fake_pumpportal, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                cfg = cfg_with(ws_url=f"ws://127.0.0.1:{port}", first_block_seconds=0.3,
                               speeds=speeds)
                fake_jupiter = mock.Mock(return_value={
                    "jupiter_organic_score": 42.5, "jupiter_organic_label": "medium",
                    "jupiter_organic_volume_1h_pct": None, "jupiter_organic_buyers_1h_pct": 7.5})
                with mock.patch.object(launch_bot, "sol_price", return_value=SOL), \
                        mock.patch.object(launch_bot, "token_prices", return_value={}), \
                        mock.patch.object(launch_bot, "JupiterOrganic",
                                          return_value=fake_jupiter), \
                        mock.patch.object(launch_bot.Runner, "ORGANIC_POLL_SECONDS", 0.1):
                    runner = launch_bot.Runner(cfg, folder)
                    task = asyncio.create_task(runner.main())
                    await asyncio.sleep(3.5)
                    runner.stop.set()
                    await asyncio.wait_for(task, 10)
                    return runner

        with tempfile.TemporaryDirectory() as d, self.assertLogs("launch_bot", "INFO") as logs:
            runner = asyncio.run(scenario(d))
            buys = {s: [r for r in rows(os.path.join(d, "launch", s, "journal.csv"))
                        if r["action"] == "BUY"] for s in ("5s", "30s", "90s")}
            self.assertTrue(os.path.exists(os.path.join(d, "launch", "state.json")))
            entries = {s: rows(os.path.join(d, "launch", s, "entries.csv"))[0]
                       for s in ("5s", "30s", "90s")}
        methods = [m["method"] for m in received]
        self.assertEqual(methods[:2], ["subscribeNewToken", "subscribeMigration"])
        self.assertEqual(len(methods), 2)                   # no trade subscriptions
        self.assertTrue(any("PumpPortal says: {'errors': 'made-up reply'}" in line
                            for line in logs.output))
        self.assertEqual(runner.kinds, {"reply": 2, "create": 1})
        self.assertIn("feed messages by type: create 1, reply 2",
                      launch_bot.test_summary(runner.engine, runner.kinds))
        self.assertEqual({s: len(b) for s, b in buys.items()}, {"5s": 1, "30s": 1, "90s": 1})
        self.assertEqual(buys["5s"][0]["price_usd"], "3e-06")  # the curve price at creation
        # Jupiter's organic score, looked up in the background (logging only).
        for e in entries.values():
            self.assertEqual((e["jupiter_organic_score"], e["jupiter_organic_label"],
                              e["jupiter_organic_volume_1h_pct"],
                              e["jupiter_organic_buyers_1h_pct"]), ("42.5", "medium", "", "7.5"))
            self.assertLess(float(e["jupiter_checked_seconds_after_creation"]),
                            float(e["seconds_after_creation"]) + 0.01)
        runner.jupiter.assert_called_with("live1")
