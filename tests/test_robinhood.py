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
BUNDLE = ["0x" + f"{i:040x}" for i in range(100, 106)]     # bundled-buy wallets
RIVAL, RIVAL2 = "0x" + "9" * 40, "0x" + "8" * 40            # other launchpad tokens


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def block_at(when):
    return HEAD - int((NOW - when).total_seconds() / BLOCK_TIME)


def gecko(dex, token, pool, created, name, liquidity=20_000, market_cap=60_000):
    return {"attributes": {"address": pool, "name": f"{name} / WETH", "pool_created_at": created,
                           "reserve_in_usd": str(liquidity), "market_cap_usd": str(market_cap)},
            "relationships": {"dex": {"data": {"id": dex}},
                              "base_token": {"data": {"id": f"robinhood_{token}"}}}}


def gecko_token(token, name):
    return {"id": f"robinhood_{token}", "type": "token", "attributes": {"name": name}}


def graduation(token, block):
    return {"address": C["pons_graduation_contract"],
            "topics": [C["pons_graduation_topic"], rh.topic_address(token), "0x" + "0" * 64],
            "data": "0x1", "blockNumber": hex(block), "logIndex": "0x0", "transactionHash": "0xg"}


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
        self.search_down = False
        self.more = {}              # GeckoTerminal dex -> extra pools in its list
        self.included = []          # GeckoTerminal "included" base tokens
        self.rate_limits = 0        # this many eth_getLogs calls answer 429 first
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
                return {"data": [gecko("pons-v2-dex", PONS, PONS_POOL, ago(hours=2), "FROG")]
                        + self.more.get("pons-v2-dex", []), "included": self.included}
            if "uniswap-pools-trade" in url:
                return {"data": [gecko("uniswap-pools-trade", POOLS, POOLS_POOL, ago(hours=1),
                                       "GLITCH")] + self.more.get("uniswap-pools-trade", []),
                        "included": self.included}
            return {"data": [  # newest pools: one too young, one on a plain Uniswap pool
                gecko("pons-v2-dex", "0x" + "e" * 40, "0x" + "3" * 64, ago(minutes=5), "NEW"),
                gecko("uniswap-v4-robinhood", "0x" + "f" * 40, "0x" + "4" * 64, ago(hours=1),
                      "OTHER")]}
        if source == "dexscreener":
            if self.dex_down:
                raise ApiError("api.dexscreener.com answered with error 503")
            if "/search" in url:
                if self.search_down:
                    raise ApiError("api.dexscreener.com answered with error 503")
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
            if self.rate_limits:
                self.rate_limits -= 1
                raise RateLimited("Robinhood Chain RPC said 'too many requests' (HTTP 429)")
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            if hi - lo + 1 > self.max_log_range:
                raise ApiError("Robinhood Chain RPC: block range too large")
            return [x for x in self.logs if x["address"] == f["address"]
                    and x["topics"][0] in f["topics"][0:1]
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
        self.sleeps = []
        return rh.RobinhoodStrategy(cfg, self.tmp.name, self.http, sleep=self.sleeps.append)

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

    def cluster(self, amounts):
        self.http.logs = pons_history(dict({DEV: 5_000}, **dict(zip(BUNDLE, amounts))))
        _, bought, _ = self.run_once()
        return self.candidate("FROG"), PONS in [p["address"] for p in bought]

    def test_equal_balance_cluster_of_5_holding_3_pct(self):
        frog, bought = self.cluster([7_000, 7_010, 6_990, 7_020, 7_000])    # 3.5% together
        self.assertFalse(bought)
        self.assertIn("No equal-balance cluster: 5 wallets hold the same amount (3.5% together;"
                      " fails at 5+ wallets holding 3%+ together)", frog["failed_checks"])
        self.assertEqual((frog["equal_group_size"], frog["equal_group_pct"]), ("5", "3.502"))

    def test_small_or_light_clusters_pass(self):
        frog, bought = self.cluster([20_000, 20_050, 19_980, 20_010])       # 4 wallets, 8%
        self.assertTrue(bought)
        self.assertEqual(frog["equal_group_size"], "4")
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        frog, bought = self.cluster([3_000, 3_001, 2_999, 3_002, 3_000, 3_001])   # 6, 1.8%
        self.assertTrue(bought)
        self.assertEqual((frog["equal_group_size"], frog["equal_group_pct"]), ("6", "1.8"))

    def test_the_heaviest_big_enough_cluster_counts(self):
        # Six wallets at 0.2% each (1.2%) and five at 0.7% each (3.5%).
        self.http.logs = pons_history(dict(
            {DEV: 5_000}, **{f"0x{i:040x}": 2_000 for i in range(200, 206)},
            **{f"0x{i:040x}": 7_000 for i in range(300, 305)}))
        self.run_once()
        frog = self.candidate("FROG")
        self.assertEqual((frog["equal_group_size"], frog["equal_group_pct"]), ("5", "3.5"))
        self.assertIn("No equal-balance cluster: 5 wallets", frog["failed_checks"])

    def test_rpc_429_is_retried_after_a_pause(self):
        self.http.rate_limits = 2
        _, bought, text = self.run_once()
        self.assertIn(PONS, [p["address"] for p in bought])
        self.assertEqual(self.sleeps, [C["rpc_retry_seconds"], 2 * C["rpc_retry_seconds"]])
        self.assertEqual(self.candidate("FROG")["holders_complete"], "yes")
        self.assertIn("2 rate-limited", text)

    def test_rpc_429_inside_the_json_answer_is_a_rate_limit(self):
        with self.assertRaises(RateLimited):
            rh.rpc_result({"jsonrpc": "2.0", "id": 1,
                           "error": {"code": 429, "message": "Too Many Requests"}})
        with self.assertRaises(ApiError) as ctx:
            rh.rpc_result({"error": {"code": -32000, "message": "block range too large"}})
        self.assertNotIsInstance(ctx.exception, RateLimited)
        self.assertEqual(rh.rpc_result({"result": "0x10"}), "0x10")

    def test_waiting_for_the_rpc_is_capped_per_run(self):
        cfg = dict(CFG, robinhood=dict(C, rpc_retry_budget_seconds=20))
        self.http.rate_limits = 100
        self.run_once(cfg=cfg)
        # Holders: 5 + 10 s, then 15 s more would pass 20 s; the graduation
        # count still has room for one 5 s wait.
        self.assertEqual(self.sleeps, [5, 10, 5])

    def test_rpc_429_after_every_retry_leaves_holders_unknown(self):
        self.http.rate_limits = C["rpc_retries"] + 1
        self.run_once()
        self.assertEqual(self.sleeps, [5, 10, 15])
        self.assertIn("Holders: unknown", self.candidate("FROG")["failed_checks"])

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

    def rival(self, token, hours_ago, name="FROG", dex="pons-v2-dex", **kw):
        pool = "0x" + token[2:4] * 32
        self.http.more.setdefault(dex, []).append(
            gecko(dex, token, pool, ago(hours=hours_ago), name, **kw))

    def test_an_earlier_launchpad_token_with_the_same_name_makes_a_copycat(self):
        self.rival(RIVAL, 24)
        _, bought, _ = self.run_once()
        self.assertNotIn(PONS, [p["address"] for p in bought])
        frog = self.candidate("FROG")
        self.assertIn("Not a copycat: 1 earlier Pons/Pools.trade token(s) called FROG in the "
                      f"last 7 days; the first, {RIVAL}, graduated 22.0 h before this one",
                      frog["failed_checks"])
        self.assertEqual(frog["copycat_of"], RIVAL)
        self.assertEqual(frog["goplus_is_honeypot"], "")      # later checks not reached

    def test_the_earliest_graduation_is_the_original(self):
        self.rival(RIVAL2, 24)
        self.rival(RIVAL, 72, dex="uniswap-pools-trade")
        self.run_once()
        frog = self.candidate("FROG")
        self.assertEqual(frog["copycat_of"], RIVAL)
        self.assertIn("2 earlier Pons/Pools.trade token(s)", frog["failed_checks"])

    def test_same_named_tokens_created_later_are_ignored(self):
        self.rival(RIVAL, 1)                                  # graduated after FROG (2 h ago)
        _, bought, text = self.run_once()
        self.assertIn(PONS, [p["address"] for p in bought])
        self.assertIn("no earlier Pons/Pools.trade token called FROG in the last 7 days "
                      "(ignored: 1 graduated later)", text)
        self.assertEqual(self.candidate("FROG")["copycat_of"], "")

    def test_clones_with_liquidity_near_their_market_cap_are_ignored(self):
        self.rival(RIVAL, 24, liquidity=55_000, market_cap=60_000)          # 92%
        self.rival(RIVAL2, 30, liquidity=10_000, market_cap=100_000)        # 10% on GT ...
        self.http.search = [pair(RIVAL2, "0x" + "6" * 64, "FROG", 60 * 30, liquidity=90_000)]
        self.http.search[0]["marketCap"] = 90_000                           # ... 100% now
        _, bought, text = self.run_once()
        self.assertIn(PONS, [p["address"] for p in bought])
        self.assertIn("(ignored: 2 with liquidity 90%+ of market cap)", text)
        # Just under 90% counts as a real earlier token.
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.http.more, self.http.search = {}, []
        self.rival(RIVAL, 24, liquidity=53_000, market_cap=60_000)          # 88%
        self.run_once()
        self.assertEqual(self.candidate("FROG")["copycat_of"], RIVAL)

    def test_tokens_from_other_launchpads_or_chains_are_ignored(self):
        # Only on DexScreener (not a Pons or Pools.trade token GeckoTerminal
        # listed), or on another DEX or chain: not compared.
        self.http.search = [pair(RIVAL, "0x" + "5" * 64, "FROG", 60 * 24, liquidity=10**6)]
        self.http.more = {"uniswap-v4-robinhood": [
            gecko("uniswap-v4-robinhood", RIVAL2, "0x" + "6" * 64, ago(hours=24), "FROG")]}
        _, bought, text = self.run_once()
        self.assertIn(PONS, [p["address"] for p in bought])
        self.assertIn("no earlier Pons/Pools.trade token called FROG", text)
        searches = [c for c in self.http.calls if c[0] == "dexscreener" and "/search" in c[1]]
        self.assertEqual(searches, [])                     # nothing to compare: no search

    def test_same_name_counts_even_with_another_symbol(self):
        self.rival(RIVAL, 24, name="FRG")
        self.http.included = [gecko_token(RIVAL, "Frog")]
        self.run_once()
        self.assertEqual(self.candidate("FROG")["copycat_of"], RIVAL)

    def test_a_failed_search_falls_back_to_geckoterminals_numbers(self):
        self.rival(RIVAL, 24)
        self.http.search_down = True
        self.run_once()
        frog = self.candidate("FROG")
        self.assertEqual(frog["copycat_of"], RIVAL)
        self.assertIn("DexScreener search failed, GeckoTerminal's numbers used",
                      frog["failed_checks"])

    def test_launchpad_tokens_are_remembered_for_the_copycat_window(self):
        self.rival(RIVAL, 3)
        self.run_once()
        self.assertIn(RIVAL, self.strategy().trader.state["launchpad_tokens"])
        # GeckoTerminal stops listing it; a FROG graduating 2 days later is
        # still compared with it ...
        self.http.more = {}
        later = NOW + timedelta(days=2)
        self.http.more = {"pons-v2-dex": [gecko("pons-v2-dex", RIVAL2, "0x" + "7" * 64,
                                                (later - timedelta(hours=2)).isoformat(), "FROG")]}
        self.http.pairs[RIVAL2] = [pair(RIVAL2, "0x" + "7" * 64, "FROG", 120 - 2 * 24 * 60)]
        s = self.strategy()
        s.apply(s.fetch(later), lambda *_: None)
        rows_ = [r for r in rows(self.path("candidates.csv")) if r["token_address"] == RIVAL2]
        self.assertEqual(rows_[0]["copycat_of"], RIVAL)
        # ... and forgotten after 7 days (plus the 6 h a pool is watched).
        s = self.strategy()
        s.apply(s.fetch(NOW + timedelta(days=7, hours=7)), lambda *_: None)
        self.assertNotIn(RIVAL, s.trader.state["launchpad_tokens"])

    def test_liquidity_minimum_per_launchpad(self):
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 120, liquidity=6_000)]
        self.http.pairs[POOLS] = [pair(POOLS, POOLS_POOL, "GLITCH", 60, liquidity=6_000)]
        _, bought, _ = self.run_once()
        self.assertEqual([p["symbol"] for p in bought], ["GLITCH"])
        self.assertIn("Liquidity: $6,000 (need $10,000+ on Pons)",
                      self.candidate("FROG")["failed_checks"])
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.http.pairs[POOLS] = [pair(POOLS, POOLS_POOL, "GLITCH", 60, liquidity=4_999)]
        self.run_once()
        self.assertIn("Liquidity: $4,999 (need $5,000+ on Pools.trade)",
                      self.candidate("GLITCH")["failed_checks"])

    def test_low_liquidity_fails_before_goplus(self):
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 120, liquidity=2_000)]
        self.run_once()
        self.assertIn("Liquidity: $2,000", self.candidate("FROG")["failed_checks"])
        goplus = [c[2]["contract_addresses"] for c in self.http.calls if c[0] == "goplus"]
        self.assertNotIn(PONS, goplus)

    def market(self, symbol="FROG", **changes):
        p = pair(PONS, PONS_POOL, symbol, 120)
        for key, value in changes.items():
            if key == "buys_sells":
                p["txns"]["h1"] = value
            elif key == "change_24h":
                p["priceChange"]["h24"] = value
            else:
                p[key] = value
        self.http.pairs[PONS] = [p]
        _, bought, _ = self.run_once()
        return self.candidate(symbol), PONS in [x["address"] for x in bought]

    def test_a_token_like_sigh_fails_every_market_check(self):
        # SIGH when it was bought: $9.5k market cap, -93% in 24h, 4 buys vs 14 sells.
        frog, bought = self.market(marketCap=9_532, change_24h=-93,
                                   buys_sells={"buys": 4, "sells": 14})
        self.assertFalse(bought)
        for text in ("Market cap: $9,532 (need $25,000+)", "Not down >50% in 24h: -93% in 24h",
                     "More buys than sells (1h): 4 buys vs 14 sells"):
            self.assertIn(text, frog["failed_checks"])
        self.assertEqual(frog["price_change_24h_pct"], "-93")
        self.assertEqual(frog["goplus_is_honeypot"], "")          # later checks not reached
        self.assertNotIn(PONS, [c[2]["contract_addresses"] for c in self.http.calls
                                if c[0] == "goplus"])

    def test_each_market_check_on_its_own(self):
        cases = [({"marketCap": 24_999, "fdv": None}, "Market cap: $24,999"),
                 ({"change_24h": -51}, "Not down >50% in 24h: -51% in 24h"),
                 ({"buys_sells": {"buys": 20, "sells": 20}},
                  "More buys than sells (1h): 20 buys vs 20 sells")]
        for changes, text in cases:
            with self.subTest(changes=changes):
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                frog, bought = self.market(**changes)
                self.assertFalse(bought)
                self.assertEqual(frog["failed_checks"].count(";"), 0, frog["failed_checks"])
                self.assertIn(text, frog["failed_checks"])

    def test_market_check_limits_and_unknowns(self):
        frog, bought = self.market(marketCap=25_000, change_24h=-50,
                                   buys_sells={"buys": 15, "sells": 14})
        self.assertTrue(bought)                                   # the limits themselves pass
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        frog, bought = self.market(marketCap=None, change_24h=None, buys_sells={})
        self.assertFalse(bought)
        for text in ("Market cap: unknown", "Not down >50% in 24h: unknown",
                     "More buys than sells (1h): unknown"):
            self.assertIn(text, frog["failed_checks"])

    def test_market_cap_falls_back_to_fdv(self):
        frog, bought = self.market(marketCap=None, fdv=40_000)
        self.assertTrue(bought)
        self.assertEqual(frog["market_cap_usd"], "40000")

    def test_an_open_position_is_kept_when_the_market_turns(self):
        # Like SIGH: bought before these checks existed. Its position stays
        # and only main's exits can sell it.
        s, _, _ = self.run_once()
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 150, price=0.000095)]
        self.http.pairs[PONS][0].update(marketCap=9_000)
        self.http.pairs[PONS][0]["priceChange"]["h24"] = -93
        s2 = self.strategy()
        s2.apply(s2.fetch(NOW + timedelta(hours=1)), lambda *_: None)
        pos = s2.trader.position(PONS)
        self.assertEqual(pos["remaining_fraction"], 1.0)
        self.assertEqual([r["action"] for r in rows(self.path("journal.csv"))
                          if r["symbol"] == "FROG"], ["BUY"])

    def test_pool_age_comes_from_dexscreener(self):
        self.http.pairs[PONS] = [pair(PONS, PONS_POOL, "FROG", 7 * 60)]   # GT said 2h
        self.run_once()
        self.assertIn("Pool age: 420 min", self.candidate("FROG")["failed_checks"])


class GraduationCountTests(Base):
    def test_graduations_on_chain_vs_seen(self):
        missed = ["0x" + "7" * 40, "0x" + "6" * 40]
        self.http.logs += [graduation(t, block_at(NOW - timedelta(hours=h)))
                           for t, h in ((PONS, 2), (missed[0], 5), (missed[1], 20))]
        self.http.logs.append(graduation("0x" + "5" * 40, block_at(NOW - timedelta(hours=30))))
        s, _, text = self.run_once()
        self.assertIn("Pons graduations on chain, last 24 h: 3; seen by this strategy: 1; "
                      "missed: 2 (counted 0 min ago)", text)
        self.assertIn(f"missed: {missed[1]}, {missed[0]}", text)
        g = s.trader.state["graduations"]
        self.assertEqual((g["tokens"], g["complete"]), (sorted([PONS] + missed), True))
        # Only read-only calls, filtered to the graduation event.
        reads = [c[2][0] for c in self.http.calls if c[0] == "rpc" and c[1] == "eth_getLogs"
                 and c[2][0]["address"] == C["pons_graduation_contract"]]
        self.assertTrue(reads)
        self.assertTrue(all(f["topics"] == [C["pons_graduation_topic"]] for f in reads))
        # Counted again only after graduation_count_minutes; reported meanwhile.
        self.http.calls.clear()
        _, _, text = self.run_once(NOW + timedelta(minutes=20))
        self.assertIn("last 24 h: 3;", text)
        self.assertIn("(counted 20 min ago)", text)
        self.assertFalse([c for c in self.http.calls if c[0] == "rpc" and c[1] == "eth_getLogs"
                          and c[2][0]["address"] == C["pons_graduation_contract"]])

    def test_a_failed_count_is_a_note_not_a_failed_run(self):
        self.http.rate_limits = 100
        s, bought, text = self.run_once()
        self.assertIn("Pons graduations on chain: couldn't count them", text)
        self.assertIn("Pons graduations on chain: not counted yet", text)
        self.assertEqual(len(rows(self.path("candidates.csv"))), 2)


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

    def test_gecko_pools_reads_names_liquidity_and_market_cap(self):
        body = {"data": [gecko("pons-v2-dex", PONS, PONS_POOL, ago(hours=2), "FROG",
                               liquidity=12_345.6, market_cap=50_000)],
                "included": [gecko_token(PONS, "Frog Coin")]}
        (p,) = rh.gecko_pools(body, {"pons-v2-dex"})
        self.assertEqual((p["name"], p["title"], p["liquidity_usd"], p["market_cap_usd"]),
                         ("FROG", "Frog Coin", 12_345.6, 50_000))
        body["data"][0]["attributes"].update(market_cap_usd=None, fdv_usd="70000")
        self.assertEqual(rh.gecko_pools(body, {"pons-v2-dex"})[0]["market_cap_usd"], 70_000)

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
