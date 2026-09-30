# Solana Memecoin Screener (paper trading only)

This program looks at brand-new Solana memecoins, runs each one through a list
of safety and quality checks, and prints a **PASS/FAIL report**. When a token
passes every check, it makes a **pretend $10 buy** and tracks it. It never
spends real money.

## Safety first

- **Read-only.** It only reads public web pages of data. It never connects to
  a wallet or an exchange.
- **No secrets.** It never asks for private keys, seed phrases or API keys.
  If anything ever asks you for these, don't give them.
- **Paper trading only.** "Buys" and "sells" are just rows in a spreadsheet.
  There's no code anywhere in here that can place a real order.

## Where the data comes from (both free, no sign-up)

- **DexScreener** (`api.dexscreener.com`): prices, market cap, liquidity, trade
  counts. The candidate list comes from its *latest token profiles* and
  *latest boosts* lists (tokens whose teams recently paid to promote them).
- **RugCheck** (`api.rugcheck.xyz`): who holds the token, whether the creator
  can still mint more or freeze wallets, and whether the pool money is locked.

## How to run it

1. Install Python 3.11 or newer from <https://www.python.org/downloads/>.
2. Open a terminal (Mac: the "Terminal" app. Windows: "Command Prompt") in this folder.
3. Install the one extra library it needs:
   ```
   pip install -r requirements.txt
   ```
4. Run it:
   ```
   python run.py
   ```
   (On a Mac you may need to type `python3` instead of `python`.)

Want to see how it works without the internet? Run `python run.py --demo`.
It uses **made-up tokens** and saves to a separate `demo_data/` folder, so it
never mixes with your real results.

Run it again whenever you like (for example every hour). Each run first
checks your open pretend positions and sells any that hit an exit rule, then
looks for new tokens.

## The checks (change them in `config.toml`)

| Check | Why it matters |
|---|---|
| Trades on PumpSwap or Raydium | The token has "graduated" from the pump.fun bonding curve to a real pool |
| Market cap $100k–$5M | Not a tiny unknown, not already huge |
| Liquidity at least $30k | Enough money in the pool that you could actually sell |
| Top 10 holders own under 30% | A few big wallets can't crash the price by selling |
| Creator owns under 5% | The creator can't dump a big bag on buyers |
| LP locked or burned | The creator can't pull the pool's money out (a "rug pull") |
| Mint authority revoked | Nobody can print more tokens |
| Freeze authority revoked | Nobody can freeze your tokens so you can't sell |
| Insider networks | Groups of linked wallets. Shown as a **WARN**, doesn't block a buy |
| Not up more than 300% in 24h | Avoids buying the top of a spike |
| 500+ trades in 24h, more buys than sells | Real activity, more buyers than sellers |

If any piece of data is missing, that check **FAILS**. The program never
assumes a token is safe just because it couldn't find out.

To save time and be polite to the free services, tokens that already failed a
market check aren't sent to RugCheck (they show `skip Safety checks`). Set
`skip_safety_if_market_fails = false` in `config.toml` to check them all.

## The paper trading rules

- **Buy:** $10 (pretend) of every token that passes all checks. Never the same
  token twice (change `allow_rebuy` to allow it).
- **Take profit:** at +50% from the buy price, sell half.
- **Stop loss:** if the price falls 30% below the buy price, sell the rest.
- **Trailing stop:** if the price falls 40% below its highest point since we
  bought, sell the rest.
- **Time exit:** after 48 hours, if the price has moved less than 10% either
  way, sell the rest.
- **Costs:** 3% of the money put in is subtracted per full buy+sell, to
  mimic fees and slippage. (Selling half charges half of that.)

## Your results

- `data/journal.csv`: every pretend buy and sell, with the reason, the profit
  or loss (P&L) of that sale, and a running total. Open it in Excel, Google
  Sheets or Numbers.
- `data/positions.json`: the pretend positions you currently hold. Delete the
  whole `data/` folder to start over from zero.

## Running automatically on GitHub

`.github/workflows/screener.yml` runs the screener every 2 hours on GitHub
Actions (and you can start a run by hand from the **Actions** tab). After each
run it commits `data/journal.csv` and `data/positions.json` back to the
repository, so the next run carries on with the same pretend positions. Each
run's full PASS/FAIL report is shown on that run's summary page.

Those two files are tracked by git, so if you also run `python run.py` on
your own computer, your local runs change the same files. Pull first
(`git pull`) and don't commit your local `data/` changes, or the two records
will get mixed up. Use `python run.py --demo` to try things out safely.

## Files in this project

| File | What it does |
|---|---|
| `run.py` | The program you run. Ties everything together |
| `config.toml` | All the numbers you can change |
| `screener/api.py` | Fetches data from DexScreener and RugCheck |
| `screener/filters.py` | The PASS/FAIL checks |
| `screener/paper_trader.py` | Pretend buys, sells and the journal |
| `screener/demo.py` | Made-up tokens for `--demo` and the tests |
| `tests/` | Automated checks that the rules work. Run with `python -m unittest -v` |
| `.github/workflows/screener.yml` | Runs the screener every 2 hours on GitHub |

## Important caveats

- Memecoins are extremely risky. Most go to zero. Passing these checks
  makes a token *less likely* to be an obvious scam, not safe.
- Paper results are more optimistic than real trading: real slippage on small
  tokens can be much worse than 3%, and prices can crash between runs.
  Exits only happen when you run the program, so a stop loss at -30% might
  actually trigger at -60% if the price fell a lot while it wasn't running.
- This is an educational tool, not financial advice.
