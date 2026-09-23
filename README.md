# trading-bot

A small, extensible trading bot written in Python. It includes:

- **Strategies**: a moving-average crossover and an RSI mean-reversion strategy, and you can add your own.
- **Risk management**: position sizing, stop loss, take profit, and a max-drawdown kill switch.
- **Backtesting**: runs on your own CSV data or on generated sample prices. It reports return, drawdown, Sharpe ratio and win rate, with fees and slippage counted.
- **Paper trading**: runs on live exchange prices with pretend money. This is the default.
- **Live trading**: sends real orders to 100+ crypto exchanges through [ccxt](https://github.com/ccxt/ccxt), but only if you pass `--live`.

The core uses only the Python standard library. `ccxt` is needed only for the commands that talk to an exchange.

> ⚠️ **Disclaimer.** This is educational software, not financial advice. The bundled strategies are simple examples and are **not** expected to make money. Backtest results do not predict future returns. Never trade money you can't afford to lose.

## Quick start

```bash
# Backtest on generated sample data (no install needed)
python -m trading_bot backtest

# Try another strategy with custom parameters, and list every trade
python -m trading_bot backtest --strategy rsi --param period=14 --param oversold=25 --show-trades

# Install the CLI plus exchange support
pip install -e '.[live]'

# Download real candles, then backtest on them
trading-bot fetch --exchange binance --symbol BTC/USDT --timeframe 1h --limit 1000 -o btc.csv
trading-bot backtest --data btc.csv --timeframe 1h

# Paper trade on live prices (fake money, real market data)
trading-bot trade --exchange binance --symbol BTC/USDT --timeframe 1h
```

## Going live (read this first)

1. Backtest thoroughly, then paper trade for a while.
2. Create an API key on the exchange with **trading permission only. Never enable withdrawals.**
3. Test on the exchange's testnet first, if it has one:
   ```bash
   export TRADING_BOT_API_KEY=... TRADING_BOT_API_SECRET=...
   trading-bot trade --exchange binance --symbol BTC/USDT --live --sandbox
   ```
4. Drop `--sandbox` to trade real money.

Things to know about live mode:
- The bot is **long-only on a single symbol**. It treats any free balance of the base asset (for example BTC) as its position and may sell it. Use a dedicated account or sub-account.
- The entry price is kept in memory. If you restart while a position is open, the stop loss and take profit stay off until the next entry. Strategy sell signals still work.
- The bot acts once per closed candle and places market orders.

## Common options

| Option | Default | Meaning |
|---|---|---|
| `--strategy` | `sma_crossover` | `sma_crossover` or `rsi` |
| `--param k=v` | | Strategy parameters (`fast`, `slow` / `period`, `oversold`, `overbought`) |
| `--position-size` | `0.95` | Fraction of equity used for each entry |
| `--stop-loss` | `0.05` | Exit 5% below entry (`off` to disable) |
| `--take-profit` | `0.10` | Exit 10% above entry (`off` to disable) |
| `--max-drawdown` | `0.25` | Close the position and stop trading after a 25% fall from peak equity |
| `--fee` / `--slippage` | `0.001` / `0.0005` | Simulated costs per fill |

Run `python -m trading_bot <command> --help` for the full list.

## How it works

```
data.py        CSV / synthetic / exchange candles  ─┐
strategies.py  Bars -> BUY / SELL / HOLD            │
risk.py        sizing, stop loss, take profit, halt ├─> trader.py  decides + executes
broker.py      PaperBroker (simulated) / CCXTBroker ─┘        │
backtest.py    replays history through the Trader  <──────────┤
live.py        polls the exchange, one decision per candle <──┘
```

The backtester and the live loop both use the same `Trader`, so the same decision code runs in tests and in real trading. In backtests, decisions are made on each bar's close and filled at the **next** bar's open. This keeps a strategy from trading on a price it couldn't have seen yet.

## Adding a strategy

```python
# trading_bot/strategies.py
class Breakout(Strategy):
    name = "breakout"

    def __init__(self, period: int = 20):
        self.period = period

    @property
    def lookback(self) -> int:
        return self.period + 1

    def generate_signal(self, bars):
        if len(bars) < self.lookback:
            return Signal.HOLD
        prior_high = max(b.high for b in bars[-self.lookback:-1])
        prior_low = min(b.low for b in bars[-self.lookback:-1])
        if bars[-1].close > prior_high:
            return Signal.BUY
        if bars[-1].close < prior_low:
            return Signal.SELL
        return Signal.HOLD

STRATEGIES[Breakout.name] = Breakout
```

Then run `python -m trading_bot backtest --strategy breakout --param period=50`.

## Tests

```bash
python -m unittest discover -s tests
```
