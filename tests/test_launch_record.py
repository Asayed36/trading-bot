"""Checks for the early-launch recorder (screener/launch_record.py, launch_record_bot.py,
its place in launch_bot.py and the "launch record" line of the daily comparison), with made-up
pump.fun events: nothing is downloaded, nothing is bought. Run with:  python -m unittest -v
"""

import asyncio
import base64
import copy
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launch_bot  # noqa: E402
import launch_record_bot as lrb  # noqa: E402
from screener import launch_record as lr  # noqa: E402
from screener import pumpfeed as pf  # noqa: E402
from screener.health import INFO, OK, WARN  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402
from tests.test_health import NOW as HEALTH_NOW  # noqa: E402
from tests.test_health import Base as HealthBase  # noqa: E402

CFG = load_config()
RealRunner = launch_bot.Runner
T0 = 1_800_000_000          # a Friday 2027-01-15 08:00:00 UTC, when the launches are created
LAG = 1                     # the feed delivers an event one second after its on-chain time
PRICE = 3e-8
CP = lr.DEFAULT_CHECKPOINTS


def key(n):
    return bytes([n % 256]) * 31 + bytes([n // 256 + 1])


def b58(n):
    return pf.b58encode(key(n))


def line(raw):
    return "Program data: " + base64.b64encode(raw).decode()


def trade_line(mint, user, is_buy, sol, tokens, price, ts, progress=10.0):
    vtok = 10**15
    real = int(pf.CURVE_TOKENS * (1 - progress / 100))
    return line(pf.TRADE_EVENT + mint + int(sol * 1e9).to_bytes(8, "little")
                + int(tokens * 1e6).to_bytes(8, "little") + bytes([1 if is_buy else 0]) + user
                + int(ts).to_bytes(8, "little", signed=True)
                + int(price * 1e18).to_bytes(8, "little") + vtok.to_bytes(8, "little")
                + (0).to_bytes(8, "little") + real.to_bytes(8, "little") + bytes(64))


def create_line(mint, creator, ts, name="Frog", symbol="FROG", with_ts=True):
    raw = pf.CREATE_EVENT
    for text in (name, symbol, "https://x"):
        raw += len(text.encode()).to_bytes(4, "little") + text.encode()
    raw += mint + bytes(32) + creator + creator
    if with_ts:
        raw += int(ts).to_bytes(8, "little", signed=True) + bytes(32)
    return line(raw)


def complete_line(mint, ts=None):
    raw = pf.COMPLETE_EVENT + bytes(32) + mint + bytes(32)
    if ts is not None:
        raw += int(ts).to_bytes(8, "little", signed=True)
    return line(raw + bytes(8))


def make(tmp, **over):
    cfg = copy.deepcopy(CFG)
    cfg["launch_record"].update(over)
    return lr.LaunchRecorder(cfg, tmp, clock=lambda: T0)


class Driver:
    """Feeds a recorder like the live feed would: on-chain times are exact, receive times
    are LAG seconds later."""

    def __init__(self, rec):
        self.rec, self.ts0, self.creator = rec, {}, {}

    def create(self, n, creator=1000, at=T0, dev=None, slot=100, name=None, symbol=None,
               with_ts=True):
        mint, who = key(n), key(creator)
        ts = at - LAG
        self.ts0[n], self.creator[n] = ts, who
        logs = [create_line(mint, who, ts, name or f"Coin{n}", symbol or f"C{n}", with_ts)]
        if dev:
            logs.append(trade_line(mint, who, True, dev[0], dev[1], PRICE, ts))
        self.rec.on_logs(logs, False, at, slot)

    def trade(self, n, wallet, rel, buy=True, sol=1.0, price=PRICE, tokens=1000.0, slot=None,
              progress=10.0):
        ts = self.ts0[n] + rel
        user = self.creator[n] if wallet == "creator" else key(wallet)
        self.rec.on_logs([trade_line(key(n), user, buy, sol, tokens, price, ts, progress)],
                         False, ts + LAG, slot)

    def finish(self, at=None):
        at = at or T0 + lr.TRACK_SECONDS + 5
        self.rec.tick(at)
        self.rec.flush(at)


def rows(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def day_file(tmp, day="2027-01-15"):
    return os.path.join(tmp, "launch-record", f"launches-{day}.csv")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def run_one(self, **over):
        """A recorder that writes every launch (sample 100%) unless told otherwise."""
        over.setdefault("sample_pct", 100.0)
        rec = make(self.d, **over)
        rec.connected(T0 - 1, "test")
        return rec, Driver(rec)


# ---------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------

class DecodeTests(unittest.TestCase):
    def test_a_created_launch_with_its_creators_buy_in_the_same_transaction(self):
        mint, creator = key(1), key(2)
        ts = T0 - LAG
        events = pf.decode([create_line(mint, creator, ts, "Frog", "FROG"),
                            trade_line(mint, creator, True, 2.0, 20_000_000, PRICE, ts)])
        created, buy = events
        self.assertEqual((created["kind"], created["mint"], created["creator"], created["name"],
                          created["symbol"], created["ts"]),
                         ("create", pf.b58encode(mint), pf.b58encode(creator), "Frog", "FROG", ts))
        self.assertEqual((buy["kind"], buy["is_buy"], buy["sol"], buy["tokens"], buy["ts"]),
                         ("trade", True, 2.0, 20_000_000.0, ts))

    def test_a_create_event_without_the_on_chain_time_still_decodes(self):
        (created,) = pf.decode([create_line(key(1), key(2), 0, with_ts=False)])
        self.assertNotIn("ts", created)
        self.assertEqual(created["mint"], pf.b58encode(key(1)))

    def test_complete_events_carry_their_time_when_present(self):
        with_ts, without = pf.decode([complete_line(key(1), 123), complete_line(key(1))])[0], \
            pf.decode(["Program data: " + base64.b64encode(
                pf.COMPLETE_EVENT + bytes(32) + key(1)).decode()])[0]
        self.assertEqual(with_ts["ts"], 123)
        self.assertNotIn("ts", without)


# ---------------------------------------------------------------------
# what is known at creation
# ---------------------------------------------------------------------

class CreationTests(Base):
    def test_creation_facts_use_the_on_chain_time(self):
        rec, d = self.run_one()
        d.create(1, dev=(2.0, 20_000_000))             # created Fri 2027-01-15 08:00:00 UTC
        d.trade(1, 7, 3)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["created_at_utc"], row["created_hour_utc"], row["created_weekday"],
                          row["created_source"]), ("2027-01-15T07:59:59Z", "7", "4", "chain"))
        self.assertEqual((row["token_address"], row["name"], row["symbol"]),
                         (pf.b58encode(key(1)), "Coin1", "C1"))
        self.assertEqual(row["creator"], pf.b58encode(key(1000)))
        self.assertEqual((row["dev_buy_pct"], row["dev_buy_sol"]), ("2", "2"))   # 20M of 1B tokens

    def test_without_an_on_chain_time_the_receive_time_is_used_and_says_so(self):
        rec, d = self.run_one()
        d.create(1, with_ts=False)
        d.trade(1, 7, 3)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["created_source"], row["created_at_utc"]),
                         ("received", "2027-01-15T08:00:00Z"))

    def test_an_implausible_on_chain_time_is_not_trusted(self):
        rec, d = self.run_one()
        mint, who = key(1), key(1000)
        rec.on_logs([create_line(mint, who, T0 - 86400)], False, T0, 100)   # a day off
        rec.tick(T0 + lr.TRACK_SECONDS + 5)
        rec.flush()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["created_source"], "received")

    def test_no_creator_buy_means_blank_not_zero(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 3)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["dev_buy_pct"], row["dev_buy_sol"], row["creator_sold_pct_1h"]),
                         ("", "", ""))

    def test_first_block_buyers_and_the_first_four_trades_after_creation(self):
        rec, d = self.run_one()
        d.create(1, slot=500, dev=(1.0, 1e7))
        d.trade(1, 11, 0, slot=500)                    # bought in the creation block
        d.trade(1, 12, 0, slot=500)
        d.trade(1, 11, 0, slot=500)                    # same wallet again
        d.trade(1, 13, 1, slot=501)
        d.trade(1, 14, 2, buy=False, slot=501)         # trade no. 5 after creation: not in the bundle count
        d.trade(1, 15, 3, slot=502)
        d.trade(1, "creator", 3, slot=502)             # the creator is never counted as a buyer
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["first_block_buyers"], "2")             # wallets 11 and 12
        # first four trades after creation: 11, 12, 11, 13 -> distinct buyers 11, 12, 13
        self.assertEqual(row["bundle_suspect_buyers"], "3")

    def test_creator_selling(self):
        rec, d = self.run_one()
        d.create(1, dev=(1.0, 100_000_000))            # the creator holds 100M tokens
        d.trade(1, "creator", 30, buy=False, tokens=25_000_000)
        d.trade(1, "creator", 600, buy=False, tokens=25_000_000)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["creator_sold_within_60s"], row["creator_sold_pct_1h"]), ("1", "50"))
        rec2, d2 = self.run_one()
        d2.create(2, dev=(1.0, 100_000_000))
        d2.trade(2, "creator", 600, buy=False, tokens=10_000_000)
        d2.finish()
        last = rows(day_file(self.d))[-1]
        self.assertEqual((last["creator_sold_within_60s"], last["creator_sold_pct_1h"]), ("0", "10"))


# ---------------------------------------------------------------------
# the price path
# ---------------------------------------------------------------------

class CheckpointTests(Base):
    def test_each_checkpoint_takes_the_last_trade_at_or_before_it(self):
        rec, d = self.run_one()
        d.create(1)
        for rel, price in ((3, 1e-8), (5, 2e-8), (8, 3e-8), (50, 4e-8), (130, 5e-8), (3600, 6e-8)):
            d.trade(1, 7, rel, price=price)
        d.trade(1, 8, 3601, price=9e-8)               # after the hour: ignored
        d.finish()
        (row,) = rows(day_file(self.d))
        got = {c: row[f"price_sol_{c}s"] for c in CP}
        self.assertEqual(got, {5: "2e-08", 10: "3e-08", 20: "3e-08", 30: "3e-08", 60: "4e-08",
                               120: "4e-08", 300: "5e-08", 900: "5e-08", 3600: "6e-08"})
        self.assertEqual((row["peak_price_sol"], row["seconds_to_peak"]), ("6e-08", "3600"))

    def test_a_checkpoint_with_no_trade_before_it_is_blank_never_zero_or_copied_forward(self):
        rec, d = self.run_one()
        d.create(1)                                    # no creator buy, so no trade at creation
        d.trade(1, 7, 40, price=2e-8)
        d.finish()
        (row,) = rows(day_file(self.d))
        for c in (5, 10, 20, 30):
            self.assertEqual(row[f"price_sol_{c}s"], "", c)
        self.assertEqual(row["price_sol_60s"], "2e-08")
        self.assertNotIn("0", {row[f"price_sol_{c}s"] for c in CP})

    def test_a_late_arriving_older_trade_does_not_overwrite_a_newer_price(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 8, price=3e-8)
        d.trade(1, 8, 6, price=2e-8)                   # older on-chain, arrived later
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["price_sol_10s"], "3e-08")

    def test_a_launch_finished_early_leaves_the_checkpoints_it_did_not_reach_blank(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 30, price=2e-8)
        d.trade(1, 8, 100, price=5e-8, progress=33.0)
        rec.finish_all(T0 + 120)                       # followed for 120 s only
        rec.flush()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["price_sol_60s"], row["price_sol_120s"]), ("2e-08", "5e-08"))
        for c in (300, 900, 3600):
            self.assertEqual(row[f"price_sol_{c}s"], "", c)
        self.assertEqual((row["curve_progress_pct_1h"], row["tracked_seconds"]), ("", "120"))

    def test_curve_progress_and_graduation(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 100, progress=42.0)
        d.trade(1, 8, 3500, progress=88.5)
        rec.on_logs([complete_line(key(1), d.ts0[1] + 3550)], False, T0 + 3552, 900)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["curve_progress_pct_1h"], row["graduated"],
                          row["seconds_to_graduation"]), ("88.5", "yes", "3550"))

    def test_a_launch_that_never_graduated_says_no(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 10)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["graduated"], row["seconds_to_graduation"]), ("no", ""))

    def test_counts_and_volume(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 5, sol=1.5)
        d.trade(1, 8, 6, sol=0.5)
        d.trade(1, 7, 7, sol=1.0)
        d.trade(1, 9, 8, buy=False, sol=2.0)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["buys"], row["sells"], row["volume_sol"], row["buyers"], row["sellers"],
                          row["buyers_60s"]), ("3", "1", "5", "2", "1", "2"))

    def test_the_market_backdrop_columns(self):
        rec, d = self.run_one()
        rec.set_backdrop({"btc_change_1h_pct": 0.1, "btc_change_24h_pct": -0.7,
                          "eth_change_1h_pct": 0.02})
        d.create(1)
        d.trade(1, 7, 5)
        rec.set_backdrop({"btc_change_1h_pct": 9.0})   # later changes do not touch launches already created
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["btc_change_1h_pct"], row["btc_change_24h_pct"],
                          row["eth_change_1h_pct"], row["sol_change_1h_pct"]),
                         ("0.1", "-0.7", "0.02", ""))


# ---------------------------------------------------------------------
# which launches are written
# ---------------------------------------------------------------------

class SelectionTests(Base):
    def buyers(self, d, n, wallets, rel=10):
        d.create(n)
        for w in wallets:
            d.trade(n, w, rel)

    def test_the_buyers_in_60_seconds_rule(self):
        rec, d = self.run_one(sample_pct=0.0)
        self.buyers(d, 1, [11, 12])                    # two buyers: not enough
        self.buyers(d, 2, [11, 11, 12])                # three trades but two wallets
        self.buyers(d, 3, [11, 12, 13])                # three buyers: written
        d.create(4)
        for w in (11, 12):
            d.trade(4, w, 10)
        d.trade(4, 13, 61)                             # the third buyer came after 60 s
        d.create(5, dev=(1.0, 1e7))
        d.trade(5, 11, 10)
        d.trade(5, "creator", 20)                      # the creator does not count as a buyer
        d.trade(5, 12, 30)
        self.buyers(d, 6, [11, 12, 13, 14])
        d.finish()
        got = [r["token_address"] for r in rows(day_file(self.d))]
        self.assertEqual(got, [pf.b58encode(key(3)), pf.b58encode(key(6))])
        self.assertEqual([r["qualified"] for r in rows(day_file(self.d))], ["1", "1"])
        self.assertEqual(rec.days["2027-01-15"]["qualified"], 2)

    def test_a_launch_that_graduates_is_written_without_buyers(self):
        rec, d = self.run_one(sample_pct=0.0)
        d.create(1)
        rec.on_logs([complete_line(key(1), d.ts0[1] + 400)], False, T0 + 401, 900)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["graduated"], row["qualified"], row["sample"], row["buyers_60s"]),
                         ("yes", "1", "0", "0"))

    def test_the_sample_is_reproducible_and_about_two_percent(self):
        mints = [pf.b58encode(key(n)) for n in range(1, 4001)] + \
            [f"Mint{i:06d}pump" for i in range(40_000)]
        chosen = [m for m in mints if lr.in_sample(m, 2.0)]
        self.assertEqual(chosen, [m for m in mints if lr.in_sample(m, 2.0)])
        self.assertTrue(0.017 < len(chosen) / len(mints) < 0.023, len(chosen) / len(mints))
        self.assertTrue(set(chosen) <= {m for m in mints if lr.in_sample(m, 3.0)})   # nested
        self.assertEqual([m for m in mints if lr.in_sample(m, 0.0)], [])
        self.assertEqual(len([m for m in mints if lr.in_sample(m, 100.0)]), len(mints))

    def test_the_sample_does_not_depend_on_python_hash_randomisation(self):
        code = ("import sys; sys.path.insert(0, %r); from screener.launch_record import in_sample; "
                "print(''.join('1' if in_sample('Mint%%06dpump' %% i, 2.0) else '0' "
                "for i in range(5000)))" % HERE)
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=dict(os.environ, PYTHONHASHSEED=seed)).stdout
                for seed in ("0", "1", "12345")}
        self.assertEqual(len(outs), 1)
        self.assertIn("1", outs.pop())

    def test_sample_rows_are_marked_and_unqualified_unsampled_launches_are_not_written(self):
        rec, d = self.run_one(sample_pct=2.0)
        for n in range(1, 301):
            d.create(n)
            d.trade(n, 11, 10)                         # one buyer: never qualified
        d.finish()
        got = rows(day_file(self.d)) if os.path.exists(day_file(self.d)) else []
        expect = [pf.b58encode(key(n)) for n in range(1, 301) if lr.in_sample(pf.b58encode(key(n)), 2.0)]
        self.assertEqual([r["token_address"] for r in got], expect)
        self.assertTrue(all(r["sample"] == "1" and r["qualified"] == "0" for r in got))

    def test_a_launch_in_the_sample_and_qualified_is_marked_both(self):
        rec, d = self.run_one(sample_pct=100.0)
        self.buyers(d, 1, [11, 12, 13])
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["sample"], row["qualified"]), ("1", "1"))


class PacedCapTests(Base):
    def qualified(self, d, n, at):
        d.create(n, at=at)
        for w in (11, 12, 13):
            d.trade(n, w, 10)

    def test_the_cap_is_paced_through_the_day_so_early_hours_cannot_use_it_all(self):
        rec, d = self.run_one(sample_pct=0.0, max_rows_per_day=24)       # 1 row per hour of pace
        for n in range(1, 11):                                             # ten launches at 00:30
            rec.connected(T0 - 7.5 * 3600 + n - 1, "test")
            self.qualified(d, n, at=T0 - 7.5 * 3600 + n)                   # 00:30 UTC on the 15th
        rec.connected(T0 + 6 * 3600 - 1, "test")
        self.qualified(d, 20, at=T0 + 6 * 3600)                            # 14:00 UTC: budget for 15 rows
        rec.tick(T0 + 86400)
        rec.flush()
        got = rows(day_file(self.d))
        # hour 0 may use ceil(24 * 1 / 24) = 1 row: the first of the ten, the other nine are skipped
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["token_address"], pf.b58encode(key(1)))
        self.assertEqual(got[1]["token_address"], pf.b58encode(key(20)))   # later hours still have room
        self.assertEqual(rec.days["2027-01-15"]["skipped_by_cap"], 9)

    def test_quiet_hours_leave_room_for_busy_ones_but_the_day_total_never_passes_the_cap(self):
        rec, d = self.run_one(sample_pct=0.0, max_rows_per_day=24)
        rec.connected(T0 + 8.5 * 3600 - 1, "test")                         # 16:30 UTC, nothing before
        for n in range(1, 31):
            rec.connected(T0 + 8.5 * 3600 + n - 1, "test")
            self.qualified(d, n, at=T0 + 8.5 * 3600 + n)
        rec.tick(T0 + 86400)
        rec.flush()
        # by the end of hour 16 the pace allows ceil(24 * 17 / 24) = 17 rows
        self.assertEqual(len(rows(day_file(self.d))), 17)

    def test_pacing_can_be_turned_off(self):
        rec, d = self.run_one(sample_pct=0.0, max_rows_per_day=24, pace_cap_through_day=False)
        for n in range(1, 11):
            rec.connected(T0 - 7.5 * 3600 + n - 1, "test")
            self.qualified(d, n, at=T0 - 7.5 * 3600 + n)
        rec.tick(T0 + 86400)
        rec.flush()
        self.assertEqual(len(rows(day_file(self.d))), 10)

    def test_the_default_is_paced_and_the_real_config_says_so(self):
        self.assertTrue(CFG["launch_record"]["pace_cap_through_day"])


class CapTests(Base):
    def qualified(self, d, n):
        d.create(n)
        for w in (11, 12, 13):
            d.trade(n, w, 10)

    def test_past_the_daily_cap_qualified_rows_are_counted_not_written(self):
        rec, d = self.run_one(sample_pct=0.0, max_rows_per_day=3, pace_cap_through_day=False)
        for n in range(1, 6):
            self.qualified(d, n)
        d.finish()
        self.assertEqual(len(rows(day_file(self.d))), 3)
        self.assertEqual(rec.health(T0 + 4000)["rows_skipped_by_cap_today"], 2)
        self.assertEqual(rec.health(T0 + 4000)["rows_written_today"], 3)

    def test_the_sample_is_never_cut_by_the_cap(self):
        rec, d = self.run_one(sample_pct=100.0, max_rows_per_day=1)
        for n in range(1, 6):
            self.qualified(d, n)
        d.finish()
        self.assertEqual(len(rows(day_file(self.d))), 5)
        self.assertEqual(rec.health(T0 + 4000)["rows_skipped_by_cap_today"], 0)

    def test_the_cap_starts_again_the_next_day_and_survives_a_restart(self):
        rec, d = self.run_one(sample_pct=0.0, max_rows_per_day=2, pace_cap_through_day=False)
        for n in range(1, 4):
            self.qualified(d, n)
        d.finish()
        rec.write_health(T0 + 4000)
        again = make(self.d, sample_pct=0.0, max_rows_per_day=2, pace_cap_through_day=False)   # a restart
        again.connected(T0 + 4000, "test")
        d2 = Driver(again)
        self.qualified(d2, 10)                                         # created T0 (same day)
        again.tick(T0 + 4000 + lr.TRACK_SECONDS)
        again.flush()
        self.assertEqual(len(rows(day_file(self.d))), 2)               # still 2: the cap is kept
        self.assertEqual(again.health(T0 + 8000)["rows_skipped_by_cap_today"], 2)


# ---------------------------------------------------------------------
# the feed
# ---------------------------------------------------------------------

class GapTests(Base):
    def test_a_disconnect_in_the_first_minute_marks_the_launch_incomplete(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 10)
        rec.disconnected(T0 + 30)
        rec.connected(T0 + 45, "test")
        d.create(2, at=T0 + 600)                        # created well after the gap
        d.trade(2, 7, 10)
        d.finish(T0 + 600 + lr.TRACK_SECONDS + 5)
        got = {r["token_address"]: r for r in rows(day_file(self.d))}
        self.assertEqual(got[pf.b58encode(key(1))]["incomplete"], "1")
        self.assertEqual(got[pf.b58encode(key(2))]["incomplete"], "0")

    def test_a_gap_that_ended_before_the_launch_does_not_count_and_one_still_open_does(self):
        rec, d = self.run_one()
        rec.disconnected(T0 - 50)
        rec.connected(T0 - 10, "test")
        d.create(1)
        d.trade(1, 7, 10)
        rec.disconnected(T0 + 55)                       # down 5 s before the minute ends...
        d.finish()                                      # ...and still down when it is written
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["incomplete"], "1")

    def test_a_gap_after_the_first_minute_is_fine(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 7, 10)
        rec.disconnected(T0 + 70)
        rec.connected(T0 + 90, "test")
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["incomplete"], "0")

    def test_a_silent_stretch_on_a_live_connection_counts_as_a_gap(self):
        rec, d = self.run_one()
        d.create(1, at=T0)
        d.trade(1, 7, 10)                               # received at T0 + 10
        rec.on_logs([], False, T0 + 40)                 # then 30 s of silence on a live connection
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["incomplete"], "1")
        self.assertEqual(rec.days["2027-01-15"]["gap_seconds"], 30)

    def test_silence_before_the_first_message_of_a_launch_is_not_its_gap(self):
        rec, d = self.run_one()
        rec.on_logs([], False, T0 - 1)
        d.create(1, at=T0 + 50)                         # silence from T0-1 to T0+50, then it appears
        d.trade(1, 7, 10)
        d.finish(T0 + 50 + lr.TRACK_SECONDS + 5)
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["incomplete"], "0")

    def test_disconnects_and_gap_seconds_are_counted_for_the_health_file(self):
        rec, d = self.run_one()
        rec.disconnected(T0 + 10)
        rec.connected(T0 + 25, "other")
        rec.disconnected(T0 + 100, stopping=True)       # a stop is not a drop
        h = rec.health(T0 + 200)
        self.assertEqual((h["feed_disconnects_today"], h["gap_seconds_today"]), (1, 15))
        self.assertEqual(h["endpoint"], "other")


# ---------------------------------------------------------------------
# the daily files
# ---------------------------------------------------------------------

class FileTests(Base):
    def qualified(self, d, n, at=T0):
        d.create(n, at=at)
        for w in (11, 12, 13):
            d.trade(n, w, 10)

    def test_header_once_atomic_and_one_file_per_creation_day(self):
        rec, d = self.run_one(sample_pct=0.0)
        self.qualified(d, 1)
        late = T0 + 16 * 3600 - 10                      # 23:59:50 UTC on the 15th
        rec.connected(late - 5, "test")
        self.qualified(d, 2, at=late)                   # written an hour later, on the 16th
        rec.connected(T0 + 16 * 3600 + 15, "test")
        self.qualified(d, 3, at=T0 + 16 * 3600 + 20)    # 00:00:20 on the 16th
        rec.tick(T0 + 2 * 86400)
        rec.flush()
        folder = os.path.join(self.d, "launch-record")
        self.assertEqual(sorted(os.listdir(folder)), ["launches-2027-01-15.csv", "launches-2027-01-16.csv"])
        first = rows(day_file(self.d, "2027-01-15"))
        self.assertEqual([r["token_address"] for r in first], [pf.b58encode(key(1)), pf.b58encode(key(2))])
        self.assertEqual([r["token_address"] for r in rows(day_file(self.d, "2027-01-16"))],
                         [pf.b58encode(key(3))])             # each launch is filed by its creation day
        self.assertEqual(len(first), 2)
        for day in ("2027-01-15", "2027-01-16"):
            with open(day_file(self.d, day)) as fh:
                self.assertEqual(fh.read().count("created_at_utc,"), 1)    # one header
                fh.seek(0)
                self.assertEqual(next(csv.reader(fh)), lr.COLUMNS)

    def test_a_file_with_an_older_header_is_rewritten_keeping_its_rows(self):
        os.makedirs(os.path.join(self.d, "launch-record"))
        path = day_file(self.d)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["created_at_utc", "token_address", "old_column"])
            w.writerow(["2027-01-15T01:00:00Z", "OLDMINT", "keep"])
        rec, d = self.run_one(sample_pct=0.0)
        self.qualified(d, 1)
        d.finish()
        old, new = rows(path)
        self.assertEqual((old["token_address"], old["created_at_utc"], old["buyers_60s"]),
                         ("OLDMINT", "2027-01-15T01:00:00Z", ""))
        self.assertEqual(new["buyers_60s"], "3")
        self.assertNotIn("old_column", old)
        self.assertEqual([n for n in os.listdir(os.path.join(self.d, "launch-record"))
                          if n.endswith(".tmp")], [])

    def test_a_half_written_last_line_from_a_crash_is_cut_off(self):
        rec, d = self.run_one(sample_pct=0.0)
        self.qualified(d, 1)
        d.finish()
        with open(day_file(self.d), "a") as fh:
            fh.write("2027-01-15T09:00:00Z,half a ro")
        again = make(self.d, sample_pct=0.0)
        again.connected(T0 - 100, "test")
        d2 = Driver(again)
        self.qualified(d2, 2)
        again.tick(T0 + lr.TRACK_SECONDS + 5)
        again.flush()
        got = rows(day_file(self.d))
        self.assertEqual([r["token_address"] for r in got],
                         [pf.b58encode(key(1)), pf.b58encode(key(2))])

    def test_rows_are_written_in_batches_not_per_launch(self):
        rec, d = self.run_one(sample_pct=0.0)
        self.qualified(d, 1)
        rec.tick(T0 + lr.TRACK_SECONDS + 5)
        self.assertFalse(os.path.exists(day_file(self.d)))     # buffered until flush
        self.assertEqual(rec.flush(), 1)
        self.assertEqual(rec.flush(), 0)

    def test_the_header_has_every_asked_for_column(self):
        for name in ("created_at_utc", "created_hour_utc", "created_weekday", "dev_buy_pct",
                     "first_block_buyers", "bundle_suspect_buyers", "creator_prior_launches",
                     "creator_prior_dead", "copycat_name", "buyers", "sellers", "buys", "sells",
                     "volume_sol", "creator_sold_within_60s", "creator_sold_pct_1h",
                     "price_sol_5s", "price_sol_10s", "price_sol_20s", "price_sol_30s",
                     "price_sol_60s", "price_sol_120s", "price_sol_300s", "price_sol_900s",
                     "price_sol_3600s", "peak_price_sol", "seconds_to_peak",
                     "curve_progress_pct_1h", "graduated", "seconds_to_graduation",
                     "btc_change_1h_pct", "btc_change_24h_pct", "eth_change_1h_pct",
                     "sol_change_1h_pct", "incomplete", "sample"):
            self.assertIn(name, lr.COLUMNS)


# ---------------------------------------------------------------------
# the creator and copycat rules, memory limits, health
# ---------------------------------------------------------------------

class LedgerTests(Base):
    def test_copycat_names_and_the_creators_earlier_launches(self):
        rec, d = self.run_one()
        d.create(1, creator=1000, name="Pepe Cash", symbol="PEPEC")
        d.create(2, creator=2000, name="pepe cash", symbol="OTHER", at=T0 + 100)     # same name
        d.create(3, creator=3000, name="New", symbol="pepec", at=T0 + 200)           # same symbol
        d.create(4, creator=2000, name="Fresh", symbol="FRESH", at=T0 + 4000)        # 2000's 2nd
        d.create(5, creator=2000, name="Fresh2", symbol="FRESH2", at=T0 + 8000)      # 3rd
        for n in range(1, 6):
            d.trade(n, 11, 5)
        rec.tick(T0 + 8000 + lr.TRACK_SECONDS + 5)
        rec.flush()
        got = {r["symbol"]: r for r in rows(day_file(self.d))}
        self.assertEqual(got["PEPEC"]["copycat_name"], "0")
        self.assertEqual(got["OTHER"]["copycat_name"], "1")
        self.assertEqual(got["pepec"]["copycat_name"], "1")
        self.assertEqual((got["FRESH"]["creator_prior_launches"], got["FRESH"]["creator_prior_dead"]),
                         ("1", "1"))                    # launch 2: over an hour old, never graduated
        self.assertEqual((got["FRESH2"]["creator_prior_launches"], got["FRESH2"]["creator_prior_dead"]),
                         ("2", "2"))

    def test_an_earlier_launch_that_graduated_is_not_dead_and_a_young_one_is_not_dead_yet(self):
        rec, d = self.run_one()
        d.create(1, creator=2000)
        rec.on_logs([complete_line(key(1), T0 + 50)], False, T0 + 51, 1)
        d.create(2, creator=2000, at=T0 + 600)                          # 1 graduated, so no dead
        d.create(3, creator=2000, at=T0 + 700)                          # 2 is only ~2 minutes old
        for n in (1, 2, 3):
            d.trade(n, 11, 5)
        rec.tick(T0 + 700 + lr.TRACK_SECONDS + 5)
        rec.flush()
        got = {r["symbol"]: r for r in rows(day_file(self.d))}
        self.assertEqual((got["C2"]["creator_prior_launches"], got["C2"]["creator_prior_dead"]), ("1", "0"))
        self.assertEqual((got["C3"]["creator_prior_launches"], got["C3"]["creator_prior_dead"]), ("2", "0"))

    def test_the_ledger_survives_a_restart_and_forgets_old_entries(self):
        rec, d = self.run_one()
        d.create(1, creator=2000, name="Frog", symbol="FRG")
        rec.save()
        again = make(self.d)
        self.assertEqual(len(again.names), 2)
        self.assertEqual(sum(len(v) for v in again.creators.values()), 1)
        old = make(self.d)
        old.prune(T0 + 8 * 86400)                      # beyond the 7-day windows
        self.assertEqual((old.names, old.creators), ({}, {}))

    def test_a_broken_state_file_is_ignored(self):
        os.makedirs(os.path.join(self.d, "launch-record"))
        with open(os.path.join(self.d, "launch-record", "state.json"), "w") as fh:
            fh.write("{not json")
        rec = make(self.d)
        self.assertEqual((rec.names, rec.creators, rec.completed), ({}, {}, {}))

    def test_the_ledger_stays_under_its_cap(self):
        rec = make(self.d, max_ledger_entries=1000)
        for i in range(3000):
            rec.names[i] = T0 - i
            rec.creators[i] = [(T0 - i, i)]
        rec.prune(T0)
        self.assertLessEqual(len(rec.names) + len(rec.creators) + len(rec.completed), 1000)


class MemoryTests(Base):
    def test_launches_followed_are_capped_and_the_oldest_dropped(self):
        rec, d = self.run_one(max_tracked_launches=3)
        for n in range(1, 6):
            d.create(n, at=T0 + n)
        self.assertEqual(len(rec.launches), 3)
        self.assertNotIn(pf.b58encode(key(1)), rec.launches)
        self.assertEqual(rec.days["2027-01-15"]["dropped_over_cap"], 2)

    def test_wallet_sets_are_capped_and_flagged(self):
        rec, d = self.run_one(max_wallets_per_launch=5)
        d.create(1)
        for w in range(100, 120):
            d.trade(1, w, 5)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual((row["buyers"], row["wallets_capped"]), ("5", "1"))

    def test_trades_of_unknown_launches_and_failed_transactions_are_ignored(self):
        rec, d = self.run_one()
        d.ts0[9], d.creator[9] = T0, key(1000)
        d.trade(9, 11, 5)                               # launch 9 was never seen being created
        d.create(1)
        rec.on_logs([trade_line(key(1), key(11), True, 1.0, 1000, PRICE, T0)], True, T0 + 1, 1)
        d.finish()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["buys"], "0")

    def test_launches_still_followed_are_not_written_when_the_service_stops(self):
        rec, d = self.run_one()
        d.create(1)
        d.trade(1, 11, 5)
        rec.write_health(T0 + 100)
        self.assertEqual(rec.flush(), 0)
        again = make(self.d)                            # the next start
        self.assertEqual(again.days["2027-01-15"]["dropped_at_restart"], 1)
        self.assertEqual(again.health(T0 + 200)["dropped_at_last_restart"], 1)

    def test_a_test_run_can_finish_the_launches_early_and_says_how_long(self):
        rec, d = self.run_one()
        d.create(1)
        for w in (11, 12, 13):
            d.trade(1, w, 10)
        rec.finish_all(T0 + 120)
        rec.flush()
        (row,) = rows(day_file(self.d))
        self.assertEqual(row["tracked_seconds"], "120")


class HealthFileTests(Base):
    def test_health_json(self):
        rec, d = self.run_one(sample_pct=0.0)
        d.create(1)
        for w in (11, 12, 13):
            d.trade(1, w, 10)
        self.assertEqual(rec.health(T0 + 100)["launches_seen_last_hour"], 1)
        d.finish()
        data = rec.write_health(T0 + lr.TRACK_SECONDS + 100)
        with open(os.path.join(self.d, "launch-record", "health.json")) as fh:
            saved = json.load(fh)
        self.assertEqual(saved["rows_written_today"], 1)
        self.assertEqual(saved["launches_seen_last_hour"], 0)        # that hour has passed
        self.assertEqual(saved["max_rows_per_day"], 4000)
        self.assertEqual(saved["last_row"], "2027-01-15T09:00:05Z")
        self.assertEqual(saved["feed_silent_seconds"], lr.TRACK_SECONDS + 100 - 10)   # last message received at T0+10
        for key_ in ("feed_up", "in_flight", "feed_disconnects_today", "gap_seconds_today",
                     "rows_skipped_by_cap_today", "updated", "days"):
            self.assertIn(key_, data)

    def test_health_survives_a_restart(self):
        rec, d = self.run_one(sample_pct=0.0)
        d.create(1)
        for w in (11, 12, 13):
            d.trade(1, w, 10)
        d.finish()
        rec.write_health(T0 + 4000)
        again = make(self.d)
        self.assertEqual(again.health(T0 + 4000)["rows_written_today"], 1)
        self.assertIsNotNone(again.last_row)


# ---------------------------------------------------------------------
# the runner: the feed, the reconnects, the files
# ---------------------------------------------------------------------

class FakeWs:
    def __init__(self, messages, then=OSError("closed")):
        self.messages, self.then, self.sent = list(messages), then, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        self.sent.append(text)

    async def recv(self):
        if self.messages:
            return self.messages.pop(0)
        raise self.then


def notification(logs, slot=77, err=None):
    return json.dumps({"jsonrpc": "2.0", "method": "logsNotification", "params": {"result": {
        "context": {"slot": slot}, "value": {"signature": "s", "err": err, "logs": logs}}}})


class RunnerTests(Base):
    def cfg(self):
        cfg = copy.deepcopy(CFG)
        cfg["momentum"].update(reconnect_seconds=0.01, max_reconnect_seconds=0.05,
                               watchdog_seconds=1, stable_seconds=120)
        cfg["launch_record"]["sample_pct"] = 100.0
        return cfg

    def test_messages_reach_the_recorder_with_their_slot_and_a_read_only_subscription(self):
        async def go():
            ts = int(__import__("time").time())
            msgs = [notification([create_line(key(1), key(2), ts)], slot=500),
                    notification([trade_line(key(1), key(3), True, 1.0, 1000, PRICE, ts)], slot=500),
                    notification([], err={"InstructionError": 1}), "not json",
                    json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"message": "meh"}})]
            ws = FakeWs(msgs)
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=lambda *a, **k: ws)
            task = asyncio.create_task(runner.feed())
            await asyncio.sleep(0.2)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
            return runner, ws
        runner, ws = asyncio.run(go())
        self.assertEqual(json.loads(ws.sent[0])["method"], "logsSubscribe")
        w = runner.recorder.launches[pf.b58encode(key(1))]
        self.assertEqual((w.slot, len(w.first_block), w.buys), (500, 1, 1))
        self.assertEqual(runner.recorder.days[next(iter(runner.recorder.days))]["launches_seen"], 1)

    def test_a_dead_endpoint_moves_on_to_the_next_and_the_gap_is_recorded(self):
        calls = []

        def connect(url, **kw):
            calls.append(url)
            if len(calls) == 1:
                raise OSError("refused")
            return FakeWs([notification([])], then=OSError("dropped"))

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=connect)
            task = asyncio.create_task(runner.feed())
            await asyncio.sleep(0.4)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
            return runner
        runner = asyncio.run(go())
        urls = lrb.feed_urls(self.cfg()["momentum"])
        self.assertEqual(calls[:2], urls[:2])
        self.assertGreaterEqual(runner.recorder.days[next(iter(runner.recorder.days))]
                                .get("feed_disconnects", 0), 1)

    def test_an_endpoint_that_was_delivering_is_tried_again_first_one_that_was_silent_is_not(self):
        calls = []

        def connect(url, **kw):
            calls.append(url)
            n = len(calls)
            if n == 1:                                    # delivers a message, then drops
                return FakeWs([notification([])], then=OSError("dropped"))
            if n == 2:                                    # the same endpoint again: silent
                return FakeWs([], then=OSError("silent"))
            return FakeWs([notification([])], then=OSError("dropped"))

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=connect)
            task = asyncio.create_task(runner.feed())
            await asyncio.sleep(0.25)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
        asyncio.run(go())
        urls = lrb.feed_urls(self.cfg()["momentum"])
        self.assertEqual(calls[0], urls[0])
        self.assertEqual(calls[1], urls[0])                # it had delivered: the same one again
        self.assertEqual(calls[2], urls[1])                # then it delivered nothing: move on

    def test_a_refused_subscription_is_a_failed_connection(self):
        runner = lrb.RecordRunner(self.cfg(), self.d)
        with self.assertRaises(ConnectionError):
            runner.on_raw(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"message": "no"}}))

    def test_shutdown_writes_the_rows_health_and_ledger(self):
        runner = lrb.RecordRunner(self.cfg(), self.d, clock=lambda: T0)
        rec = runner.recorder
        rec.connected(T0 - 10, "x")
        d = Driver(rec)
        d.create(1)
        d.trade(1, 11, 5)
        rec.tick(T0 + lr.TRACK_SECONDS + 5)
        runner.shutdown()
        folder = os.path.join(self.d, "launch-record")
        self.assertEqual(sorted(os.listdir(folder)),
                         ["health.json", "launches-2027-01-15.csv", "state.json"])

    def test_the_backdrop_is_asked_through_its_own_cache_and_only_sets_columns(self):
        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d,
                                      backdrop=lambda: {"btc_change_1h_pct": 0.3})
            task = asyncio.create_task(runner.backdrop_task())
            await asyncio.sleep(0.1)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
            return runner
        runner = asyncio.run(go())
        self.assertEqual(runner.recorder.backdrop_values[0], 0.3)

    def test_a_failing_backdrop_never_stops_the_recorder(self):
        def boom():
            raise RuntimeError("down")

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, backdrop=boom)
            task = asyncio.create_task(runner.backdrop_task())
            await asyncio.sleep(0.1)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
        asyncio.run(go())

    def test_the_test_report_prints_the_numbers_asked_for(self):
        runner = lrb.RecordRunner(self.cfg(), self.d, clock=lambda: T0)
        rec = runner.recorder
        rec.connected(T0 - 10, "x")
        d = Driver(rec)
        for n in range(1, 11):
            d.create(n, at=T0 + n)
            for w in (11, 12, 13) if n <= 4 else (11,):
                d.trade(n, w, 10)
        rec.finish_all(T0 + 300)
        rec.flush()
        lines = []
        lrb.test_report(rec, 300, out=lines.append)
        text = "\n".join(lines)
        self.assertIn("Launches seen: 10", text)
        self.assertIn("Rows written", text)
        self.assertIn("rows a day: about", text)
        self.assertIn("min_buyers_60s =  3:", text)
        self.assertIn("<- now", text)
        self.assertIn("MB a day", text)
        self.assertIn("used the on-chain time", text)
        self.assertIn("A handful of real rows", text)


# ---------------------------------------------------------------------
# the launch bot runs it, no server step
# ---------------------------------------------------------------------

class WiringTests(Base):
    def test_the_recorder_runs_inside_the_launch_bot_only_while_stopped_and_enabled(self):
        cfg = copy.deepcopy(CFG)
        self.assertTrue(cfg["launch"]["stopped"] and cfg["launch_record"]["enabled"])
        self.assertIsNotNone(RealRunner(cfg, self.d).record)
        running = copy.deepcopy(cfg)
        running["launch"]["stopped"] = False
        self.assertIsNone(RealRunner(running, self.d).record)
        off = copy.deepcopy(cfg)
        off["launch_record"]["enabled"] = False
        self.assertIsNone(RealRunner(off, self.d).record)

    def test_the_test_mode_of_the_launch_bot_never_starts_the_recorder(self):
        seen = {}

        class FakeRunner:                               # what "launch_bot.py --test" builds
            def __init__(self, cfg_, folder):
                seen["record"] = RealRunner(cfg_, folder).record
                self.engine = unittest.mock.Mock(stats={}, traders={})
                self.kinds = {}

            async def main(self, stop_after=None):
                pass
        with unittest.mock.patch.object(launch_bot, "Runner", FakeRunner), \
                unittest.mock.patch("builtins.print"):
            self.assertEqual(launch_bot.main(["--test"]), 0)
        self.assertIn("record", seen)
        self.assertIsNone(seen["record"])

    def test_the_recorder_shares_the_launch_bots_stop_signal(self):
        runner = RealRunner(copy.deepcopy(CFG), self.d)
        self.assertIs(runner.record.stop, runner.stop)

    def test_changes_to_its_settings_restart_the_service_by_itself(self):
        self.assertIn("launch_record", launch_bot.CONFIG_SECTIONS)
        self.assertIn("momentum", launch_bot.CONFIG_SECTIONS)      # the feed endpoints it shares

    def test_the_recorder_never_trades_or_signs(self):
        for name in ("launch_record_bot.py", os.path.join("screener", "launch_record.py")):
            with open(os.path.join(HERE, name)) as fh:
                text = fh.read()
            for word in ("sendTransaction", "private_key", "Keypair", "secrets.", "subprocess"):
                self.assertNotIn(word, text, f"{name}: {word}")
        self.assertEqual(pf.ALLOWED_METHODS, {"logsSubscribe"})

    def test_the_results_folder_is_pushed_and_only_the_wanted_files_are_allowed(self):
        with open(os.path.join(HERE, "deploy", "push_results.sh")) as fh:
            self.assertIn("data/launch-record", fh.read())
        for path, allowed in (("data/launch-record/launches-2027-01-15.csv", True),
                              ("data/launch-record/health.json", True),
                              ("data/launch-record/state.json", False),
                              ("data/launch-record/launches-2027-01-15.csv.tmp", False),
                              ("data/backdrop_cache.json", False)):
            ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=HERE).returncode == 0
            self.assertEqual(not ignored, allowed, path)

    def test_the_config_section(self):
        c = CFG["launch_record"]
        self.assertEqual((c["min_buyers_60s"], c["sample_pct"], c["max_rows_per_day"]), (3, 2.0, 4000))
        self.assertEqual(c["checkpoints_seconds"], [5, 10, 20, 30, 60, 120, 300, 900, 3600])
        self.assertEqual(lr.columns(tuple(c["checkpoints_seconds"])), lr.COLUMNS)


# ---------------------------------------------------------------------
# the daily comparison's one line
# ---------------------------------------------------------------------

class HealthLineTests(HealthBase):
    NAME = "launch record: server"

    def lines(self, gh):
        """Like the base class, but with the real config (the tests' running() removes
        [launch] stopped, which is what switches this line on)."""
        from screener.health import health_lines
        text = "\n".join(health_lines(self.d, load_config(), HEALTH_NOW, gh))
        rows = {line.split(" | ")[0][2:]: line for line in text.splitlines()
                if line.startswith("| ") and not line.startswith("| Check")}
        return text, rows

    def good(self, **over):
        data = {"updated": (HEALTH_NOW - timedelta(minutes=20)).strftime(lr.ISO),
                "feed_up": True, "feed_silent_seconds": 3, "since_last_row_seconds": 600,
                "launches_seen_last_hour": 1450, "in_flight": 1400, "rows_written_today": 380,
                "rows_skipped_by_cap_today": 0, "max_rows_per_day": 4000,
                "feed_disconnects_today": 2, "gap_seconds_today": 40}
        data.update(over)
        self.write("launch-record/health.json", data)

    def test_a_healthy_recorder_is_one_ok_line_and_nothing_else_changes(self):
        gh = self.healthy()
        _, before = self.lines(gh)
        self.assertEqual(before[self.NAME].count(INFO), 1)       # not pushed yet: information only
        self.assertIn("no results pushed yet", before[self.NAME])
        self.good()
        text, after = self.lines(gh)
        self.assertIn(OK, after[self.NAME])
        self.assertIn("1450 launch(es) seen in the last hour", after[self.NAME])
        self.assertIn("380 row(s) written today", after[self.NAME])
        self.assertEqual({k: v for k, v in after.items() if k != self.NAME},
                         {k: v for k, v in before.items() if k != self.NAME})
        self.assertIn("**All checks OK.**", text)

    def test_warning_when_the_feed_was_silent_for_more_than_ten_minutes(self):
        gh = self.healthy()
        self.good(feed_silent_seconds=11 * 60)
        text, rows_ = self.lines(gh)
        self.assertIn(WARN, rows_[self.NAME])
        self.assertIn("silent for more than 10 min", rows_[self.NAME])
        self.assertIn("launch record:", text.split("problem(s) need a look")[1])
        self.good(feed_silent_seconds=9 * 60)
        self.assertIn(OK, self.lines(gh)[1][self.NAME])

    def test_warning_when_no_row_was_written_for_an_hour(self):
        gh = self.healthy()
        self.good(since_last_row_seconds=61 * 60)
        self.assertIn("no row written in the last 60 min", self.lines(gh)[1][self.NAME])
        self.good(since_last_row_seconds=None)
        row = self.lines(gh)[1][self.NAME]
        self.assertIn(WARN, row)
        self.assertIn("no row written yet", row)

    def test_warning_when_nothing_has_been_pushed_for_hours(self):
        gh = self.healthy()
        self.good(updated=(HEALTH_NOW - timedelta(hours=5)).strftime(lr.ISO))
        row = self.lines(gh)[1][self.NAME]
        self.assertIn(WARN, row)
        self.assertIn("older than 3 h", row)

    def test_rows_skipped_by_the_cap_are_said_plainly(self):
        gh = self.healthy()
        self.good(rows_skipped_by_cap_today=120, rows_written_today=4000)
        row = self.lines(gh)[1][self.NAME]
        self.assertIn("120 qualified row(s) SKIPPED by the daily cap of 4000", row)

    def test_no_line_when_the_recorder_is_off_or_the_strategy_is_not_stopped(self):
        gh = self.healthy()
        self.good()
        from screener.health import health_lines
        off = load_config()
        off["launch_record"]["enabled"] = False
        self.assertNotIn(self.NAME, "\n".join(health_lines(self.d, off, HEALTH_NOW, gh)))
        running = load_config()
        running["launch"]["stopped"] = False
        self.assertNotIn(self.NAME, "\n".join(health_lines(self.d, running, HEALTH_NOW, gh)))


# ---------------------------------------------------------------------
# the feed failure log and the health watchdog (fake time, fake connections)
# ---------------------------------------------------------------------

class ClosableWs(FakeWs):
    """FakeWs that the watchdog can close (a closed connection fails its next recv)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.closed = 0

    async def close(self):
        self.closed += 1
        self.then = OSError("closed by the watchdog")


def http_error(status, phrase, headers=None):
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    return InvalidStatus(Response(status, phrase, Headers(headers or {}), b""))


def closed_error(received=None, sent=None):
    from websockets.exceptions import ConnectionClosed
    from websockets.frames import Close
    return ConnectionClosed(Close(*received) if received else None,
                            Close(*sent) if sent else None)


class FeedFailureLogTests(Base):
    cfg = RunnerTests.cfg

    def failures(self, errors):
        """Run the feed through these connection failures; the warnings it logged."""
        calls = []

        def connect(url, **kw):
            calls.append(url)
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return FakeWs([], then=OSError("end"))

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=connect)
            task = asyncio.create_task(runner.feed())
            while len(calls) <= len(errors):
                await asyncio.sleep(0.01)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
        with self.assertLogs("launch_record", level="WARNING") as logged:
            asyncio.run(go())
        return [r.getMessage() for r in logged.records if "feed disconnected" in r.getMessage()]

    def test_the_http_status_of_a_refused_handshake_is_logged(self):
        (line,) = self.failures([http_error(502, "Bad Gateway")])[:1]
        self.assertIn("HTTP 502 Bad Gateway", line)
        self.assertIn("api.mainnet-beta.solana.com", line)

    def test_rate_limiting_is_visible(self):
        (line,) = self.failures([http_error(429, "Too Many Requests", {"Retry-After": "30"})])[:1]
        self.assertIn("HTTP 429 Too Many Requests, Retry-After 30", line)

    def test_close_codes_are_logged(self):
        lines = self.failures([closed_error((1011, "keepalive ping timeout")),
                               closed_error(None, (1011, "")), closed_error((1013, ""))])
        self.assertIn("closed by the server with code 1011 (keepalive ping timeout)", lines[0])
        self.assertIn("closed without a close frame (code 1006); we sent code 1011", lines[1])
        self.assertIn("closed by the server with code 1013", lines[2])

    def test_os_errors_and_timeouts_are_logged(self):
        lines = self.failures([ConnectionRefusedError(111, "Connection refused"),
                               asyncio.TimeoutError()])
        self.assertIn("ConnectionRefusedError errno 111", lines[0])
        self.assertIn("timeout", lines[1])

    def test_one_line_per_failure(self):
        errors = [http_error(502, "Bad Gateway"), http_error(503, "Service Unavailable"),
                  http_error(502, "Bad Gateway")]
        lines = self.failures(errors)
        # one line for each of the three failures (then one for the fake feed ending)
        self.assertEqual(len(lines), 4)
        self.assertEqual(["502" in x for x in lines[:3]], [True, False, True])
        self.assertIn("HTTP 503 Service Unavailable", lines[1])

    def test_a_dropped_working_connection_is_logged_with_its_close_code(self):
        calls = []

        def connect(url, **kw):
            calls.append(url)
            return FakeWs([notification([])], then=closed_error((1006, "")))

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=connect)
            task = asyncio.create_task(runner.feed())
            await asyncio.sleep(0.1)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
        with self.assertLogs("launch_record", level="WARNING") as logged:
            asyncio.run(go())
        self.assertIn("closed by the server with code 1006",
                      "\n".join(r.getMessage() for r in logged.records))


class WatchdogTests(Base):
    cfg = RunnerTests.cfg

    def runner(self, now):
        """A runner whose clock is now[0]; its health was saved at now[0] when it was made."""
        runner = lrb.RecordRunner(self.cfg(), self.d, clock=lambda: now[0])
        runner.exit_fn = unittest.mock.Mock()
        return runner

    def test_nothing_happens_while_health_is_fresh(self):
        now = [T0]

        async def go():
            runner = self.runner(now)
            now[0] = T0 + 599
            return await runner.check_watchdog()
        self.assertIsNone(asyncio.run(go()))

    def test_after_10_minutes_the_connection_is_restarted_once(self):
        now = [T0]

        async def go():
            runner = self.runner(now)
            runner.ws = ClosableWs([])
            now[0] = T0 + 600
            with self.assertLogs("launch_record", level="ERROR") as logged:
                first = await runner.check_watchdog()
            now[0] = T0 + 700
            second = await runner.check_watchdog()                # no second restart
            return runner, first, second, logged
        runner, first, second, logged = asyncio.run(go())
        self.assertEqual((first, second), ("restart", "restart"))
        self.assertEqual(runner.ws.closed, 1)
        self.assertEqual(runner.feed_restarts, 1)
        self.assertFalse(runner.stop.is_set())
        self.assertEqual(len(logged.records), 1)
        self.assertIn("restarting the feed connection", logged.output[0])

    def test_a_save_resets_the_watchdog(self):
        now = [T0]

        async def go():
            runner = self.runner(now)
            runner.ws = ClosableWs([])
            now[0] = T0 + 650
            with self.assertLogs("launch_record", level="ERROR"):
                await runner.check_watchdog()
            runner.health_saved = now[0]                          # a save went through
            self.assertIsNone(await runner.check_watchdog())
            self.assertEqual(runner.watchdog_stage, 0)
            now[0] += 601                                         # stalled again
            with self.assertLogs("launch_record", level="ERROR"):
                await runner.check_watchdog()
            return runner
        runner = asyncio.run(go())
        self.assertEqual(runner.ws.closed, 2)

    def test_after_20_minutes_the_service_is_stopped_for_systemd(self):
        now = [T0]
        with unittest.mock.patch.object(lrb, "HARD_EXIT_SECONDS", 0.05):
            async def go():
                runner = self.runner(now)
                runner.ws = ClosableWs([])
                now[0] = T0 + 650
                with self.assertLogs("launch_record", level="ERROR"):
                    await runner.check_watchdog()
                now[0] = T0 + 1200
                with self.assertLogs("launch_record", level="ERROR") as logged:
                    result = await runner.check_watchdog()
                    again = await runner.check_watchdog()         # logged once only
                self.assertEqual(len(logged.records), 1)
                self.assertIn("stopping the service so systemd starts it again", logged.output[0])
                before = runner.exit_fn.call_count
                await asyncio.sleep(0.2)                          # the service is still running
                return runner, result, again, before
            runner, result, again, before = asyncio.run(go())
        self.assertEqual((result, again), ("exit", "exit"))
        self.assertTrue(runner.stop.is_set())
        self.assertTrue(runner.exit_requested)
        self.assertEqual(before, 0)
        runner.exit_fn.assert_called_once_with(1)                 # the hard exit, as a last resort

    def test_not_connected_is_logged_not_a_crash(self):
        now = [T0]

        async def go():
            runner = self.runner(now)
            now[0] = T0 + 600
            with self.assertLogs("launch_record", level="ERROR") as logged:
                result = await runner.check_watchdog()
            return result, logged
        result, logged = asyncio.run(go())
        self.assertEqual(result, "restart")
        self.assertIn("not connected", "\n".join(logged.output))

    def test_the_restart_makes_the_feed_reconnect(self):
        now = [T0]
        wss = []

        class StuckWs(ClosableWs):
            """A connection that delivers nothing until it is closed."""

            def __init__(self):
                super().__init__([])
                self.gate = asyncio.Event()

            async def recv(self):
                await self.gate.wait()
                raise closed_error((1006, ""))

            async def close(self):
                self.closed += 1
                self.gate.set()

        def connect(url, **kw):
            wss.append(StuckWs())
            return wss[-1]

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=connect, clock=lambda: now[0])
            runner.exit_fn = unittest.mock.Mock()
            task = asyncio.create_task(runner.feed())
            await asyncio.sleep(0.05)
            self.assertEqual(len(wss), 1)
            now[0] = T0 + 600
            with self.assertLogs("launch_record", level="ERROR"):
                await runner.check_watchdog()
            await asyncio.sleep(0.1)
            runner.stop.set()
            wss[-1].gate.set()
            await asyncio.wait_for(task, 2)
        asyncio.run(go())
        self.assertEqual(wss[0].closed, 1)
        self.assertGreaterEqual(len(wss), 2)                      # it reconnected

    def test_the_clock_task_marks_each_save(self):
        ticks = [T0]

        def clock():
            ticks[0] += 31                                         # every look is 31 s later
            return ticks[0]

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, clock=clock)
            first = runner.health_saved
            task = asyncio.create_task(runner.clock_task())
            await asyncio.sleep(1.2)
            runner.stop.set()
            await asyncio.wait_for(task, 2)
            return runner, first
        runner, first = asyncio.run(go())
        self.assertGreater(runner.health_saved, first)
        self.assertTrue(os.path.exists(os.path.join(self.d, "launch-record", "health.json")))

    def test_the_watchdog_task_runs_beside_the_others(self):
        runner = lrb.RecordRunner(self.cfg(), self.d)
        coros = runner.tasks()
        self.assertEqual(len(coros), 4)
        self.assertIn("watchdog_task", [c.cr_code.co_name for c in coros])
        for c in coros:
            c.close()

    def test_the_watchdog_task_polls_and_acts(self):
        now = [T0]

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, clock=lambda: now[0])
            runner.exit_fn = unittest.mock.Mock()
            runner.ws = ClosableWs([])
            now[0] = T0 + 601
            with unittest.mock.patch.object(lrb, "WATCHDOG_POLL_SECONDS", 0.01), \
                    self.assertLogs("launch_record", level="ERROR"):
                task = asyncio.create_task(runner.watchdog_task())
                await asyncio.sleep(0.1)
                runner.stop.set()
                await asyncio.wait_for(task, 2)
            return runner
        runner = asyncio.run(go())
        self.assertEqual(runner.ws.closed, 1)


# ---------------------------------------------------------------------
# the data-change monitor: what the feed sent per UTC hour
# ---------------------------------------------------------------------

MIDNIGHT = T0 + 16 * 3600              # 2027-01-16 00:00:00 UTC (T0 is 2027-01-15 08:00)
UNKNOWN_EVENT = line(bytes.fromhex("0102030405060708") + bytes(120))


def hour_key(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H")


class FeedCountTests(Base):
    def recorder(self, clock=None, folder=None):
        return lr.LaunchRecorder(copy.deepcopy(CFG), folder or self.d,
                                 clock=clock or (lambda: T0))

    def counts(self, rec, t=T0):
        return rec.feed_counts.get(hour_key(t), {})

    def test_normal_messages_are_counted_by_kind(self):
        rec = self.recorder()
        mint, who = key(1), key(1000)
        rec.on_logs([create_line(mint, who, T0)], False, T0, 5)
        rec.on_logs([create_line(key(2), who, T0), trade_line(key(2), who, True, 1.0, 1000, PRICE, T0)],
                    False, T0 + 1, 5)
        rec.on_logs([trade_line(mint, key(3), True, 1.0, 1000, PRICE, T0)], False, T0 + 2, 6)
        rec.on_logs([trade_line(mint, key(4), False, 1.0, 1000, PRICE, T0)], False, T0 + 3, 6)
        rec.on_logs(["Program 6EF8 invoke [1]"], False, T0 + 4, 7)        # no event at all
        self.assertEqual(self.counts(rec), {"messages": 5, "creations": 2, "trades": 3})
        self.assertEqual(rec.health(T0 + 5)["feed_counts"][hour_key(T0)],
                         {"messages": 5, "creations": 2, "trades": 3})

    def test_an_undecodable_message_is_counted_not_recorded(self):
        rec = self.recorder()
        rec.on_logs([UNKNOWN_EVENT], False, T0, 5)                        # unknown event type
        rec.on_logs(["Program data: !!!"], False, T0 + 1, 5)               # not base64 at all
        rec.on_logs(["Program data: " + base64.b64encode(
            pf.TRADE_EVENT + bytes(20)).decode()], False, T0 + 2, 5)       # known type, cut short
        rec.on_logs([create_line(key(1), key(2), T0), UNKNOWN_EVENT], False, T0 + 3, 5)  # fine
        rec.on_logs([UNKNOWN_EVENT], True, T0 + 4, 5)                      # a failed transaction
        self.assertEqual(self.counts(rec),
                         {"messages": 5, "undecoded": 3, "creations": 1})
        self.assertEqual(len(rec.launches), 1)

    def test_a_counting_error_never_stops_the_recording(self):
        rec = self.recorder()
        with unittest.mock.patch.object(lr, "utc", side_effect=RuntimeError("boom")):
            rec._feed_count(T0, "messages")                                # never raises
            rec._count_feed_events(T0, [UNKNOWN_EVENT], [])
        rec.on_logs([create_line(key(1), key(2), T0)], False, T0, 1)       # recording as normal
        self.assertEqual(len(rec.launches), 1)

    def test_a_drop_in_creations_shows_in_the_counts(self):
        rec = self.recorder()
        for hour in range(5):
            for n in range(30 if hour < 4 else 6):
                rec.on_logs([create_line(key(100 * hour + n), key(7), T0 + hour * 3600)],
                            False, T0 + hour * 3600 + n, 1)
        data = rec.health(T0 + 5 * 3600)["feed_counts"]
        self.assertEqual([data[hour_key(T0 + h * 3600)]["creations"] for h in range(5)],
                         [30, 30, 30, 30, 6])

    def test_a_clean_reset_at_midnight_utc(self):
        now = [MIDNIGHT - 1]
        rec = self.recorder(clock=lambda: now[0])
        rec.on_logs([create_line(key(1), key(9), MIDNIGHT - 1)], False, MIDNIGHT - 1, 1)
        now[0] = MIDNIGHT
        rec.on_logs([create_line(key(2), key(9), MIDNIGHT)], False, MIDNIGHT, 1)
        rec.on_logs([trade_line(key(2), key(8), True, 1.0, 1000, PRICE, MIDNIGHT)], False,
                    MIDNIGHT + 1, 1)
        late, early = hour_key(MIDNIGHT - 1), hour_key(MIDNIGHT)
        self.assertEqual((late[:10], early[:10]), ("2027-01-15", "2027-01-16"))
        self.assertEqual(rec.feed_counts[late], {"messages": 1, "creations": 1})
        self.assertEqual(rec.feed_counts[early], {"messages": 2, "creations": 1, "trades": 1})
        # an hour with no message has no entry (so it starts from zero, not from the old hour)
        self.assertNotIn(hour_key(MIDNIGHT + 3600), rec.feed_counts)
        # only the last 24 hours are in health.json; older hours are forgotten
        shown = rec.health(MIDNIGHT + 24 * 3600 + 1800)["feed_counts"]
        self.assertNotIn(late, shown)
        self.assertIn(early, shown)
        for h in range(60):                          # a long run: the old hours are forgotten
            rec.feed_counts[hour_key(MIDNIGHT + 3600 * (2 + h))] = {"messages": 1}
        rec.prune(MIDNIGHT + 62 * 3600)
        self.assertEqual(len(rec.feed_counts), lr.FEED_HOURS_KEPT)
        self.assertNotIn(early, rec.feed_counts)

    def test_the_counts_survive_a_restart(self):
        rec = self.recorder()
        rec.on_logs([create_line(key(1), key(9), T0)], False, T0, 1)
        rec.write_health(T0 + 5)
        again = self.recorder()
        self.assertEqual(self.counts(again), {"messages": 1, "creations": 1})


class FeedFormatLineTests(HealthBase):
    NAME = "launch record: feed format"
    lines = HealthLineTests.lines

    def hours(self, creations, last=None, undecoded=0, messages=None, current=None):
        """feed_counts for the 24 full hours before the file was saved: `creations` per hour,
        the last full hour with `last` creations; `current` for the hour in progress."""
        saved = HEALTH_NOW - timedelta(minutes=20)
        top = saved.replace(minute=0, second=0, microsecond=0)
        out = {}
        for i in range(1, 25):
            key_ = (top - timedelta(hours=i)).strftime("%Y-%m-%dT%H")
            out[key_] = {"creations": creations, "trades": creations * 20,
                         "messages": creations * 30, "undecoded": 0}
        newest = (top - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
        out[newest] = {"creations": creations if last is None else last,
                       "trades": 6000, "messages": messages or 9000, "undecoded": undecoded}
        if current is not None:
            out[top.strftime("%Y-%m-%dT%H")] = {"creations": current, "messages": 10}
        return out

    def write_counts(self, counts):
        data = {"updated": (HEALTH_NOW - timedelta(minutes=20)).strftime(lr.ISO),
                "feed_counts": counts}
        self.write("launch-record/health.json", data)

    def row(self, counts):
        gh = self.healthy()
        self.write_counts(counts)
        return self.lines(gh)[1][self.NAME]

    def test_normal_counts_are_ok(self):
        row = self.row(self.hours(300))
        self.assertIn(OK, row)
        self.assertIn("creations per hour median 300, lowest 300", row)
        self.assertIn("trades per hour median", row)
        self.assertIn("0 of 9000 message(s) undecoded", row)

    def test_warning_when_creations_fall_below_half_the_median(self):
        row = self.row(self.hours(300, last=149))
        self.assertIn(WARN, row)
        self.assertIn("below 50% of the 24 h median", row)
        self.assertIn(OK, self.row(self.hours(300, last=150)))            # exactly half is fine
        self.assertIn("lowest 149", self.row(self.hours(300, last=149)))

    def test_the_hour_in_progress_is_not_judged(self):
        self.assertIn(OK, self.row(self.hours(300, current=2)))

    def test_warning_when_more_than_five_percent_cannot_be_decoded(self):
        row = self.row(self.hours(300, undecoded=451, messages=9000))     # 5.01%
        self.assertIn(WARN, row)
        self.assertIn("451 of 9000 message(s) in the last full hour could not be decoded", row)
        self.assertIn(OK, self.row(self.hours(300, undecoded=450, messages=9000)))   # 5.0%

    def test_a_silent_last_hour_is_a_warning(self):
        counts = self.hours(300)
        del counts[max(k for k in counts if counts[k]["messages"] == 9000)]
        self.assertIn(WARN, self.row(counts))

    def test_too_little_history_never_warns_on_the_median(self):
        counts = self.hours(300, last=1)
        counts = dict(sorted(counts.items())[-2:])
        self.assertIn(OK, self.row(counts))

    def test_no_counts_yet_is_information(self):
        gh = self.healthy()
        self.write("launch-record/health.json",
                   {"updated": (HEALTH_NOW - timedelta(minutes=20)).strftime(lr.ISO)})
        row = self.lines(gh)[1][self.NAME]
        self.assertIn(INFO, row)
        self.assertIn("no feed counts pushed yet", row)


# ---------------------------------------------------------------------
# how each feed endpoint behaves over the last 24 hours (fake connections, fake time)
# ---------------------------------------------------------------------

A_HOST, B_HOST = "api.mainnet-beta.solana.com", "solana-rpc.publicnode.com"


class TimedWs(FakeWs):
    """Delivers its messages, then lets `seconds` pass on the fake clock and fails."""

    def __init__(self, now, seconds, then, messages=(notification([]),)):
        super().__init__(messages, then=then)
        self.now, self.seconds = now, seconds

    async def recv(self):
        if not self.messages:
            self.now[0] += self.seconds
        return await super().recv()


class EndpointStatsTests(Base):
    cfg = RunnerTests.cfg

    def run_feed(self, script, now=None, stop_when_done=True):
        """script: one item per connection attempt: an exception to raise from the connection
        attempt, or (seconds, error) for a connection that works for a while and then fails.
        Returns the runner (its recorder holds the statistics)."""
        now = now if now is not None else [T0]
        calls, holder = [], []

        def connect(url, **kw):
            calls.append(url)
            if len(calls) > len(script):         # the script is over: stop the feed
                holder[0].stop.set()
                raise OSError("script over")
            item = script[len(calls) - 1]
            if isinstance(item, BaseException):
                raise item
            seconds, error = item
            return TimedWs(now, seconds, error)

        async def go():
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=connect, clock=lambda: now[0])
            holder.append(runner)
            await asyncio.wait_for(runner.feed(), 5)
            return runner
        with self.assertLogs("launch_record", level="WARNING"):
            runner = asyncio.run(go())
        return runner

    def endpoints(self, runner, t=T0 + 1000):
        return runner.recorder.health(t)["endpoints"]

    def test_attempts_successes_top_failure_and_average_time_up(self):
        script = [http_error(502, "Bad Gateway"),                    # A: refused
                  (120, closed_error((1006, ""))),                   # B: up 120 s, then dropped
                  (60, closed_error((1006, ""))),                    # B again: up 60 s
                  (30, closed_error((1013, "try again later")))]      # B again: up 30 s
        stats = self.endpoints(self.run_feed(script))
        a, b = stats[A_HOST], stats[B_HOST]
        self.assertEqual((a["attempts"], a["successes"], a["failures"]), (1, 0, 1))
        self.assertEqual(a["top_failure"], "HTTP 502 Bad Gateway")
        self.assertIsNone(a["avg_connected_seconds"])
        self.assertEqual((b["attempts"], b["successes"]), (3, 3))
        self.assertEqual(b["top_failure"], "closed by the server with code 1006")
        self.assertEqual((b["top_failure_count"], b["failures"]), (2, 3))
        self.assertEqual(b["ended_connections"], 3)
        self.assertEqual(b["avg_connected_seconds"], 70.0)

    def test_the_most_common_failure_wins(self):
        script = [http_error(502, "Bad Gateway"), http_error(429, "Too Many Requests"),
                  http_error(502, "Bad Gateway"), http_error(502, "Bad Gateway"),
                  http_error(429, "Too Many Requests")]
        stats = self.endpoints(self.run_feed(script))
        total = {k: sum(e["failures"] for e in stats.values()) for k in ("failures",)}
        self.assertEqual(total["failures"], len(script))
        tops = {e["top_failure"] for e in stats.values()}
        self.assertTrue(tops <= {"HTTP 502 Bad Gateway", "HTTP 429 Too Many Requests"})
        self.assertIn("HTTP 502 Bad Gateway", tops)

    def test_a_connection_ended_by_a_stop_counts_its_time_but_no_failure(self):
        now = [T0]

        async def go():
            ws = TimedWs(now, 0, OSError("never"), messages=())

            async def quiet():
                await asyncio.sleep(10)
            ws.recv = quiet
            runner = lrb.RecordRunner(self.cfg(), self.d, connect=lambda *a, **k: ws,
                                      clock=lambda: now[0])
            task = asyncio.create_task(runner.feed())
            await asyncio.sleep(0.05)
            now[0] += 45
            runner.stop.set()
            await asyncio.wait_for(task, 2)
            return runner
        runner = asyncio.run(go())
        a = self.endpoints(runner)[A_HOST]
        self.assertEqual((a["attempts"], a["successes"], a["failures"]), (1, 1, 0))
        self.assertIsNone(a["top_failure"])
        self.assertEqual(a["avg_connected_seconds"], 45.0)

    def test_only_the_last_24_hours_count_and_hours_roll_over(self):
        rec = lr.LaunchRecorder(copy.deepcopy(CFG), self.d, clock=lambda: T0)
        rec.endpoint_attempt(T0, A_HOST, False, "HTTP 502 Bad Gateway")
        rec.endpoint_attempt(T0 + 25 * 3600, A_HOST, True)
        rec.endpoint_ended(T0 + 25 * 3600 + 100, A_HOST, 100, "closed by the server with code 1006")
        stats = rec._endpoints_24h(T0 + 26 * 3600)
        self.assertEqual(stats[A_HOST]["attempts"], 1)               # the first is 26 h old
        self.assertEqual(stats[A_HOST]["top_failure"], "closed by the server with code 1006")
        self.assertEqual(rec._endpoints_24h(T0 + 3600)[A_HOST]["attempts"], 2)
        for h in range(40):
            rec.endpoint_attempt(T0 + (30 + h) * 3600, B_HOST, True)
        rec.prune(T0 + 80 * 3600)
        self.assertEqual(len(rec.endpoint_hours), lr.FEED_HOURS_KEPT)

    def test_the_statistics_survive_a_restart(self):
        rec = lr.LaunchRecorder(copy.deepcopy(CFG), self.d, clock=lambda: T0)
        rec.endpoint_attempt(T0, B_HOST, True)
        rec.endpoint_ended(T0 + 50, B_HOST, 50, None)
        rec.write_health(T0 + 60)
        again = lr.LaunchRecorder(copy.deepcopy(CFG), self.d, clock=lambda: T0 + 70)
        self.assertEqual(again.health(T0 + 70)["endpoints"][B_HOST]["avg_connected_seconds"], 50.0)

    def test_counting_errors_never_stop_the_feed(self):
        with unittest.mock.patch.object(lr, "utc", side_effect=RuntimeError("boom")):
            rec = lr.LaunchRecorder.__new__(lr.LaunchRecorder)
            rec.endpoint_hours = {}
            rec.endpoint_attempt(T0, A_HOST, True)                     # never raises
            rec.endpoint_ended(T0, A_HOST, 5, "x")

    def test_endpoints_and_timeouts_are_unchanged(self):
        m = load_config()["momentum"]
        self.assertEqual(lrb.feed_urls(m), list(m["ws_urls"]))
        self.assertEqual([lrb.host(u) for u in lrb.feed_urls(m)][:2], [A_HOST, B_HOST])


class EndpointLineTests(HealthBase):
    NAME = "launch record: endpoints"
    lines = HealthLineTests.lines

    def write_endpoints(self, endpoints):
        self.write("launch-record/health.json",
                   {"updated": (HEALTH_NOW - timedelta(minutes=20)).strftime(lr.ISO),
                    "endpoints": endpoints})

    def test_one_line_with_every_endpoint(self):
        gh = self.healthy()
        self.write_endpoints({
            A_HOST: {"attempts": 340, "successes": 120, "failures": 330,
                     "top_failure": "HTTP 502 Bad Gateway", "top_failure_count": 200,
                     "avg_connected_seconds": 148.5, "ended_connections": 119},
            B_HOST: {"attempts": 4, "successes": 4, "failures": 0, "top_failure": None,
                     "top_failure_count": 0, "avg_connected_seconds": None,
                     "ended_connections": 0}})
        text, rows_ = self.lines(gh)
        row = rows_[self.NAME]
        self.assertIn(OK, row)
        self.assertIn(f"{A_HOST}: 120 of 340 attempt(s) connected, most common failure "
                      "HTTP 502 Bad Gateway (200 of 330), connections lasted 148.5 s on average", row)
        self.assertIn(f"{B_HOST}: 4 of 4 attempt(s) connected, no failures, no connection has "
                      "ended yet", row)
        self.assertNotIn(WARN, row)                                   # information, never a warning
        self.assertNotIn("launch record: launch record", text)

    def test_no_statistics_yet_is_information(self):
        gh = self.healthy()
        self.write("launch-record/health.json",
                   {"updated": (HEALTH_NOW - timedelta(minutes=20)).strftime(lr.ISO)})
        row = self.lines(gh)[1][self.NAME]
        self.assertIn(INFO, row)
        self.assertIn("no endpoint statistics pushed yet", row)

    def test_a_pipe_in_a_failure_cannot_break_the_table(self):
        gh = self.healthy()
        self.write_endpoints({A_HOST: {"attempts": 1, "successes": 0, "failures": 1,
                                       "top_failure": "weird | text", "top_failure_count": 1,
                                       "avg_connected_seconds": None, "ended_connections": 0}})
        row = self.lines(gh)[1][self.NAME]
        self.assertIn("weird / text", row)


if __name__ == "__main__":
    unittest.main()
