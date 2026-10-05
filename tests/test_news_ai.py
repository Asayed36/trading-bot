"""Checks for the news strategy's AI check (screener/news_ai.py), with a
made-up Claude: no API call is ever made. Run with:  python -m unittest -v
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import anthropic
import httpx2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import load_config  # noqa: E402
from screener.demo import DemoClaude, DemoNewsHttp  # noqa: E402
from screener.health import INFO, OK, WARN, _news_ai  # noqa: E402
from screener.news import NewsStrategy  # noqa: E402
from screener.news_ai import MODEL, SCHEMA, AiChecker, check_ai, says_buy  # noqa: E402

CFG = load_config()
C = CFG["news"]
NOW = datetime(2026, 9, 24, 13, 30, tzinfo=timezone.utc)
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def with_ai(**changes):
    return dict(CFG, news=dict(C, ai=dict(C["ai"], **changes)))


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "news")

    def go(self, client=None, key=None, cfg=CFG, now=NOW, items=None):
        s = NewsStrategy(cfg, self.tmp.name, DemoNewsHttp(now=now, items=items), None, key,
                         client)
        plan = s.fetch(now=now)
        lines = []
        bought = s.apply(plan, None, lines.append)
        return plan, bought, lines

    def verdicts(self):
        return rows(os.path.join(self.folder, "ai_verdicts.csv"))

    def state(self):
        with open(os.path.join(self.folder, "positions.json")) as fh:
            return json.load(fh)


class AiCheckTests(Base):
    def test_verdicts_logged_next_to_the_rule_based_checks(self):
        claude = DemoClaude()
        _, bought, lines = self.go(claude)
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])
        logged = self.verdicts()
        self.assertEqual([(r["rule_coin"], r["rule_verdict"], r["ai_status"], r["ai_catalyst"],
                           r["agree"]) for r in logged],
                         [("demo-network", "PASS", "ok", "yes", "yes"),
                          ("hypecoin", "FAIL", "ok", "no", "yes")])
        self.assertIn('No hype wording: says "Explores"', logged[1]["rule_failed"])
        self.assertEqual(logged[0]["ai_coin"], "Demo Network")
        self.assertTrue(any(line.strip().startswith("AI   yes: Demo Network (DEMO)")
                            for line in lines))
        self.assertTrue(any("AI checks today (Claude Haiku 4.5): 2 of 100" in line
                            for line in lines))
        # the buy's GitHub issue says what the AI thought
        extra = dict(bought[0]["issue_details"]["extra"])
        self.assertIn("yes: Demo Network", extra["AI check"])

    def test_only_crypto_items_are_sent(self):
        claude = DemoClaude()
        self.go(claude)
        sent = [r["messages"][0]["content"] for r in claude.requests]
        self.assertEqual(len(sent), 2)
        self.assertFalse(any("Factory" in text for text in sent))   # not about crypto
        request = claude.requests[0]
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(MODEL, "claude-haiku-4-5")
        self.assertEqual(request["output_config"],
                         {"format": {"type": "json_schema", "schema": SCHEMA}})
        self.assertIn("Keyword matcher's coin: Demo Network (DEMO)", sent[0])

    def test_crypto_news_naming_no_coin_is_checked_too(self):
        items = [("press", "Acme Raises $20M for Its Blockchain Payments Platform",
                  "The tokenization startup will hire 50 engineers.", 5)]
        claude = DemoClaude()
        _, _, lines = self.go(claude, items=items)
        (row,) = self.verdicts()
        self.assertEqual((row["rule_verdict"], row["ai_status"], row["ai_coin"]),
                         ("no coin", "ok", ""))
        self.assertIn("Keyword matcher's coin: none", claude.requests[0]["messages"][0]["content"])
        self.assertTrue(any(line.strip().startswith("AI: no: no coin") for line in lines))

    def test_recent_headlines_are_sent_for_duplicates(self):
        claude = DemoClaude()
        self.go(claude)
        later = NOW + timedelta(minutes=15)
        items = [("press", "Big Bank's Demo Network Deal Goes Live", "blockchain", 5)]
        self.go(claude, now=later, items=items)
        prompt = claude.requests[-1]["messages"][0]["content"]
        self.assertIn("- [PR Newswire] Big Bank Selects Demo Network", prompt)
        # older than a day: forgotten
        self.go(claude, now=NOW + timedelta(days=2), items=[
            ("press", "Visa Selects Demo Network", "blockchain", 5)])
        prompt = claude.requests[-1]["messages"][0]["content"]
        self.assertNotIn("Big Bank Selects", prompt)


class FallbackTests(Base):
    def test_no_key_means_rule_based_only(self):
        _, bought, lines = self.go(client=None, key=None)
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])     # unchanged
        self.assertEqual([r["ai_status"] for r in self.verdicts()],
                         ["skipped: no CLAUDE_API_KEY secret"] * 2)
        self.assertEqual(self.verdicts()[0]["agree"], "")
        self.assertTrue(any("not checked (no CLAUDE_API_KEY secret); the rule-based checks "
                            "decide" in line for line in lines))
        self.assertEqual(_news_ai(C["ai"], self.state()["ai"], NOW)[0], INFO)

    def test_api_failure_falls_back(self):
        claude = DemoClaude(fail=anthropic.APIConnectionError(request=REQUEST))
        _, bought, _ = self.go(claude)
        self.assertEqual([p["symbol"] for p in bought], ["DEMO"])
        self.assertEqual([r["ai_status"] for r in self.verdicts()],
                         ["error: could not reach Anthropic's API",
                          "skipped: could not reach Anthropic's API"])
        self.assertEqual(len(claude.requests), 1)       # stops trying for this run
        status, detail = _news_ai(C["ai"], self.state()["ai"], NOW)
        self.assertEqual(status, WARN)
        self.assertIn("could not reach Anthropic's API", detail)

    def test_bad_key_falls_back(self):
        response = httpx2.Response(401, request=REQUEST)
        claude = DemoClaude(fail=anthropic.AuthenticationError("bad key", response=response,
                                                               body=None))
        _, bought, _ = self.go(claude)
        self.assertEqual(len(bought), 1)
        self.assertIn("refused", self.verdicts()[0]["ai_status"])

    def test_unusable_answers(self):
        class Odd(DemoClaude):
            def create(self, **request):
                answer = super().create(**request)
                answer.content[0].text = "not json"
                return answer

        _, bought, _ = self.go(Odd())
        self.assertEqual(len(bought), 1)
        self.assertEqual(self.verdicts()[0]["ai_status"], "error: the answer wasn't valid JSON")

    def test_daily_limit(self):
        cfg = with_ai(daily_limit=1)
        claude = DemoClaude()
        self.go(claude, cfg=cfg)
        self.assertEqual(len(claude.requests), 1)
        self.assertEqual(self.verdicts()[1]["ai_status"],
                         "skipped: daily limit of 1 AI checks reached")
        self.assertEqual(self.state()["ai"]["calls"], 1)
        status, detail = _news_ai(cfg["news"]["ai"], self.state()["ai"], NOW)
        self.assertEqual(status, WARN)
        self.assertIn("daily limit reached", detail)
        # a new day, a new count (UTC)
        tomorrow = NOW + timedelta(days=1)
        self.go(claude, cfg=cfg, now=tomorrow,
                items=[("press", "Visa Selects Demo Network", "blockchain", 5)])
        self.assertEqual(len(claude.requests), 2)
        self.assertEqual(self.state()["ai"]["day"], "2026-09-25")
        self.assertEqual(_news_ai(cfg["news"]["ai"], self.state()["ai"], tomorrow)[0], WARN)

    def test_turned_off(self):
        claude = DemoClaude()
        self.go(claude, cfg=with_ai(enabled=False))
        self.assertEqual(claude.requests, [])


class MustPassTests(Base):
    def test_off_by_default_the_ai_decides_nothing(self):
        self.assertFalse(C["ai"]["must_pass"])

        class Sceptic(DemoClaude):
            def create(self, **request):
                answer = super().create(**request)
                data = json.loads(answer.content[0].text)
                answer.content[0].text = json.dumps(dict(data, positive_catalyst=False))
                return answer

        _, bought, _ = self.go(Sceptic())
        self.assertEqual(len(bought), 1)                 # the rule-based checks decided
        self.assertEqual(self.verdicts()[0]["agree"], "no")
        # with must_pass = true, the AI's no blocks the buy
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        plan, bought, _ = self.go(Sceptic(), cfg=with_ai(must_pass=True))
        self.assertEqual(bought, [])
        checks = {ch.name: ch for ch in plan["candidates"][0]["checks"]}
        self.assertEqual(checks["AI check"].status, "FAIL")
        row = self.verdicts()[0]
        self.assertEqual((row["rule_verdict"], row["agree"]), ("PASS", "no"))  # rules alone

    def test_must_pass_without_an_answer_is_rule_based(self):
        _, bought, _ = self.go(client=None, key=None, cfg=with_ai(must_pass=True))
        self.assertEqual(len(bought), 1)


class HelperTests(unittest.TestCase):
    def test_says_buy(self):
        ok = {"status": "ok", "positive_catalyst": True, "about_one_coin": True,
              "false_match": False, "duplicate": False}
        self.assertTrue(says_buy(ok))
        for flag in ({"false_match": True}, {"duplicate": True}, {"about_one_coin": False},
                     {"positive_catalyst": False}):
            self.assertFalse(says_buy(dict(ok, **flag)))
        self.assertIsNone(says_buy({"status": "skipped", "note": "x"}))

    def test_schema_is_strict(self):
        self.assertFalse(SCHEMA["additionalProperties"])
        self.assertEqual(sorted(SCHEMA["required"]), sorted(SCHEMA["properties"]))

    def test_the_test_command(self):
        lines = []
        self.assertEqual(check_ai(CFG, client=DemoClaude(), out=lines.append, now=NOW), 0)
        self.assertIn("AI (claude-haiku-4-5): yes: Quant (QNT)", "\n".join(lines))
        self.assertEqual(check_ai(CFG, client=DemoClaude(fail=anthropic.APIConnectionError(
            request=REQUEST)), out=lambda *a: None, now=NOW), 1)
        os.environ.pop("CLAUDE_API_KEY", None)
        self.assertEqual(check_ai(CFG, out=lambda *a: None, now=NOW), 2)

    def test_health_row(self):
        self.assertEqual(_news_ai(C["ai"], None, NOW)[0], INFO)
        meter = {"day": "2026-09-24", "calls": 7, "last_ok": NOW.isoformat()}
        self.assertEqual(_news_ai(C["ai"], meter, NOW),
                         (OK, "7 of 100 checks today; last answer 2026-09-24 13:30 UTC"))
        self.assertEqual(_news_ai(dict(C["ai"], enabled=False), meter, NOW)[0], INFO)

    def test_checker_never_sends_without_a_key(self):
        state = {}
        checker = AiChecker(C["ai"], None, state, NOW)
        verdict = checker.check({"title": "x", "url": "u", "published": NOW}, {"name": "s"}, [])
        self.assertEqual(verdict, {"status": "skipped", "note": "no CLAUDE_API_KEY secret"})
        self.assertEqual(state["ai"]["calls"], 0)


if __name__ == "__main__":
    unittest.main()
