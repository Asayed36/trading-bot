"""Checks for the "robinhood" paper strategy (screener/robinhood.py), with
made-up answers from GeckoTerminal, DexScreener, GoPlus and the RPC.
Run with:  python -m unittest -v
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config, run  # noqa: E402
from screener import robinhood as rh  # noqa: E402
from screener.api import ApiError, RateLimited  # noqa: E402
from screener.demo import DemoApi, DemoNewsHttp, demo_rpc_factory  # noqa: E402
from screener.github_issues import issue_body, issue_title  # noqa: E402

CFG = load_config()
C = CFG["robinhood"]
PT = C["paper_trading"]
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
HEAD, BLOCK_TIME = 1_000_000, 0.1

PONS = "0x" + "a" * 40           # a graduated Pons token
POOLS = "0x" + "b" * 40          # a Pools.trade token
PONS_POOL = "0x" + "1" * 64      # Uniswap v4 pool ids
POOLS_POOL = "0x" + "2" * 64
CURVE = "0x" + "c" * 40          # where the Pons token was minted (its curve)
MANAGER = C["excluded_holders"][0]   # Uniswap v4 PoolManager: holds the pool's tokens
DEV = "0x" + "d" * 40
WALLETS = ["0x" + str(i) * 40 for i in range(1, 6)]


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def block_at(when):
    return HEAD - int((NOW - when).total_seconds() / BLOCK_TIME)


def gecko(dex, token, pool, created, name):
    return {"attributes": {"address": pool, "name": f"{name} / WETH", "pool_created_at": created},
            "relationships": {"dex": {"data": {"id": dex}},
                              "base_token": {"data": {"id": f"robinhood_{token}"}}}}


def pair(token, pool, symbol, created_min_ago, liquidity=25_000, price=0.0001):
    return {"chainId": "robinhood", "dexId": "uniswap", "labels": ["v4"], "pairAddress": pool,
            "url": f"https://dexscreener.com/robinhood/{pool}",
            "baseToken": {"address": token, "symbol": symbol, "name": symbol.title()},
            "quoteToken": {"symbol": "WETH"}, "priceUsd": str(price),
            "liquidity": {"usd": liquidity}, "marketCap": 90_000,
            "txns": {"h1": {"buys": 40, "sells": 25}},
            "priceChange": {"m5": 2.5, "h1": 30, "h24": 30},
            "pairCreatedAt": int((NOW - timedelta(minutes=created_min_ago)).timestamp() * 1000)}


def transfer(frm, to, amount, block, tx="0xt"):
    return {"address": PONS, "topics": [rh.TRANSFER, rh.topic_address(frm), rh.topic_address(to)],
            "data": hex(amount), "blockNumber": hex(block), "logIndex": "0x0",
            "transactionHash": tx}


def pons_history(holdings=None):
    """1,000,000 minted to the curve 3 hours ago; at graduation (2 hours ago)
    the curve moved 800,000 to the pool. Wallets bought from the curve."""
    holdings = holdings or {DEV: 20_000, WALLETS[0]: 50_000, WALLETS[1]: 30_000,
                            WALLETS[2]: 25_000, WALLETS[3]: 15_000, WALLETS[4]: 10_000}
    start = block_at(NOW - timedelta(hours=3))
    logs = [transfer(rh.ZERO, CURVE, 1_000_000, start, tx="0xmint")]
    for i, (wallet, amount) in enumerate(holdings.items(), 1):
        logs.append(transfer(CURVE, wallet, amount, start + i * 100))
    logs.append(transfer(CURVE, MANAGER, 800_000, block_at(NOW - timedelta(hours=2))))
    return logs


class FakeHttp:
    """Answers like the four sources; records every call."""

    def __init__(self):
        self.calls = []
        self.goplus = {}            # token -> GoPlus result (default: all "0")
        self.pairs = {PONS: [pair(PONS, PONS_POOL, "FROG", 120)],
                      POOLS: [pair(POOLS, POOLS_POOL, "GLITCH", 60)]}
        self.search = []            # DexScreener search pairs
        self.logs = pons_history()
        self.gecko_status = {}      # url part -> exception to raise
        self.dex_down = False
        self.max_log_range = 100_000

    def get(self, source, url, params=None):
        self.calls.append((source, url, params))
        if source == "geckoterminal":
            for part, exc in self.gecko_status.items():
                if part in url:
                    raise exc
            if "pons-v2-dex" in url:
                return {"data": [gecko("pons-v2-dex", PONS, PONS_POOL, ago(hours=2), "FROG")]}
            if "uniswap-pools-trade" in url:
                return {"data": [gecko("uniswap-pools-trade", POOLS, POOLS_POOL, ago(hours=1),
                                       "GLITCH")]}
            return {"data": [  # newest pools: one too young, one on a plain Uniswap pool
                gecko("pons-v2-dex", "0x" + "e" * 40, "0x" + "3" * 64, ago(minutes=5), "NEW"),
                gecko("uniswap-v4-robinhood", "0x" + "f" * 40, "0x" + "4" * 64, ago(hours=1),
                      "OTHER")]}
        if source == "dexscreener":
            if self.dex_down:
                raise ApiError("api.dexscreener.com answered with error 503")
            if "/search" in url:
                return {"pairs": self.search}
            tokens = url.rsplit("/", 1)[1].split(",")
            return [p for t in tokens for p in self.pairs.get(t, [])]
        if source == "goplus":
            token = params["contract_addresses"]
            result = dict(self.goplus.get(token) or {
                "is_honeypot": "0", "is_mintable": "0", "hidden_owner": "0",
                "owner_change_balance": "0", "is_blacklisted": "0", "buy_tax": "0",
                "sell_tax": "0", "cannot_sell_all": "0", "is_open_source": "1",
                "owner_address": ""})
            return {"code": 1, "message": "OK", "result": {token: result}}
        raise AssertionError(url)

    def rpc(self, method, params):
        rh.rpc_request(method, params)               # refuses anything not allowed
        self.calls.append(("rpc", method, params))
        if method == "eth_blockNumber":
            return hex(HEAD)
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            return {"timestamp": hex(int(NOW.timestamp() - (HEAD - number) * BLOCK_TIME))}
        if method == "eth_getLogs":
            f = params[0]
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            if hi - lo + 1 > self.max_log_range:
                raise ApiError("Robinhood Chain RPC: block range too large")
            return [x for x in self.logs if x["address"] == f["address"]
                    and lo <= int(x["blockNumber"], 16) <= hi]
        if method == "eth_getTransactionByHash":
            return {"from": DEV if params[0] == "0xmint" else WALLETS[0]}
        raise AssertionError(method)


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.http = FakeHttp()

    def tearDown(self):
        self.tmp.cleanup()

    def strategy(self, cfg=CFG):
        return rh.RobinhoodStrategy(cfg, self.tmp.name, self.http)

    def run_once(self, now=NOW, cfg=CFG):
        s = self.strategy(cfg)
        lines = []
        bought = s.apply(s.fetch(now), lines.append)
        return s, bought, "\n".join(lines)

    def path(self, name):
        return os.path.join(self.tmp.name, "robinhood", name)

    def candidate(self, symbol):
        return {r["symbol"]: r for r in rows(self.path("candidates.csv"))}[symbol]


class FlowTests(Base):
    def test_buys_a_pons_and_a_pools_trade_token_with_every_value_saved(self):
        s, bought, text = self.run_once()
        self.assertEqual(sorted(p["symbol"] for p in bought), ["FROG", "GLITCH"])
        entries = {r["symbol"]: r for r in rows(self.path("entries.csv"))}
        frog, glitch = entries["FROG"], entries["GLITCH"]
        self.assertEqual((frog["launchpad"], frog["pool_address"], frog["pool_age_minutes"]),
                         ("Pons", PONS_POOL, "120"))
        self.assertEqual((frog["goplus_is_honeypot"], frog["goplus_is_mintable"],
                          frog["copycat_of"]), ("0", "0", ""))
        # Holders rebuilt from the RPC: pool, curve and burn left out; the
        # creator is the sender of the mint transaction.
        self.assertEqual((frog["creator"], frog["creator_pct"], frog["top10_pct"],
                          frog["holders"], frog["equal_group_size"], frog["holders_complete"]),
                         (DEV, "2", "15", "6", "0", "yes"))
        self.assertEqual((frog["pool_fee_pct"], frog["slippage_pct"], frog["gas_usd"]),
                         ("1", "2", "0.05"))
        # Pools.trade: no holder checks, so those values are blank (unknown).
        self.assertEqual((glitch["launchpad"], glitch["creator"], glitch["top10_pct"],
                          glitch["holders_complete"]), ("Pools.trade", "", "", ""))
        self.assertEqual(glitch["pool_fee_pct"], "0.25")
        # Only allowed launchpads, only pools 30 min - 6 h old.
        self.assertEqual({r["symbol"] for r in rows(self.path("candidates.csv"))},
                         {"FROG", "GLITCH"})
        self.assertIn("[PASS] FROG (Pons)", text)
        # Costs: fee + slippage leave fewer tokens; gas is added to the cost.
        pos = s.trader.position(PONS)
        self.assertAlmostEqual(pos["tokens"], 10 * 0.99 * 0.98 / 0.0001)
        self.assertAlmostEqual(pos["cost_usd"], 10.05)
        self.assertEqual(pos["issue_details"]["top_holders"][0], {"wallet": WALLETS[0],
                                                                  "pct": 5.0})
        self.assertNotIn("top_holders", s.trader.position(POOLS)["issue_details"])

    def test_gecko_calls_are_limited_and_the_watchlist_carries_over(self):
        s, _, _ = self.run_once()
        gecko = [c for c in self.http.calls if c[0] == "geckoterminal"]
        self.assertEqual(len(gecko), C["gecko_calls_per_run"])
        self.assertIn(PONS_POOL, s.trader.state["watch"])
        # Next run: GeckoTerminal refuses everything; the watchlist is still checked.
        self.http.gecko_status = {"geckoterminal": RateLimited("429")}
        self.http.calls.clear()
        later = NOW + timedelta(minutes=C["recheck_minutes"] + 1)
        s2 = self.strategy()
        plan = s2.fetch(later)
        self.assertEqual(len([c for c in self.http.calls if c[0] == "geckoterminal"]), 1)
        self.assertTrue(any("rate-limiting" in n for n in plan["notes"]))
        self.assertIn(PONS_POOL, plan["watch"])
        s2.apply(plan, lambda *_: None)
        src = s2.trader.state["sources"]["geckoterminal"]
        self.assertEqual((src["ok"], src["rate_limited"]), (False, 1))

    def test_a_pool_is_rechecked_only_after_recheck_minutes(self):
        self.http.goplus[PONS] = {"is_honeypot": "1"}
        self.run_once()
        _, _, text = self.run_once(NOW + timedelta(minutes=10))
        self.assertNotIn("FROG", text)
        _, _, text = self.run_once(NOW + timedelta(minutes=C["recheck_minutes"] + 1))
        self.assertIn("[FAIL] FROG", text)
        # candidates.csv only gets a new row when the result changes.
        self.assertEqual(sum(r["symbol"] == "FROG" for r in rows(self.path("candidates.csv"))), 1)

    def test_dexscreener_down_skips_the_strategy_before_any_change(self):
        s, _, _ = self.run_once()
        self.http.dex_down = True
        with self.assertRaises(ApiError):
            self.strategy().fetch(NOW + timedelta(minutes=20))
        self.assertEqual(len(rows(self.path("journal.csv"))), 2)


class CheckTests(Base):
    def test_goplus_flags_and_unknowns(self):
        self.http.goplus[PONS] = {"is_honeypot": "1", "is_mintable": "0", "hidden_owner": "0",
                                  "owner_change_balance": "0", "is_blacklisted": "0"}
        self.http.goplus[POOLS] = {"is_honeypot": "0"}       # the rest unknown
        _, bought, _ = self.run_once()
        self.assertEqual(bought, [])
        frog, glitch = self.candidate("FROG"), self.candidate("GLITCH")
        self.assertIn("Not a honeypot: GoPlus is_honeypot = 1", frog["failed_checks"])
        self.assertEqual(frog["creator"], "")                # holder check not reached
        self.assertIn("Not mintable: unknown", glitch["failed_checks"])
        self.assertEqual((glitch["goplus_is_honeypot"], glitch["goplus_is_mintable"]), ("0", ""))

    def test_creator_share(self):
        self.http.logs = pons_history({DEV: 60_000, WALLETS[0]: 10_000})
        self.run_once()
        self.assertIn("Creator share: 6.00%", self.candidate("FROG")["failed_checks"])

    def test_top_10_holders(self):
        self.http.logs = pons_history({DEV: 10_000, WALLETS[0]: 140_000, WALLETS[1]: 90_000,
                                       WALLETS[2]: 70_000})
        self.run_once()
        self.assertIn("Top 10 holders: 31.0%", self.candidate("FROG")["failed_checks"])
        self.assertEqual(self.candidate("FROG")["top10_pct"], "31")

    def test_equal_balance_cluster(self):
        self.http.logs = pons_history({DEV: 5_000, WALLETS[0]: 20_000, WALLETS[1]: 20_050,
                                       WALLETS[2]: 19_980, WALLETS[3]: 3_000})
        self.run_once()
        frog = self.candidate("FROG")
        self.assertIn("No equal-balance cluster: 3 wallets", frog["failed_checks"])
        self.assertEqual(frog["equal_group_size"], "3")

    def test_holders_unknown_when_the_mint_isnt_found(self):
        self.http.logs = [x for x in pons_history() if x["transactionHash"] != "0xmint"]
        self.run_once()
        frog = self.candidate("FROG")
        self.assertIn("Holders: unknown", frog["failed_checks"])
        self.assertEqual(frog["holders_complete"], "no")

    def test_log_ranges_are_split_when_the_rpc_refuses_them(self):
        self.http.max_log_range = 30_000
        _, bought, _ = self.run_once()
        self.assertIn(PONS, [p["address"] for p in bought])
        sizes = {int(c[2][0]["toBlock"], 16) - int(c[2][0]["fromBlock"], 16) + 1
                 for c in self.http.calls if c[0] == "rpc" and c[1] == "eth_getLogs"}
        self.assertLessEqual(min(sizes), 30_000)

    def test_copycat_from_dexscreener_search(self):
        older = pair("0x" + "9" * 40, "0x" + "5" * 64, "FROG", 60 * 24)
        self.http.search = [older]
        self.run_once()
        frog = self.candidate("FROG")
        self.assertIn("Not a copycat", frog["failed_checks"])
        self.assertEqual(frog["copycat_of"], "0x" + "9" * 40)
        self.assertEqual(frog["goplus_is_honeypot"], "")      # later checks not reached

    def test_low_liquidity_fails_before_goplus(self):
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 120, liquidity=2_000)]
        self.run_once()
        self.assertIn("Liquidity: $2,000", self.candidate("FROG")["failed_checks"])
        goplus = [c[2]["contract_addresses"] for c in self.http.calls if c[0] == "goplus"]
        self.assertNotIn(PONS, goplus)

    def test_pool_age_comes_from_dexscreener(self):
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 7 * 60)]   # GT said 2h
        self.run_once()
        self.assertIn("Pool age: 420 min", self.candidate("FROG")["failed_checks"])


class ExitTests(Base):
    def test_main_exits_after_costs(self):
        s, _, _ = self.run_once()
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 150, price=0.00016)]
        self.http.pairs[POOLS] = [pair(POOLS, POOLS_POOL, "GLITCH", 90, price=0.00006)]
        later = NOW + timedelta(hours=1)
        s2 = self.strategy()
        s2.apply(s2.fetch(later), lambda *_: None)
        sells = [r for r in rows(self.path("journal.csv")) if r["action"] == "SELL"]
        reasons = {r["symbol"]: r["reason"] for r in sells}
        self.assertIn("take profit: up 60%", reasons["FROG"])      # half sold at +50%+
        self.assertIn("stop loss: down 40%", reasons["GLITCH"])
        frog = [r for r in sells if r["symbol"] == "FROG"][0]
        tokens = 10 * 0.99 * 0.98 / 0.0001
        proceeds = tokens * 0.5 * 0.00016 * 0.99 * 0.98 - 0.05
        self.assertAlmostEqual(float(frog["pnl_usd"]), round(proceeds - 10.05 * 0.5, 2), places=2)
        self.assertEqual(len(s2.trader.open_positions), 1)        # FROG's other half rides

    def test_exit_rows_in_the_issue_are_mains(self):
        s, _, _ = self.run_once()
        pos = s.trader.position(PONS)
        body = issue_body(pos, PT, "note", "robinhood")
        self.assertEqual(issue_title(pos, "robinhood"), "PASSED (robinhood): FROG")
        for text in ("Robinhood Chain (4663)", "Contract address (Robinhood Chain)", "Pons",
                     "+50%", "-30%", "40% below the highest price", "48h",
                     "Top 10 holders", f"`{WALLETS[0]}`"):
            self.assertIn(text, body)


class SafetyTests(unittest.TestCase):
    def test_only_read_only_rpc_calls(self):
        self.assertEqual(rh.RPC_METHODS, {"eth_blockNumber", "eth_getBlockByNumber",
                                          "eth_getLogs", "eth_getTransactionByHash"})
        for method in ("eth_sendRawTransaction", "eth_sendTransaction", "eth_sign",
                       "personal_sign", "eth_signTypedData_v4"):
            with self.assertRaises(ValueError):
                rh.rpc_request(method, [])

    def test_equal_groups(self):
        self.assertEqual([len(g) for g in rh.equal_groups([100, 100.2, 100.4, 5, 5, 70], 0.005)],
                         [3, 2])


class RunTests(Base):
    def test_run_records_robinhood_health(self):
        import json
        cfg = dict(CFG, robinhood=dict(C, min_liquidity_usd=10**12))  # nothing to buy
        run(DemoApi(), cfg, self.tmp.name, out=lambda *a: None, rpc_factory=demo_rpc_factory(),
            news_http=DemoNewsHttp(), robinhood_http=self.http)
        with open(os.path.join(self.tmp.name, "health.json")) as fh:
            self.assertIn("last_ok", json.load(fh)["strategies"]["robinhood"])


if __name__ == "__main__":
    unittest.main()
