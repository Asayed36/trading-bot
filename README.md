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

## Where the data comes from (all free, no sign-up)

- **DexScreener** (`api.dexscreener.com`): prices, market cap, liquidity, trade
  counts. The candidate list comes from its *latest token profiles* and
  *latest boosts* lists (tokens whose teams recently paid to promote them).
- **RugCheck** (`api.rugcheck.xyz`): who holds the token, whether the creator
  can still mint more or freeze wallets, and whether the pool money is locked.
- **GeckoTerminal** (`api.geckoterminal.com`): its *new pools* list is an extra
  source of candidates for the early strategy (below). If it's down, the early
  strategy carries on with the other sources.

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
- `data/early/`: the same two files for the early strategy (below), plus its
  watchlist of young tokens and the creators it has seen launch dead tokens.
- `python compare.py`: both strategies side by side, for today and all time
  (`--date yesterday` or `--date 2026-10-01` for another day).

## The "early" strategy (a second, separate paper strategy)

Every run also paper-trades a second strategy that goes after young tokens,
with its own $10 pretend buys, positions and journal. The main strategy above
is unchanged. The point is to find out, with pretend money, whether buying
early actually works for someone arriving at the bot's speed.

**It buys a token only when all of these are true** (numbers in `[early]` in
`config.toml`):

| Check | Why |
|---|---|
| Graduated to PumpSwap or Raydium, at least 30 min ago | Past the first-minutes dump, and RugCheck can check the real pool |
| Token at most 6 hours old | Still early |
| Pullback: spiked 50%+, now 20–50% below its peak | Buys the dip, not the green candle |
| Not falling over the last 5 min, more buys than sells over the last hour | The dip is holding |
| Liquidity at least $10k | You could sell again |
| Mint and freeze authority revoked, LP locked or burned | Same basic safety as the main strategy |
| Top 10 holders own under 20% | Stricter than main: young tokens are easy to dump |
| No insider flags at all | Linked wallets are a **FAIL** here, not a warning |
| No other token with the same name or symbol in the last 7 days | Skips copycats and hype waves |
| Creator not known for dead tokens | Skips serial ruggers (see below) |

**Selling:** half at 2x. Everything left goes at -30% (hard stop), or after
45 minutes if 2x hasn't happened (time stop). After taking profit, the other
half rides until it falls 40% from its peak, or 24 hours pass. Fees and
slippage are assumed to be 5% per full trade (3% for the main strategy),
because young pools are thinner.

**Good to know:**
- The bot runs every 15 minutes, so "the peak" is what it has seen at those
  moments (plus DexScreener's 5m/1h/6h changes when it first sees a token),
  and the 45-minute time stop really triggers at 45–60 minutes.
- "Creator has dead tokens" uses RugCheck's list of the creator's other tokens
  when it has one, which is rare. On top of that, whenever a token the bot is
  watching dies (market cap under $5k, or flagged as rugged), its creator is
  remembered and their later tokens are skipped. That memory starts empty and
  gets more useful the longer the bot runs.
- Early tokens get their own GitHub issues, titled **PASSED (early): SYMBOL**
  and labelled `strategy: early`. Main-strategy issues are labelled
  `strategy: main`.
- Once a day (00:07 UTC), `.github/workflows/daily-comparison.yml` posts the
  previous day's comparison of both strategies as an issue labelled
  `daily-comparison`, and closes the day before's.

## Running automatically on GitHub

`.github/workflows/screener.yml` runs the screener every 15 minutes on GitHub
Actions (and you can start a run by hand from the **Actions** tab). GitHub
sometimes starts scheduled runs a few minutes late when it's busy. Each run's
full PASS/FAIL report is shown on that run's summary page.

After a run, it commits `data/journal.csv` and `data/positions.json` back to
the repository so the next run carries on with the same pretend positions,
but only when something actually changed: a buy, a sell, or a new price high
for a position you hold (the trailing stop needs it). Runs where nothing
changed make no commit.

If DexScreener or RugCheck say "too many requests", the program skips that
whole run: it fetches all the data *before* changing any pretend trade, so a
skipped run changes nothing (`python run.py` exits with code 75). The run
shows a notice instead of failing, and the next run tries again.

### A GitHub issue for every token that passes

When a token passes every filter, the scheduled run opens an issue titled
**PASSED: SYMBOL**, labelled `passed`, with:

- the token name, contract address and DexScreener link
- the paper entry price, market cap, liquidity and 24h change when it passed
- the top 10 holders (pool wallets left out)
- the exit levels worked out from the entry price: take profit (sell half)
  at +50%, stop loss at -30%, trailing stop 40% below the peak, and the 48h
  time stop (which only sells if the price is still within ±10% of entry)
- a reminder that passing the filters is not a buy signal, and the
  one-sentence test: why does this coin exist, why now, and who will buy from
  you at a higher price? (change the wording under `[github_issues]` in
  `config.toml`)

Each token only ever gets one issue, even if it passes again later or two
tokens share a symbol: issues are matched by contract address. When the paper
position closes, the run comments on the issue with every sale, the exit
reason and the final profit or loss, then closes it. If GitHub can't be
reached, nothing is lost: the pending issue work is saved in
`data/positions.json` and retried on the next run.

Issues are only opened for tokens you hold a paper position in (a new buy,
or one bought earlier that passes again), so every issue gets closed.
Positions bought before this feature existed get an issue the next time they
pass. Local runs (`python run.py`) never touch GitHub.

Those two files are tracked by git, so if you also run `python run.py` on
your own computer, your local runs change the same files. Pull first
(`git pull`) and don't commit your local `data/` changes, or the two records
will get mixed up. Use `python run.py --demo` to try things out safely.

## Files in this project

| File | What it does |
|---|---|
| `run.py` | The program you run. Ties everything together |
| `config.toml` | All the numbers you can change |
| `screener/api.py` | Fetches data from DexScreener, RugCheck and GeckoTerminal |
| `screener/filters.py` | The PASS/FAIL checks |
| `screener/paper_trader.py` | Pretend buys, sells and the journal |
| `screener/github_issues.py` | Opens and closes the "PASSED" GitHub issues |
| `screener/early.py` | The early strategy: candidates, checks, pullback entry and exits |
| `screener/compare.py`, `compare.py` | The side-by-side comparison of both strategies |
| `screener/demo.py` | Made-up tokens for `--demo` and the tests |
| `tests/` | Automated checks that the rules work. Run with `python -m unittest -v` |
| `.github/workflows/screener.yml` | Runs both strategies every 15 minutes on GitHub |
| `.github/workflows/daily-comparison.yml` | Posts the daily comparison issue |

## Important caveats

- Memecoins are extremely risky. Most go to zero. Passing these checks
  makes a token *less likely* to be an obvious scam, not safe.
- Paper results are more optimistic than real trading: real slippage on small
  tokens can be much worse than 3%, and prices can crash between runs.
  Exits only happen when you run the program, so a stop loss at -30% might
  actually trigger at -60% if the price fell a lot while it wasn't running.
- This is an educational tool, not financial advice.
