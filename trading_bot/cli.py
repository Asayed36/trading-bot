"""Command line interface: `python -m trading_bot {backtest,fetch,trade}`."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .backtest import run_backtest
from .broker import CCXTBroker, PaperBroker
from .data import ExchangeFeed, generate_synthetic, load_csv, make_exchange, save_csv
from .live import run_loop
from .risk import RiskConfig, RiskManager
from .strategies import STRATEGIES, build_strategy
from .trader import Trader

# Bars per year for annualising the Sharpe ratio.
PERIODS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
    "1h": 8_760, "4h": 2_190, "1d": 365, "1w": 52,
}


def _parse_params(pairs: list[str]) -> dict:
    params = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--param expects key=value, got {pair!r}")
        try:
            number = float(value)
            params[key] = int(number) if number.is_integer() and "." not in value else number
        except ValueError:
            params[key] = value
    return params


def _optional_pct(value: str):
    return None if value.lower() in ("none", "off", "0") else float(value)


def _add_strategy_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strategy", default="sma_crossover", choices=sorted(STRATEGIES))
    p.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                   help="strategy parameter, e.g. --param fast=10 --param slow=30")
    p.add_argument("--position-size", type=float, default=0.95,
                   help="fraction of equity per trade (default 0.95)")
    p.add_argument("--stop-loss", type=_optional_pct, default=0.05,
                   help="stop-loss fraction, or 'off' (default 0.05)")
    p.add_argument("--take-profit", type=_optional_pct, default=0.10,
                   help="take-profit fraction, or 'off' (default 0.10)")
    p.add_argument("--max-drawdown", type=_optional_pct, default=0.25,
                   help="halt trading at this drawdown, or 'off' (default 0.25)")


def _risk_config(args) -> RiskConfig:
    return RiskConfig(
        position_size_pct=args.position_size,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        max_drawdown_pct=args.max_drawdown,
    )


def cmd_backtest(args) -> int:
    if args.data:
        bars = load_csv(args.data)
    else:
        bars = generate_synthetic(n=args.synthetic, seed=args.seed)
        print(f"No --data given; using {len(bars)} synthetic hourly bars (seed={args.seed}).\n")
    strategy = build_strategy(args.strategy, **_parse_params(args.param))
    result = run_backtest(
        bars, strategy, _risk_config(args),
        initial_cash=args.cash, fee_rate=args.fee, slippage_pct=args.slippage,
        periods_per_year=PERIODS_PER_YEAR.get(args.timeframe, 8_760),
    )
    print(f"Strategy: {strategy!r}")
    print(f"Bars:     {len(bars)}  ({bars[0].timestamp} -> {bars[-1].timestamp})\n")
    print(result.summary())
    if args.show_trades:
        print("\nTrades:")
        for t in result.trades:
            print(f"  {t.timestamp}  {t.side.value:<4}  {t.quantity:.6f} @ {t.price:.4f}  ({t.reason})")
    return 0


def cmd_fetch(args) -> int:
    exchange = make_exchange(args.exchange)
    bars = ExchangeFeed(exchange, args.symbol, args.timeframe).fetch_bars(args.limit)
    save_csv(bars, args.output)
    print(f"Saved {len(bars)} bars to {args.output}")
    return 0


def cmd_trade(args) -> int:
    strategy = build_strategy(args.strategy, **_parse_params(args.param))
    if args.live:
        key = os.environ.get("TRADING_BOT_API_KEY")
        secret = os.environ.get("TRADING_BOT_API_SECRET")
        if not key or not secret:
            print("--live needs TRADING_BOT_API_KEY and TRADING_BOT_API_SECRET set.", file=sys.stderr)
            return 2
        exchange = make_exchange(args.exchange, key, secret, sandbox=args.sandbox)
        broker = CCXTBroker(exchange, args.symbol)
        mode = "LIVE (sandbox)" if args.sandbox else "LIVE - REAL MONEY"
    else:
        exchange = make_exchange(args.exchange)
        broker = PaperBroker(args.cash, args.fee, args.slippage)
        mode = "paper"
    trader = Trader(strategy, broker, RiskManager(_risk_config(args)))
    feed = ExchangeFeed(exchange, args.symbol, args.timeframe)
    logging.getLogger(__name__).warning(
        "Starting %s trading: %s %s on %s with %r", mode, args.symbol, args.timeframe, args.exchange, strategy
    )
    try:
        run_loop(trader, feed, poll_seconds=args.poll)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-bot", description="A simple, extensible trading bot.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="test a strategy on historical or synthetic data")
    bt.add_argument("--data", help="CSV with timestamp,open,high,low,close[,volume]")
    bt.add_argument("--synthetic", type=int, default=2000, help="synthetic bars if no --data (default 2000)")
    bt.add_argument("--seed", type=int, default=42)
    bt.add_argument("--timeframe", default="1h", help="bar size, used to annualise Sharpe (default 1h)")
    bt.add_argument("--cash", type=float, default=10_000.0)
    bt.add_argument("--fee", type=float, default=0.001, help="fee rate per fill (default 0.001 = 0.1%%)")
    bt.add_argument("--slippage", type=float, default=0.0005)
    bt.add_argument("--show-trades", action="store_true")
    _add_strategy_args(bt)
    bt.set_defaults(func=cmd_backtest)

    fe = sub.add_parser("fetch", help="download candles from an exchange to CSV (needs ccxt)")
    fe.add_argument("--exchange", default="binance")
    fe.add_argument("--symbol", default="BTC/USDT")
    fe.add_argument("--timeframe", default="1h")
    fe.add_argument("--limit", type=int, default=1000)
    fe.add_argument("-o", "--output", default="data.csv")
    fe.set_defaults(func=cmd_fetch)

    tr = sub.add_parser("trade", help="run the bot on live market data (paper by default, needs ccxt)")
    tr.add_argument("--exchange", default="binance")
    tr.add_argument("--symbol", default="BTC/USDT")
    tr.add_argument("--timeframe", default="1h")
    tr.add_argument("--poll", type=float, default=60.0, help="seconds between checks (default 60)")
    tr.add_argument("--cash", type=float, default=10_000.0, help="starting paper cash")
    tr.add_argument("--fee", type=float, default=0.001)
    tr.add_argument("--slippage", type=float, default=0.0005)
    tr.add_argument("--live", action="store_true",
                    help="place REAL orders using TRADING_BOT_API_KEY / TRADING_BOT_API_SECRET")
    tr.add_argument("--sandbox", action="store_true", help="with --live, use the exchange testnet")
    _add_strategy_args(tr)
    tr.set_defaults(func=cmd_trade)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Backtests print a summary; per-trade logs are only shown with -v.
    quiet = args.command == "backtest" and not args.verbose
    logging.basicConfig(
        level=logging.WARNING if quiet else logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
