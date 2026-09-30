# Solana Memecoin Screener (paper trading only)

This program looks at brand-new Solana memecoins, runs each one through a list
of safety and quality checks, and prints a **PASS/FAIL report**. When a token
passes every check, it makes a **pretend $10 buy** and tracks it. It never
spends real money.

## Safety first

- **Read-only.** It only reads public web pages of data. It never connects to
  a wallet or an exchange.
- **No wallet secrets.** It never asks for private keys or seed phrases. If
  anything ever asks you for these, don't give them. The one key it can use
  is an optional, free Helius API key for the convergence strategy: that's a
  data-access key (like a library card), not a wallet key, and it can't move
  or trade anything.
- **Paper trading only.** "Buys" and "sells" are just rows in a spreadsheet.
  There's no code anywhere in here that can place a real order.

## Where the data comes from (all free)

- **DexScreener** (`api.dexscreener.com`): prices, market cap, liquidity, trade
  counts. The candidate list comes from its *latest token profiles* and
  *latest boosts* lists (tokens whose teams recently paid to promote them).
- **RugCheck** (`api.rugcheck.xyz`): who holds the token, whether the creator
  can still mint more or freeze wallets, and whether the pool money is locked.
- **GeckoTerminal** (`api.geckoterminal.com`): its *new pools* list is an extra
  source of candidates for the early strategy (below). If it's down, the early
  strategy carries on with the other sources.
- **Helius** (`mainnet.helius-rpc.com`, free plan, needs a free sign-up):
  wallets' transactions, for the convergence strategy only (below).

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
- `data/entries.csv` (and the same file in `data/early/` and
  `data/convergence/`): one row per pretend buy with what the market looked
  like at that moment, for later analysis: buys and sells over the last hour
  (DexScreener) and insider-network status (RugCheck: whether any insider
  flag was set, the number of networks, linked wallets and insider top
  holders). Blank or `unknown` means the data wasn't available. Rows are never
  removed, even after the position closes. Nothing here affects trading.
- `data/early/`: the same two files for the early strategy (below), plus its
  watchlist of young tokens and the creators it has seen launch dead tokens.
- `data/convergence/`: the same two files for the convergence strategy
  (below), plus its tracked wallets and its Helius credit count.
- `python compare.py`: all strategies side by side, for today and all time
  (`--date yesterday` or `--date 2026-10-01` for another day), plus Helius
  credit use.

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
| The most liquid of all tokens with the same name or symbol from the last 7 days | Skips copycats and hype waves, but not the original (or leading) token |
| Creator not known for dead tokens | Skips serial ruggers (see below) |

**Selling:** half at 2x. Everything left goes at -30% (hard stop), or after
45 minutes if 2x hasn't happened (time stop). After taking profit, the other
half rides until it falls 40% from its peak, or 24 hours pass. Fees and
slippage are assumed to be 5% per full trade (3% for the main strategy),
because young pools are thinner.

**Good to know:**
- The bot runs every 5 minutes, so "the peak" is what it has seen at those
  moments (plus DexScreener's 5m/1h/6h changes when it first sees a token),
  and the 45-minute time stop really triggers at 45–50 minutes.
- "Creator has dead tokens" uses RugCheck's list of the creator's other tokens
  when it has one, which is rare. On top of that, whenever a token the bot is
  watching dies (market cap under $5k, or flagged as rugged), its creator is
  remembered and their later tokens are skipped. That memory starts empty and
  gets more useful the longer the bot runs.
- Early tokens get their own GitHub issues, titled **PASSED (early): SYMBOL**
  and labelled `strategy: early`. Main-strategy issues are labelled
  `strategy: main`.
- Once a day (00:07 UTC), `.github/workflows/daily-comparison.yml` posts the
  previous day's comparison of all strategies as an issue labelled
  `daily-comparison`, and closes the day before's.

## The "convergence" strategy (a third, separate paper strategy)

It follows proven traders: when **3 or more wallets from a tracked list buy
the same token within 20 minutes**, it paper-buys **$5** of it. It has its own
positions and journal in `data/convergence/`, and no GitHub issue per trade;
its results are in the daily comparison. Numbers are in `[convergence]` in
`config.toml`.

**The tracked list, rebuilt every week:**
1. Every run, tokens up 100%+ in 24h with $30k+ liquidity are remembered as
   the week's winners (free DexScreener data).
2. The biggest holders of the top 10 winners (free RugCheck data, creators
   and insiders left out) become candidates, up to 30.
3. Each candidate's last 14 days of swaps are read from Helius and their
   **realized profit** (in SOL) is worked out.
4. Candidates are dropped if they made over 150 transactions in 14 days
   (probably a bot), closed fewer than 5 trades, made under 2 SOL, won under
   40% of trades, or made over 60% of their profit on one token.
5. The 15 most profitable become the tracked list. This work is spread over
   many runs, so a new list takes a few hours to build.

**Buying:** every 15 minutes, each tracked wallet's new transactions are read
and decoded. When 3+ of them bought the same token within 20 minutes, and the
last of those buys was in the last 20 minutes, the token is paper-bought if
it has a DexScreener price, at least $10k liquidity, and mint and freeze
authority revoked.

**Selling:** half at 2x; everything left at -30%; everything left once 2 of
the wallets that triggered the buy have sold it ("smart money exit"); after
taking profit, the rest at 40% below its peak; 24 hours at most. Fees and
slippage are assumed to be 5% per full trade.

**Helius credits.** The two calls this uses (`getSignaturesForAddress` and
`getTransaction`) cost **10 credits each**, so the free plan's 1,000,000
monthly credits buy about 100,000 calls. That's why it tracks about 15
wallets, not 50. Every call is counted before it's made, and:
- the weekly list rebuild only uses credits left over after reserving enough
  for live checks until the end of the month;
- the strategy **pauses itself** rather than go past **80%** of the monthly
  credits, and starts again when Helius resets your credits (open positions
  keep being managed while paused, using free DexScreener prices);
- the daily comparison shows credits used that day, this cycle, the pause
  limit and whether it's paused.

On the free plan with no payment method, Helius doesn't charge for going
over: it just stops answering until your credits reset. The 80% pause keeps it well away from that.

Following wallets means buying after them: the price has usually moved by the
third buy, and some tracked wallets will sell to their followers. That's what
this paper test is for.

### Setting up the free Helius API key

You only do this once. It takes about 5 minutes.

**1. Create the free Helius account and key**
1. Go to **https://dashboard.helius.dev/signup** and create an account. If
   you're asked to choose a plan, choose **Free** ($0/month). Don't add a
   payment method: without one, Helius can't charge you anything.
2. Write down **today's date**. Your free credits reset on this day of the
   month (see step 3).
3. In the dashboard's left sidebar, click **API Keys**.
4. If a key is already listed, you can use it. Otherwise click **Create New
   API Key** and name it `trading-bot`.
5. **Copy the key right away**: Helius may not show it again after you leave
   the page. It looks like `a1b2c3d4-e5f6-...`. Keep it private: don't paste
   it into chats, files or commits. This repository is public.

**2. Add it to GitHub as a secret**
1. Open the repository on GitHub and click **Settings** (top right of the
   repository page, not your account settings).
2. In the left sidebar, click **Secrets and variables**, then **Actions**.
3. Click the green **New repository secret** button.
4. **Name:** `HELIUS_API_KEY` (exactly like that).
5. **Secret:** paste the key.
6. Click **Add secret**.

GitHub keeps the secret encrypted, hides it in logs, and only gives it to
this repository's own workflows. It isn't given to pull requests from other
people's copies of the repository.

**3. Tell the bot when your credits reset**
In `config.toml`, under `[convergence]`, set `helius_cycle_day` to the day of
the month from step 1.2 (for example `helius_cycle_day = 30`; use `28` if you
signed up on the 29th, 30th or 31st, which resets a little early and stays
safe). Commit that change.

**4. Check it works**
1. Go to the repository's **Actions** tab, pick **Paper trading run**, and
   click **Run workflow**.
2. When it finishes, open the run and look at **STEP 6** in the summary. You
   should see `Helius credits this cycle: ...` and
   `weekly list refresh started: N candidate wallets`, instead of
   `not active: add the HELIUS_API_KEY secret`.
3. Optional: the credit usage shown in your Helius dashboard should be about
   the same as the bot's count. If you use the same key anywhere else, the
   bot can't see that usage, so give this bot its own Helius account.

To stop using Helius, delete the secret (Settings, Secrets and variables,
Actions), or set `enabled = false` under `[convergence]`.

## Running automatically on GitHub

`.github/workflows/screener.yml` runs the screener every 5 minutes on GitHub
Actions (and you can start a run by hand from the **Actions** tab). GitHub
sometimes starts scheduled runs a few minutes late when it's busy. Runs never
overlap: one that's due while another is still going waits for it. Each run's
full PASS/FAIL report is shown on that run's summary page.

The convergence strategy still reads Helius only every 15 minutes
(`helius_every_minutes` in `config.toml`), so its credit use doesn't go up; its
open positions are checked every run.

**Schedule changes are recorded.** `[schedule] run_every_minutes` in
`config.toml` must match the workflow's cron line. When it changes, the next
run adds the date and time to `data/schedule.json`, and the daily comparison
shows each strategy's results before and after the latest change separately
(positions are grouped by when they were bought).

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
| `screener/convergence.py` | The convergence strategy: Helius reads, credit budget, wallet scoring, signals and exits |
| `screener/compare.py`, `compare.py` | The side-by-side comparison of all strategies, with Helius credit use |
| `screener/demo.py` | Made-up tokens for `--demo` and the tests |
| `tests/` | Automated checks that the rules work. Run with `python -m unittest -v` |
| `.github/workflows/screener.yml` | Runs all strategies every 5 minutes on GitHub |
| `.github/workflows/daily-comparison.yml` | Posts the daily comparison issue |

## Important caveats

- Memecoins are extremely risky. Most go to zero. Passing these checks
  makes a token *less likely* to be an obvious scam, not safe.
- Paper results are more optimistic than real trading: real slippage on small
  tokens can be much worse than 3%, and prices can crash between runs.
  Exits only happen when you run the program, so a stop loss at -30% might
  actually trigger at -60% if the price fell a lot while it wasn't running.
- This is an educational tool, not financial advice.
