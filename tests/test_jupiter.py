"""Checks for Jupiter's organic score in entries.csv (screener/jupiter.py),
with made-up Jupiter answers. Logging only: no trade may change.
Run with:  python -m unittest -v
"""

import csv
import os
import sys
import tempfile
import unittest

import unittest.mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import running  # noqa: E402

from run import load_config, run  # noqa: E402
from screener.demo import DemoApi  # noqa: E402
from screener.filters import Result  # noqa: E402
from screener.jupiter import COLUMNS, URL, JupiterOrganic, organic_values  # noqa: E402
from screener.paper_trader import ENTRY_COLUMNS, PaperTrader  # noqa: E402

CFG = running(load_config())
MINT = "MINTaaaa"
ROW = {"id": MINT, "organicScore": 63.456, "organicScoreLabel": "medium",
       "stats1h": {"buyOrganicVolume": 2500, "buyVolume": 10000,
                   "numOrganicBuyers": 12, "numTraders": 300}}


def rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class ParsingTests(unittest.TestCase):
    def test_values_from_a_tokens_api_row(self):
        self.assertEqual(organic_values(ROW, MINT), {
            "jupiter_organic_score": 63.46, "jupiter_organic_label": "medium",
            "jupiter_organic_volume_1h_pct": 25.0, "jupiter_organic_buyers_1h_pct": 4.0})

    def test_unknowns_are_none(self):
        self.assertEqual(organic_values({"id": MINT, "stats1h": {"buyVolume": 0}}, MINT),
                         dict.fromkeys(COLUMNS))
        self.assertEqual(organic_values(dict(ROW, id="other"), MINT), dict.fromkeys(COLUMNS))

    def test_lookup_asks_the_tokens_api_and_never_raises(self):
        calls = []

        def get(url, params, headers, timeout):
            calls.append((url, params))
            return FakeResponse(200, [dict(ROW, id="other"), ROW])

        self.assertEqual(JupiterOrganic(get=get)(MINT)["jupiter_organic_score"], 63.46)
        self.assertEqual(calls, [(URL, {"query": MINT})])
        # No answer: blank values, marked so a caller can wait for one.
        for answer, why in ((FakeResponse(500, None), "HTTP 500"),
                            (FakeResponse(200, ValueError("not json")), "ValueError")):
            self.assertEqual(JupiterOrganic(get=lambda *a, **k: answer)(MINT),
                             dict(dict.fromkeys(COLUMNS), jupiter_error=why))

        def down(*a, **k):
            raise requests.ConnectionError("no network")
        self.assertEqual(JupiterOrganic(get=down)(MINT),
                         dict(dict.fromkeys(COLUMNS), jupiter_error="ConnectionError"))
        # An answer without this token: blank, but an answer.
        self.assertEqual(JupiterOrganic(get=lambda *a, **k: FakeResponse(200, {"error": "x"}))(
            MINT), dict.fromkeys(COLUMNS))


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_at_the_buy(self):
        trader = PaperTrader(CFG["paper_trading"], self.d)
        trader.organic = lambda mint: organic_values(dict(ROW, id=mint), mint)
        trader.buy(Result("X", "X", "X", {"priceUsd": "1.5"}))
        (row,) = rows(os.path.join(self.d, "entries.csv"))
        self.assertEqual(list(row), ENTRY_COLUMNS)
        self.assertEqual([row[k] for k in COLUMNS], ["63.46", "medium", "25.0", "4.0"])

    def test_blank_without_a_lookup(self):
        PaperTrader(CFG["paper_trading"], self.d).buy(Result("X", "X", "X", {"priceUsd": "1.5"}))
        (row,) = rows(os.path.join(self.d, "entries.csv"))
        self.assertEqual([row[k] for k in COLUMNS], ["", "", "", ""])

    def test_every_solana_strategy_in_a_run_and_trades_unchanged(self):
        asked = []

        def jupiter(mint):
            asked.append(mint)
            return organic_values(dict(ROW, id=mint), mint)

        run(DemoApi(), CFG, self.d, out=lambda *a: None, jupiter=jupiter)
        main = rows(os.path.join(self.d, "entries.csv"))
        early = rows(os.path.join(self.d, "early", "entries.csv"))
        self.assertTrue(main and early)
        for row in main + early:
            self.assertEqual(row["jupiter_organic_label"], "medium")
        self.assertEqual(sorted(asked), sorted(r["token_address"] for r in main + early))
        # Same run without the lookup: the same trades.
        with tempfile.TemporaryDirectory() as other:
            run(DemoApi(), CFG, other, out=lambda *a: None)
            for name in ("journal.csv", os.path.join("early", "journal.csv")):
                strip = lambda rs: [{k: v for k, v in r.items() if k != "time_utc"} for r in rs]
                self.assertEqual(strip(rows(os.path.join(self.d, name))),
                                 strip(rows(os.path.join(other, name))))

    def test_convergence_trader_gets_the_lookup(self):
        from screener.convergence import ConvergenceStrategy
        traders = []
        original = ConvergenceStrategy.__init__

        def spy(strategy, *a, **k):
            original(strategy, *a, **k)
            traders.append(strategy.trader)

        jupiter = lambda mint: dict.fromkeys(COLUMNS)
        with unittest.mock.patch.object(ConvergenceStrategy, "__init__", spy):
            run(DemoApi(), CFG, self.d, out=lambda *a: None, jupiter=jupiter)
        self.assertIs(traders[0].organic, jupiter)


if __name__ == "__main__":
    unittest.main()
