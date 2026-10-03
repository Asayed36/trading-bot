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
HEAD = 1_000_000
BLOCK_TIME = 0.25
TOKEN = "0x" + "a" * 40       # a new Pons token
CURVE = "0x" + "c" * 40       # its bonding curve (GeckoTerminal's "pool")
FACTORY = "0x" + "f" * 40     # the Pons factory
OLD = "0x" + "d" * 40         # an older token on DexScreener
CREATED = "TokenCreated-topic".ljust(66, "0")
TRADE = "Trade-topic".ljust(66, "0")


def word(n):
    return hex(n)


def transfer(frm, to, amount):
    return {"address": TOKEN, "topics": [rp.TRANSFER, rp.topic_address(frm),
                                         rp.topic_address(to)], "data": word(amount)}


# The token's whole history: 1000 minted to the curve, then four wallets buy
# exactly 50 each (a bundle) and one buys 120.
TRANSFERS = ([transfer(rp.ZERO, CURVE, 1000)]
             + [transfer(CURVE, "0x" + c * 40, 50) for c in "1234"]
             + [transfer(CURVE, "0x" + "5" * 40, 120)])


def gecko_pool(dex, token, pool, created):
    return {"attributes": {"name": "X / WETH", "address": pool, "pool_created_at": created,
                           "reserve_in_usd": "100"},
            "relationships": {"dex": {"data": {"id": dex}},
                              "base_token": {"data": {"id": "robinhood_" + token}}}}


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
                 "labels": ["v4"], "baseToken": {"address": OLD, "symbol": "OLD"},
                 "quoteToken": {"symbol": "WETH"}, "pairCreatedAt": (NOW - 7200) * 1000,
                 "liquidity": {"usd": 5000}, "priceUsd": "0.001", "url": "u"},
                {"chainId": "solana", "pairAddress": "s1"}]}, None
        if "token-profiles" in url or "token-boosts" in url:
            return 200, [{"chainId": "robinhood"}, {"chainId": "solana"}], None
        if url.endswith("/networks/robinhood/dexes"):
            return 200, {"data": [{"id": "uniswap-v4-robinhood"}, {"id": "pons-v2"},
                                  {"id": "uniswap-pools-trade"}]}, None
        if "new_pools" in url:
            if params["page"] > 1:
                return 200, {"data": []}, None
            pool = gecko_pool("pons-v2", TOKEN, CURVE, "2026-10-03T03:00:00Z")
            return 200, {"data": [pool]}, None
        if "/dexes/" in url and url.endswith("/pools"):
            return 200, {"data": []}, None
        if "/tokens/v1/robinhood/" in url:
            return 200, [], None                      # curve-stage tokens: not listed
        if "blockscout" in url:
            return 403, None, "<!DOCTYPE html><title>Just a moment...</title>"
        if "token_security" in url:
            return 200, {"code": 1, "message": "OK", "result": {
                params["contract_addresses"]: {"is_honeypot": "0", "buy_tax": ""}}}, None
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
            return hex(HEAD), None
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            return {"timestamp": hex(int(NOW - (HEAD - number) * BLOCK_TIME))}, None
        if method == "eth_getLogs":
            f = params[0]
            if int(f["toBlock"], 16) - int(f["fromBlock"], 16) > 1000:
                return None, "range too large"       # makes the probe split the range
            topics = f.get("topics") or []
            mine = rp.topic_address(TOKEN)
            if f.get("address") == TOKEN:
                if len(topics) > 1:                  # mints only
                    return [t for t in TRANSFERS if t["topics"][1] == topics[1]], None
                return list(TRANSFERS) if self._first(f) else [], None
            if f.get("address") == FACTORY:
                return [{"address": FACTORY, "topics": [CREATED]}], None
            if f.get("address") == CURVE:
                return [{"address": CURVE, "topics": [TRADE]}] * 3, None
            if topics[1:2] == [mine]:
                return [{"address": FACTORY, "topics": [CREATED, mine]}], None
            if topics[2:3] == [mine]:
                return [{"address": CURVE, "topics": [TRADE, None, mine]}], None
            return [], None
        return None, "unknown"

    def _first(self, f):
        # Return the token's transfers only in the chunk that holds its creation.
        created = HEAD - int((NOW - rp._ts("2026-10-03T03:00:00Z")) / BLOCK_TIME)
        return int(f["fromBlock"], 16) <= created <= int(f["toBlock"], 16)


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

    def test_balances_and_concentration_from_transfers(self):
        bal = rp.balances_from_transfers(TRANSFERS)
        self.assertEqual(bal[CURVE], 1000 - 4 * 50 - 120)
        got = rp.concentration(bal, skip={CURVE})
        self.assertEqual((got["holders"], got["largest_pct"], got["top10_pct"],
                          got["skipped_pct"], got["equal_balance_groups"]),
                         (5, 12.0, 32.0, 68.0, [4]))

    def test_launchpad_names(self):
        self.assertEqual(rp.launchpad_of("pons-v2"), "pons")
        self.assertEqual(rp.launchpad_of("uniswap-pools-trade"), "pools")
        self.assertIsNone(rp.launchpad_of("uniswap-v4-robinhood"))


class ProbeTests(unittest.TestCase):
    def run_probe(self, env=None):
        http = FakeHttp()
        result = rp.Probe(http=http, env=env or {}, now=NOW).run()
        return http, result, rp.report(result)

    def test_full_run_reports_every_source(self):
        http, r, text = self.run_probe()
        self.assertNotIn("crashes", r)
        self.assertEqual(r["dexscreener"]["pairs_found"], 1)
        self.assertEqual(r["geckoterminal"]["launchpad_like_dexes"],
                         ["pons-v2", "uniswap-pools-trade"])
        self.assertEqual(r["rpc"]["chain_id"], 4663)
        self.assertAlmostEqual(r["rpc"]["seconds_per_block"], BLOCK_TIME)
        pons = r["launchpad_contracts"]["pons"]
        (traced,) = pons["tokens"]
        self.assertEqual(traced["minted_to"], [CURVE])
        self.assertEqual({e for e, _, _ in traced["events_naming_token"]}, {FACTORY, CURVE})
        self.assertEqual({c["contract"]: [t for t, _ in c["by_topic"]] for c in pons["contracts"]},
                         {FACTORY: [CREATED], CURVE: [TRADE]})
        self.assertTrue(all(c["complete"] for c in pons["contracts"]))
        self.assertEqual(r["launchpad_contracts"]["pools"]["tokens_traced"], 0)
        self.assertEqual(r["curve_stage"]["pons"]["listed_on_dexscreener"], 0)
        (holders,) = r["holders"]["from_transfer_logs"]
        self.assertTrue(holders["complete"])         # range split until accepted
        self.assertEqual((holders["largest_pct"], holders["equal_balance_groups"]),
                         (12.0, [4]))
        self.assertTrue(r["holders"]["blockscout"]["keyless_instance_api"].startswith("HTTP 403"))
        self.assertEqual(r["goplus"]["without_key"][0]["launchpad"], "pons")
        self.assertIn("not tested", r["goplus"]["with_key"])
        for heading in ("## DexScreener", "## GeckoTerminal", "## Launchpad contracts",
                        "## Curve stage", "## Holders", "## GoPlus"):
            self.assertIn(heading, text)
        self.assertFalse([c for c in http.seen if c[0] == "POST"])   # no key: no login

    def test_goplus_with_a_key_logs_in_and_sends_the_token(self):
        http, r, _ = self.run_probe({"GOPLUS_APP_KEY": "k", "GOPLUS_APP_SECRET": "s"})
        (login,) = [c for c in http.seen if c[0] == "POST"]
        self.assertEqual(login[1], rp.GOPLUS + "/token")
        self.assertEqual(login[2]["sign"], rp.goplus_sign("k", "s", login[2]["time"]))
        keyed = [c for c in http.seen if c[0] == "GET" and "token_security" in c[1] and c[3]]
        self.assertTrue(keyed and all(c[3] == {"Authorization": "T"} for c in keyed))
        self.assertIsInstance(r["goplus"]["with_key"], list)

    def test_one_broken_source_doesnt_stop_the_others(self):
        http = FakeHttp()
        http.rpc = lambda method, params: (_ for _ in ()).throw(OSError("down"))
        r = rp.Probe(http=http, env={}, now=NOW).run()
        self.assertTrue(any("rpc_basics" in c for c in r["crashes"]))
        self.assertEqual(r["launchpad_contracts"], "skipped: no block time from the RPC")
        self.assertIn("goplus", r)


if __name__ == "__main__":
    unittest.main()
