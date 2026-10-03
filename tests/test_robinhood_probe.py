"""Checks for the Robinhood Chain data probe (robinhood_probe.py), with
made-up answers instead of the real websites.
Run with:  python -m unittest -v
"""

import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import robinhood_probe as rp  # noqa: E402

NOW = 1_791_000_000.0
TOKEN = "0x" + "a" * 40
FRESH = "0x" + "b" * 40
FACTORY = "0x" + "f" * 40
TOPIC = "0x" + "1" * 64


class FakeHttp:
    """Answers by URL; records every call."""

    def __init__(self):
        self.calls = Counter()
        self.seen = []

    def get(self, url, params=None, headers=None, gap=0):
        self.seen.append(("GET", url, params, headers))
        self.calls[url.split("/")[2]] += 1
        if "/latest/dex/search" in url:
            return 200, {"pairs": [
                {"chainId": "robinhood", "pairAddress": "0xp1", "dexId": "uniswap",
                 "labels": ["v4"], "baseToken": {"address": TOKEN, "symbol": "CAT"},
                 "quoteToken": {"symbol": "WETH"}, "pairCreatedAt": (NOW - 7200) * 1000,
                 "liquidity": {"usd": 5000}, "priceUsd": "0.001", "url": "u"},
                {"chainId": "solana", "pairAddress": "s1"}]}, None
        if "token-profiles" in url or "token-boosts" in url:
            return 200, [{"chainId": "robinhood"}, {"chainId": "solana"}], None
        if url.endswith("/networks/robinhood/dexes"):
            return 200, {"data": [{"id": "uniswap-v4-robinhood"}, {"id": "pons"}]}, None
        if "new_pools" in url:
            return 200, {"data": [{"attributes": {"name": "DOG / WETH",
                                                  "pool_created_at": "2026-10-03T05:00:00Z"},
                                   "relationships": {
                                       "dex": {"data": {"id": "uniswap-v4-robinhood"}},
                                       "base_token": {"data": {"id": "robinhood_" + TOKEN}}}}]}, None
        if "/tokens/multi/" in url:
            return 200, {"data": []}, None
        if "/search" in url:
            return 200, {"items": [{"type": "contract", "name": "PonsLaunchpad",
                                    "address": FACTORY}]}, None
        if url.endswith(f"/addresses/{TOKEN}"):
            return 200, {"creator_address_hash": "0xdev", "creation_transaction_hash": "0xtx",
                         "token": {"name": "Cat"}}, None
        if url.endswith("/transactions/0xtx"):
            return 200, {"to": {"hash": FACTORY, "name": "PonsLaunchpad"},
                         "method": "createToken"}, None
        if url.endswith(f"/addresses/{FACTORY}/logs"):
            return 200, {"items": [{"topics": [TOPIC],
                                    "decoded": {"method_call": "TokenCreated(address token)"}}]}, None
        if "internal-transactions" in url:
            return 200, {"items": [{"created_contract": {"hash": FRESH}}, {}]}, None
        if "/tokens/v1/robinhood/" in url:
            return 200, [], None                      # brand-new tokens: not listed
        if url.endswith("/holders"):
            return 200, {"items": [{"address": {"hash": "0x" + c * 40, "is_contract": False},
                                    "value": "100"} for c in "1234"]
                         + [{"address": {"hash": "0x" + "9" * 40, "is_contract": True},
                             "value": "600"}]}, None
        if "/tokens/" in url:
            return 200, {"symbol": "CAT", "total_supply": "1000", "holders_count": "5"}, None
        if "token_security" in url:
            return 200, {"code": 1, "message": "OK", "result": {
                params["contract_addresses"]: {"is_honeypot": "0", "buy_tax": "0",
                                               "holders": [{"percent": "0.6"}]}}}, None
        return 404, None, "not found"

    def post_json(self, url, payload, gap=0):
        self.seen.append(("POST", url, payload, None))
        return 200, {"code": 1, "result": {"access_token": "T"}}, None

    def rpc(self, method, params):
        rp.rpc_request(method, params)               # refuses anything not allowed
        self.seen.append(("RPC", method, params, None))
        if method == "eth_chainId":
            return hex(4663), None
        if method == "eth_blockNumber":
            return hex(1_000_000), None
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            return {"timestamp": hex(int(NOW) - (1_000_000 - number) // 4)}, None
        if method == "eth_getLogs":
            if int(params[0]["toBlock"], 16) - int(params[0]["fromBlock"], 16) > 4000:
                return None, "range too large"       # makes the probe halve the window
            return [{"topics": [TOPIC]}, {"topics": [TOPIC]}], None
        return None, "unknown"


class HelperTests(unittest.TestCase):
    def test_only_read_only_rpc_calls(self):
        self.assertEqual(rp.RPC_METHODS, {"eth_chainId", "eth_blockNumber",
                                          "eth_getBlockByNumber", "eth_getLogs"})
        for method in ("eth_sendRawTransaction", "eth_sendTransaction", "eth_sign",
                       "personal_sign", "eth_call"):
            with self.assertRaises(ValueError):
                rp.rpc_request(method, [])

    def test_equal_balance_groups(self):
        self.assertEqual(rp.equal_groups([100, 100.2, 100.4, 5, 5, 70]), [3, 2])
        self.assertEqual(rp.equal_groups([1, 2, 3]), [])

    def test_holder_summary_skips_pools_and_finds_bundles(self):
        holders = [{"address": {"hash": "0x" + c * 40}, "value": "100"} for c in "123"]
        holders.append({"address": {"hash": "0x" + "9" * 40, "is_contract": True},
                        "value": "700"})
        got = rp.holder_summary(holders, "1000", skip={"0x" + "9" * 40})
        self.assertEqual((got["top10_pct"], got["equal_balance_groups"]), (30.0, [3]))

    def test_launchpad_names(self):
        self.assertEqual(rp.launchpad_of("PonsLaunchpadV2"), "pons")
        self.assertEqual(rp.launchpad_of("Pools.trade Factory"), "pools")
        self.assertIsNone(rp.launchpad_of("UniswapV4PoolManager"))


class ProbeTests(unittest.TestCase):
    def run_probe(self, env=None):
        http = FakeHttp()
        result = rp.Probe(http=http, env=env or {}, now=NOW).run()
        return http, result, rp.report(result)

    def test_full_run_reports_every_source(self):
        http, r, text = self.run_probe()
        self.assertNotIn("crashes", r)
        self.assertEqual(r["dexscreener"]["pairs_found"], 1)
        self.assertEqual(r["dexscreener"]["token-profiles"]["robinhood"], 1)
        self.assertEqual(r["geckoterminal"]["new_pools"], len(range(rp.GECKO_PAGES)))
        self.assertEqual(r["token_origins"]["creating_contracts"][0],
                         {"address": FACTORY, "name": "PonsLaunchpad", "tokens": 1,
                          "launchpad": "pons"})
        events = r["rpc"]["launchpad_events"][0]
        self.assertEqual((r["rpc"]["chain_id"], events["logs"], events["recently_created"]),
                         (4663, 2, 1))
        self.assertLessEqual(events["blocks_read"], 4000)    # halved until accepted
        self.assertEqual(r["curve_stage"]["listed_on_dexscreener"], 0)
        holders = r["blockscout_holders"]["keyless"][0]
        self.assertEqual(holders["equal_balance_groups"], [4])
        self.assertEqual(r["goplus"]["without_key"][0]["values"]["is_honeypot"], "0")
        self.assertIn("not tested", r["goplus"]["with_key"])
        for heading in ("## DexScreener", "## GeckoTerminal", "## Public RPC",
                        "## Curve stage", "## Blockscout holders", "## GoPlus"):
            self.assertIn(heading, text)
        self.assertFalse([c for c in http.seen if c[0] == "POST"])   # no key: no login

    def test_goplus_with_a_key_logs_in_and_sends_the_token(self):
        http, r, _ = self.run_probe({"GOPLUS_APP_KEY": "k", "GOPLUS_APP_SECRET": "s"})
        (login,) = [c for c in http.seen if c[0] == "POST"]
        self.assertEqual(login[1], rp.GOPLUS + "/token")
        self.assertEqual(login[2]["sign"], rp.goplus_sign("k", "s", login[2]["time"]))
        self.assertTrue(all(c[3] == {"Authorization": "T"} for c in http.seen
                            if c[0] == "GET" and "token_security" in c[1] and c[3]))
        self.assertIsInstance(r["goplus"]["with_key"], list)

    def test_one_broken_source_doesnt_stop_the_others(self):
        http = FakeHttp()
        http.rpc = lambda method, params: (_ for _ in ()).throw(OSError("down"))
        r = rp.Probe(http=http, env={}, now=NOW).run()
        self.assertTrue(any("rpc_and_events" in c for c in r["crashes"]))
        self.assertIn("goplus", r)


if __name__ == "__main__":
    unittest.main()
