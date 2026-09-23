import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_bot.backtest import run_backtest
from trading_bot.broker import CCXTBroker, PaperBroker
from trading_bot.cli import main
from trading_bot.data import ExchangeFeed, generate_synthetic, load_csv, save_csv
from trading_bot.live import run_loop
from trading_bot.models import Bar, Side, Signal
from trading_bot.risk import RiskConfig, RiskManager
from trading_bot.strategies import RSIMeanReversion, SMACrossover, build_strategy, rsi, sma
from trading_bot.trader import Trader

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bars_from_closes(closes, opens=None):
    opens = opens or closes
    return [
        Bar(T0 + timedelta(hours=i), o, max(o, c), min(o, c), c, 1.0)
        for i, (o, c) in enumerate(zip(opens, closes))
    ]


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sma([1, 2, 3, 4], 2), 3.5)
        with self.assertRaises(ValueError):
            sma([1], 2)

    def test_rsi_bounds(self):
        self.assertEqual(rsi([1, 2, 3, 4], 3), 100.0)
        self.assertEqual(rsi([4, 3, 2, 1], 3), 0.0)
        self.assertEqual(rsi([1, 1, 1, 1], 3), 50.0)
        self.assertAlmostEqual(rsi([1, 2, 1, 2], 3), 66.6666, places=3)


class StrategyTests(unittest.TestCase):
    def test_sma_crossover_signals(self):
        s = SMACrossover(fast=2, slow=4)
        # Flat then a jump: fast crosses above slow on the last bar.
        self.assertIs(s.generate_signal(bars_from_closes([10, 10, 10, 10, 20])), Signal.BUY)
        self.assertIs(s.generate_signal(bars_from_closes([10, 10, 10, 10, 5])), Signal.SELL)
        self.assertIs(s.generate_signal(bars_from_closes([10, 10, 10, 10, 10])), Signal.HOLD)
        self.assertIs(s.generate_signal(bars_from_closes([10, 20])), Signal.HOLD)

    def test_rsi_strategy_signals(self):
        s = RSIMeanReversion(period=3, oversold=30, overbought=70)
        self.assertIs(s.generate_signal(bars_from_closes([4, 3, 2, 1])), Signal.BUY)
        self.assertIs(s.generate_signal(bars_from_closes([1, 2, 3, 4])), Signal.SELL)

    def test_build_strategy(self):
        self.assertEqual(build_strategy("sma_crossover", fast=3, slow=5).slow, 5)
        with self.assertRaises(ValueError):
            build_strategy("nope")
        with self.assertRaises(ValueError):
            SMACrossover(fast=5, slow=3)


class BrokerTests(unittest.TestCase):
    def test_round_trip_charges_fees_and_slippage(self):
        b = PaperBroker(cash=1000, fee_rate=0.01, slippage_pct=0.0)
        b.buy(5, 100, T0, "test")
        self.assertAlmostEqual(b.cash, 1000 - 500 - 5)
        self.assertEqual(b.position, 5)
        self.assertEqual(b.entry_price, 100)
        b.sell(5, 110, T0, "test")
        self.assertAlmostEqual(b.cash, 495 + 550 - 5.5)
        self.assertEqual(b.position, 0)
        self.assertIsNone(b.entry_price)

    def test_buy_never_overspends(self):
        b = PaperBroker(cash=1000, fee_rate=0.001, slippage_pct=0.001)
        b.buy(1_000_000, 100, T0, "test")
        self.assertGreaterEqual(b.cash, -1e-9)
        self.assertLess(b.cash, 1e-6)

    def test_sell_without_position_is_noop(self):
        self.assertIsNone(PaperBroker().sell(1, 100, T0, "test"))


class RiskTests(unittest.TestCase):
    def test_exit_reasons(self):
        r = RiskManager(RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.1))
        self.assertIn("stop loss", r.exit_reason(100, 94))
        self.assertIn("take profit", r.exit_reason(100, 111))
        self.assertIsNone(r.exit_reason(100, 101))

    def test_drawdown_halts(self):
        r = RiskManager(RiskConfig(max_drawdown_pct=0.2))
        r.update_equity(100)
        r.update_equity(85)
        self.assertFalse(r.halted)
        r.update_equity(79)
        self.assertTrue(r.halted)

    def test_invalid_config(self):
        with self.assertRaises(ValueError):
            RiskConfig(position_size_pct=1.5)


class BacktestTests(unittest.TestCase):
    def test_fills_at_next_bar_open(self):
        # Signal fires on the close of bar 4; the fill must use bar 5's open.
        closes = [10, 10, 10, 10, 20, 21]
        opens = [10, 10, 10, 10, 10, 19]
        result = run_backtest(
            bars_from_closes(closes, opens), SMACrossover(2, 4),
            RiskConfig(stop_loss_pct=None, take_profit_pct=None, max_drawdown_pct=None),
            fee_rate=0, slippage_pct=0,
        )
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].price, 19)
        self.assertEqual(result.trades[0].timestamp, T0 + timedelta(hours=5))

    def test_deterministic_on_synthetic_data(self):
        bars = generate_synthetic(n=500, seed=1)
        a = run_backtest(bars, SMACrossover())
        b = run_backtest(bars, SMACrossover())
        self.assertEqual(a.metrics, b.metrics)
        self.assertEqual(len(a.equity_curve), 500)
        self.assertGreater(a.metrics["round_trips"], 0)
        self.assertLessEqual(a.metrics["max_drawdown"], 1)


class DataTests(unittest.TestCase):
    def test_csv_round_trip(self):
        bars = generate_synthetic(n=10)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bars.csv"
            save_csv(bars, path)
            self.assertEqual(load_csv(path), bars)

    def test_csv_epoch_millis(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bars.csv"
            path.write_text("Timestamp,Open,High,Low,Close\n1704067200000,1,2,0.5,1.5\n")
            (bar,) = load_csv(path)
            self.assertEqual(bar.timestamp, T0)
            self.assertEqual(bar.volume, 0.0)


class FakeFeed:
    def __init__(self, batches):
        self.batches = list(batches)

    def fetch_bars(self, limit):
        return self.batches.pop(0)[-limit:]


class LiveLoopTests(unittest.TestCase):
    def test_acts_once_per_new_candle(self):
        flat = bars_from_closes([10, 10, 10, 10])
        up = bars_from_closes([10, 10, 10, 10, 20])
        broker = PaperBroker(1000, fee_rate=0, slippage_pct=0)
        trader = Trader(SMACrossover(2, 4), broker, RiskManager(RiskConfig()))
        # The same candle repeated must not trigger a second trade.
        run_loop(trader, FakeFeed([flat, up, up]), poll_seconds=0, max_iterations=3, sleep=lambda s: None)
        self.assertEqual([t.side for t in broker.trades], [Side.BUY])

    def test_errors_do_not_stop_loop(self):
        class Flaky:
            calls = 0

            def fetch_bars(self, limit):
                Flaky.calls += 1
                raise ConnectionError("boom")

        trader = Trader(SMACrossover(2, 4), PaperBroker(), RiskManager(RiskConfig()))
        with self.assertLogs("trading_bot.live", level="ERROR"):
            run_loop(trader, Flaky(), poll_seconds=0, max_iterations=3, sleep=lambda s: None)
        self.assertEqual(Flaky.calls, 3)


class FakeExchange:
    """Mimics the small slice of the ccxt API the bot uses."""

    def __init__(self):
        self.balances = {"BTC": 0.0, "USDT": 1000.0}
        self.orders = []

    def load_markets(self):
        pass

    def fetch_ohlcv(self, symbol, timeframe, limit):
        start = int(T0.timestamp() * 1000)
        return [[start + i * 3_600_000, 1, 2, 0.5, 1.5, 10] for i in range(limit)]

    def fetch_balance(self):
        return {"free": dict(self.balances)}

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.4f}"

    def create_order(self, symbol, type_, side, amount):
        self.orders.append((side, amount))
        sign = 1 if side == "buy" else -1
        self.balances["BTC"] += sign * amount
        self.balances["USDT"] -= sign * amount * 100
        return {"filled": amount, "average": 100.0, "fee": {"cost": 0.1}}


class ExchangeTests(unittest.TestCase):
    def test_feed_drops_forming_candle(self):
        bars = ExchangeFeed(FakeExchange(), "BTC/USDT").fetch_bars(5)
        self.assertEqual(len(bars), 5)
        self.assertEqual(bars[0].timestamp, T0)

    def test_ccxt_broker_round_trip(self):
        ex = FakeExchange()
        broker = CCXTBroker(ex, "BTC/USDT")
        self.assertEqual(broker.cash, 1000.0)
        trade = broker.buy(100, 100.0, T0, "test")  # more than affordable
        self.assertEqual(ex.orders[0][0], "buy")
        self.assertLessEqual(ex.orders[0][1], 1000 / 100)
        self.assertEqual(broker.entry_price, 100.0)
        self.assertEqual(trade.fee, 0.1)
        broker.sell(broker.position, 100.0, T0, "test")
        self.assertEqual(ex.orders[1], ("sell", ex.orders[0][1]))
        self.assertIsNone(broker.entry_price)


class CliTests(unittest.TestCase):
    def test_backtest_command(self):
        self.assertEqual(main(["backtest", "--synthetic", "300", "--strategy", "rsi", "--param", "period=10"]), 0)

    def test_bad_strategy_params(self):
        self.assertEqual(main(["backtest", "--synthetic", "100", "--param", "fast=50", "--param", "slow=10"]), 2)


if __name__ == "__main__":
    unittest.main()
