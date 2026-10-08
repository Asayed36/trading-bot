# Solana Memecoin Screener (paper trading only)

This program looks at brand-new Solana memecoins, runs each one through a list
of safety and quality checks, and prints a **PASS/FAIL report**. When a token
passes every check, it makes a **pretend $10 buy** and tracks it. It never
spends real money.

## Safety first

- **Read-only.** It only reads public web pages of data. It never connects to
  a wallet or an exchange.
- **No wallet secrets.** It never asks for private keys or seed phrases. If
  anything ever asks you for these, don't give them. The keys it can use are
  optional data-access keys (like a library card), not wallet keys: free ones
  for Helius (the convergence strategy) and CoinGecko (the news strategy),
  and an Anthropic API key for the news strategy's AI check (a paid service,
  capped at a small daily limit). None of them can move or trade anything.
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
- **Official news feeds** (PR Newswire, GlobeNewswire, Business Wire, project
  blogs, the SEC, exchange announcements and the public market lists of
  Coinbase, Upbit and OKX, all read-only with no key), **CoinGecko** (free
  plan) and, optionally, **Anthropic's API** (Claude Haiku 4.5, with the
  `CLAUDE_API_KEY` secret: a second opinion on headlines): for the news
  strategy only (below).
- **GoPlus** (`api.gopluslabs.io`, no key) and **Robinhood Chain's public RPC**
  (`rpc.mainnet.chain.robinhood.com`, no key): for the robinhood strategy only
  (below), with GeckoTerminal and DexScreener.

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

## Which strategies are running

Since 2026-10-07, after a review of every strategy's results:
- **Running:** main (1 min)'s versions B and C (on your server; main
  (1 min)'s own checks run every minute for them), news (GitHub), news
  (listings) (server) and convergence (GitHub).
- **Stopped** (`stopped = true` in `config.toml`): main on GitHub, early,
  the three launch speeds, all three momentum variants, robinhood, main
  (1 min)'s own buying and its version A. A stopped
  strategy makes no new buys; positions it still holds finish under its
  normal exits, then it does nothing. Its journal and files are kept, and
  the daily comparison still shows it, marked "(stopped)". To restart one,
  remove its `stopped = true` line.

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
  (DexScreener), insider-network status (RugCheck: whether any insider
  flag was set, the number of networks, linked wallets and insider top
  holders), the price change over the last 5 minutes and the last hour
  (DexScreener, `price_change_5m_pct` / `price_change_1h_pct`), and
  Jupiter's organic score at the buy (`jupiter_organic_score` 0-100,
  `jupiter_organic_label` low/medium/high, and the share of the last hour's
  buy volume and traders Jupiter counts as organic; from Jupiter's free
  Tokens API, logging only; the news strategy's coins aren't Solana tokens,
  so its rows leave these blank). Blank or
  `unknown` means the data wasn't available; buys from before a column was
  added have it blank. Rows are never removed, even after the position
  closes. Nothing here affects trading.
- `data/early/`: the same two files for the early strategy (below), plus its
  watchlist of young tokens and the creators it has seen launch dead tokens.
- `data/convergence/`: the same two files for the convergence strategy
  (below), plus its tracked wallets and its Helius credit count.
- `python compare.py`: all strategies side by side, for today and all time
  (`--date yesterday` or `--date 2026-10-01` for another day), plus Helius
  credit use.

## The "early" strategy (a second, separate paper strategy)

**Stopped on 2026-10-05** (`stopped = true` in `config.toml`): it makes no new buys; positions it still holds finish under the normal exits, and its journal and files are kept. The daily comparison shows it as "(stopped)".

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
  previous day's comparison of all strategies (including the launch bot's latest
  pushed results) as an issue labelled
  `daily-comparison`, and closes the day before's.
- **A health section at the top** of that issue shows, as of when it's posted,
  whether everything is running, with a ⚠️ and a short list of problems
  when something is stale or broken (settings under `[health]` in
  `config.toml`):
  - scheduled runs: how many failed in the last 24 hours, and when the last
    successful one finished (warns on any failure);
  - the real time between scheduled runs in the last 24 hours (average,
    median, longest), from GitHub's run history: GitHub often starts
    scheduled runs late, so it's usually longer than the cron line asks for.
    The before/after-the-schedule-change table also shows each period's real
    average (e.g. "every 5 min (actually ~18)");
  - each strategy (main, early, convergence, news): its last successful run
    (warns if older than 60 minutes or skipped since). Every run records
    this in `data/health.json`, which is saved at least every 30 minutes;
  - convergence: how many wallets it tracks (warns under 3, when it can't
    give a signal) and whether Helius is paused;
  - news: each source, ok, turned off, failing with the reason, or with
    nothing new for longer than usual; and the AI check: today's count
    against its daily limit, not used (no key), or failing;
  - launch: when your server last pushed results (warns after 3 hours or if
    it never has).

## The "convergence" strategy (a third, separate paper strategy)

It follows proven traders: when **3 or more wallets from a tracked list buy
the same token within 20 minutes**, it paper-buys **$5** of it. It has its own
positions and journal in `data/convergence/`, and no GitHub issue per trade;
its results are in the daily comparison. Numbers are in `[convergence]` in
`config.toml`.

**The tracked list, grown every day:**
1. Every run, tokens up 100%+ in 24h with $30k+ liquidity are remembered as
   the week's winners (free DexScreener data).
2. Every day, from 20 of the winners (the ones not used in the last 3 days
   first), candidates are the wallets that recently **sold** it (its pool's
   last 300 trades on GeckoTerminal, free; sells of $50+) and its biggest
   holders (free RugCheck data, creators and insiders left out), up to 150.
   Wallets seen on more winners come first, and sellers before holders: a
   holder who hasn't sold has no closed trades to judge. Wallets already
   scored in the last 7 days are skipped.
3. Each candidate's last 14 days of swaps are read from Helius and their
   **realized profit** (in SOL) is worked out. A wallet with fewer than 10
   transactions in 14 days can't have 5 closed trades, so its transactions
   aren't read (same result, fewer credits).
4. Candidates are dropped if they made over 150 transactions in 14 days
   (probably a bot), closed fewer than 5 trades, made under 2 SOL, won under
   40% of trades, or made over 60% of their profit on one token.
5. Every candidate that passes joins the tracked list at once (the 50 most
   profitable stay). Each tracked wallet is scored again every 7 days and
   leaves the list if it no longer passes. This work is spread over many
   runs, within a daily share of the Helius credits. The run log (and
   `list_summary` in `data/convergence/positions.json`) says why candidates
   were dropped, e.g. `26 too few closed trades, 3 qualified; 41 swaps in
   812 transactions`.

**Buying:** every 15 minutes, each tracked wallet's new transactions are read
and decoded. When 3+ of them bought the same token within 20 minutes, and the
last of those buys was in the last 20 minutes, the token is paper-bought if
it has a DexScreener price, at least $10k liquidity, and mint and freeze
authority revoked.

**Selling:** half at 2x; everything left at -30%; everything left once 2 of
the wallets that triggered the buy have sold it ("smart money exit"); after
taking profit, the rest at 40% below its peak; 24 hours at most. Fees and
slippage are assumed to be 5% per full trade.

**Helius credits.** Helius's price list says the two calls this uses
(`getSignaturesForAddress` and `getTransaction`) can cost up to 10 credits
each, but the Helius dashboard showed far less: about 1 credit per call for
recent data (live checks) and about 2.5 per call when reading candidates'
14-day histories. The bot counts **2 credits per live call and 4 per history
call** (`helius_live_credits_per_call` and `helius_history_credits_per_call`
in `config.toml`), above what was measured, so its count errs high. At those
rates it can follow 50 wallets and use roughly half the free 1,000,000
monthly credits. Every call is counted before it's made, and:
- scoring candidates only uses credits left over after reserving enough
  for live checks of the list until the end of the month, spread evenly over
  the days left (at most a day's share a day);
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
   `list refresh started: N wallets to score`, instead of
   `not active: add the HELIUS_API_KEY secret`.
3. Now and then, compare your Helius dashboard with the bot's count. The bot's
   count should be **higher** (it's a deliberately cautious estimate). If the
   dashboard is ever higher, raise `helius_live_credits_per_call` /
   `helius_history_credits_per_call`; if it's much lower for a week or more,
   you can lower them. When they change, the bot rescales its count for the
   current cycle. If you use the same key anywhere else, the bot can't see
   that usage, so give this bot its own Helius account.

To stop using Helius, delete the secret (Settings, Secrets and variables,
Actions), or set `enabled = false` under `[convergence]`.

## The "main (1 min)" strategy (the main strategy every minute, on your own server)

(The main strategy on GitHub was stopped on 2026-10-05; its rules live on
here, checked every minute.)

The same strategy as **main**, checked **every minute** instead of every few
minutes, to see whether checking more often changes the results. It runs all
the time on the launch bot's server (`main_1min.py`, the `main-1min`
service; setup: Part G of
[`deploy/LAUNCH_SERVER_SETUP.md`](deploy/LAUNCH_SERVER_SETUP.md)).

- **Exactly main's rules:** it reads `[filters]` and `[paper_trading]` in
  `config.toml` and uses main's own code for the checks and the paper trades,
  so the two can't drift apart: the same entry checks, **$10** buys, **3%**
  costs, and the same exits (sell half at +50%; everything left at -30%, 40%
  below the peak, or after 48 hours if it's still within ±10% of entry).
- **Its own files:** `data/main-1min/` (`journal.csv`, `positions.json`,
  `entries.csv`, `health.json`). It never reads or writes the GitHub main
  strategy's files and opens no GitHub issues. The hourly push
  (`deploy/push_results.sh`) sends the folder here.
- **Updates itself:** when the hourly push brings new code it uses, it
  saves, exits and is started again by systemd with the new code (like the
  launch bot; "automatic restart" in `journalctl -u main-1min`).
- **Free limits:** about 4–6 DexScreener requests a minute (its limits are 60
  a minute for the lists and 300 for pairs). RugCheck is asked only about
  tokens that pass the market checks, and only when a token is new or its
  report is more than 10 minutes old, at most 10 a minute; after a "too many
  requests" it isn't asked for 5 minutes (tokens waiting for RugCheck are
  checked the next minute, never bought without it). Settings: `[main_1min]`.
- **In the daily comparison:** the **main (1 min)** column, next to main,
  and a health row with its last good run, runs and busiest-hour requests,
  and its last push.

### Versions A, B and C (paper, side by side on the same data)

More paper versions run inside the same bot, on exactly the same data
every minute, each with main's checks plus one extra rule, the same exits
and costs, and its own files:

| Version | Extra rule | Files |
|---|---|---|
| **main (1 min) A** | buys a token only after it passed main's checks on **3 consecutive one-minute checks**. A token that drops off DexScreener's lists while on a run of passes is still checked each minute (for A only). The counts start again if the bot restarts. | `data/main-1min/a/` |
| **main (1 min) B** | skips tokens **up more than 100% in the last hour**, and needs a **Jupiter organic score of at least 60** (no score = skip). | `data/main-1min/b/` |
| **main (1 min) C** | B's two rules, but **decided once, at the minute a token first passes main's checks**: bought then if it's up no more than 100% in the last hour and has an organic score of 60+, else skipped for good. Unlike B it never waits for a token to cool down (B bought a median 45 minutes after main). Tokens main (1 min) had already passed when C started count as decided; decisions are kept 14 days in its `positions.json`. | `data/main-1min/c/` |

They test the two ideas from the review: main (1 min) won on the tokens it
shared with main but lost on tokens that passed only briefly (A), and
chasing tokens up more than 100% in an hour lost the most money (B). Each
has its own column in the daily comparison and a health row (its open
positions, buys, and the tokens it passed on in the last 24 hours). Jupiter
is read at most once per token every 10 minutes (shared by B and every
buy's `entries.csv` row). Settings: `[[main_1min.versions]]` in
`config.toml`.

## The "news (listings)" strategy (exchange listings every minute, on your own server)

The news strategy for the exchange listings only, checked **every minute**
instead of every 15 minutes on GitHub, because a listing's price moves
within minutes. `news_listings_bot.py` runs all the time on the launch
bot's server (the `news-listings` service; setup: Part J of
[`deploy/LAUNCH_SERVER_SETUP.md`](deploy/LAUNCH_SERVER_SETUP.md)).

- **Its sources:** the `[[news.sources]]` marked `runs_on = "server"`:
  Binance's new-listing list, Kraken's blog, and new coins in the public
  market lists of Coinbase, Upbit and OKX (a coin that wasn't on a list
  before is a new listing; the first read only saves the list). GitHub no
  longer reads these; all the other news sources stay on GitHub.
- **Exactly the news strategy's rules:** the same code and settings (`[news]`):
  the coin matching, every check, the AI check (Claude Haiku 4.5), $10
  buys, 1% costs and the same exits (half at +50%; the rest at -20%, 25%
  below the peak, or after 7 days).
- **Its own files:** `data/news-listings/` (`journal.csv`, `positions.json`,
  `candidates.csv`, `ai_verdicts.csv`, `entries.csv`, `health.json`), pushed
  to GitHub once an hour. It opens no GitHub issues.
- **Limits:** each source once a minute; CoinGecko only for a new listing,
  plus the open positions' prices every 15 minutes, within its own count of
  4,000 calls a month (GitHub's news strategy now stops at 5,500, so both
  together stay under the free plan's 10,000 even with one key); the AI
  check at most 50 times a day. Settings: `[news_listings]`.
- **The Claude API key** lives on the server in a file only root can read,
  handed to this one service by systemd (Part J2). Without it, the
  rule-based checks decide, as always.
- **Updates itself** like the other server bots ("automatic restart" in
  `journalctl -u news-listings`).
- **In the daily comparison:** the **news (listings)** column, next to news,
  and health rows for the bot (last good run, runs, CoinGecko calls, last
  push), each of its sources, and its AI check.

### "news (listings) fast": the same listings, exits within hours

Exchange-listing gains tend to come in the first minutes to hours and fade
within a week or two, while news (listings) holds up to 7 days. **news
(listings) fast** buys every news (listings) signal at the same moment and
the same price, but exits fast:

- sell half at **+20%**;
- the rest **10% below its highest price** since the buy;
- everything left at **-10%** from entry, or after **6 hours** at most.

The same $10 buys and 1% costs. Its prices are checked every 2 minutes while
it holds something (CoinGecko, in news (listings)' 4,000 a month). Its own
`journal.csv`, `positions.json` and `entries.csv` in
`data/news-listings/fast/`, its own column in the daily comparison and a
health row. news (listings) itself is unchanged, so the two can be compared
side by side. Settings: `[news_listings.fast]`.

## The "momentum" strategy (new launches rising fast, on your own server)

**The 30%/2 min and 50%/3 min variants were stopped on 2026-10-05** (losing
even before costs): no new buys, their journals kept. The 100%/5 min variant
keeps running.

It tests whether buying a brand-new pump.fun launch **after** it starts
rising fast on real buying works better than sniping it at creation.
`momentum_bot.py` runs all the time on the launch bot's server (the
`momentum-bot` service; setup: Part I of
[`deploy/LAUNCH_SERVER_SETUP.md`](deploy/LAUNCH_SERVER_SETUP.md)).

- **Data:** every pump.fun trade, launch and graduation, live from Solana's
  **free public RPC** (one read-only `logsSubscribe`; no key, no wallet;
  `screener/pumpfeed.py`). A backup free endpoint is in `ws_urls`: after a
  drop the bot reconnects within about a second, and moves to the next
  endpoint when one keeps failing; the health check shows disconnects per
  hour and per endpoint, and the time the feed was down. Prices: each trade's bonding-curve price;
  DexScreener once a held token stops trading for a minute or graduates.
  SOL's price: DexScreener.
- **Three variants, side by side**, each with its own journal in
  `data/momentum/<name>/`: a rise of **+30% within 2 minutes**, **+50% within
  3 minutes**, **+100% within 5 minutes** (from the window's lowest price).
- **The other entry rules** (in the same window, numbers in `[momentum]`):
  at least **15 buys** from at least **10 different wallets**, buys
  outnumbering sells at least **1.5 to 1**, at least **3 SOL of net
  buying**, **no wallet over 30%** of the SOL bought, the **creator hasn't
  sold**, the launch is **1-10 minutes old**, still on the curve and under
  80% of the way to graduating, and not skipped by the launch bot's
  **copycat-name** and **dead-creator** rules (from launches this bot has
  seen).
- **The fill:** at the first trade at least **5 seconds** after the signal,
  at that trade's price (no trade within a minute = no buy). **No new buys
  while the feed is down**, nor on a signal whose window or wait for the fill
  overlaps a feed outage (missed trades would make the counts wrong).
- **Limits per variant:** at most **10 buys an hour** and **20 open**.
- **Costs and exits: the launch bot's** (`[launch.paper_trading]` and its
  90s speed's priority fee and slippage): **$5** buys, 1% bot fee,
  pump.fun's fee, 5% slippage and a priority fee on every trade; sell half
  at **2x**, everything left at **-30%** or **30 minutes** after the buy.
- **Records:** each variant's `journal.csv`, `positions.json` and
  `entries.csv` (the rise, buys, sells, buyers, net SOL, biggest wallet's
  share, curve progress, seconds after creation and after the signal, and
  Jupiter's organic score, read at the signal), `near_misses.csv` (once per
  launch and variant: the rise came but another rule failed, or everything
  else passed and the rise reached 80% of the target, with every value and
  what failed, for tuning), `stats.json` (hourly counts) and `health.json`.
  The hourly push sends them; the daily comparison shows **momentum
  30pct-2min / 50pct-3min / 100pct-5min** and a health row.
- **Updates itself** like the other server bots ("automatic restart" in
  `journalctl -u momentum-bot`).
- **Caveat:** first-minute pumps are often bots buying their own launch or
  bundled buys, and paper fills here are generous: expect real results to
  be worse than paper.

## Trade feed probe (a 2-hour measurement, no trading)

`trade_feed_probe.py` checks whether Solana's **free public RPC** can be the
live trade feed for a planned "momentum on launches" strategy (PumpPortal's
trade feed now needs a wallet). It subscribes read-only to pump.fun's
program logs and records only numbers: trades per second, bandwidth (and
what Helius would charge for it), disconnects, silent gaps, the feed's
delay, and DexScreener's listing delay and price lag for a few sampled
launches, plus its own CPU and memory. No trades are made and no trade data
is kept: only `data/trade-feed-probe/summary.json`. It stops by itself after
2 hours. Run it on your server (Part H of
[`deploy/LAUNCH_SERVER_SETUP.md`](deploy/LAUNCH_SERVER_SETUP.md)); the
"Trade feed probe (short test)" workflow runs it for 5 minutes on GitHub.

## The "launch" strategy (a fourth paper strategy, on your own server)

**All three speeds were stopped on 2026-10-05:** no new buys; their last
positions close within 30 minutes (the time stop), and then the launch-bot
service can be turned off (Part K of the server guide). Their journals and
files are kept. (Without the trade feed, the 5s and 30s speeds bought at the
creation price, so those results are not realistic.)

It tests whether **sniping** brand-new pump.fun tokens could work. Because a
check every few minutes is far too slow for launches, it doesn't run on
GitHub: `launch_bot.py` runs all the time on a small server (about
$5/month) and pushes its results here about once an hour. Setup, step by
step: [`deploy/LAUNCH_SERVER_SETUP.md`](deploy/LAUNCH_SERVER_SETUP.md).

- **Data:** PumpPortal's **free** real-time data feed only: new tokens and
  migrations. PumpPortal's stream of each token's trades needs an API key and
  a funded wallet, so the bot doesn't use it. It never uses PumpPortal's
  trading API, a wallet or a private key. Prices: the bonding-curve price in
  the creation message, then DexScreener (every 20 seconds) once that price
  is a minute old or the token graduates. So the 5s and 30s buys are at the
  creation price, and exits react to DexScreener's price, not to each trade.
- **Which launches** (numbers in `[launch]` in `config.toml`): it skips
  copycat names (an earlier launch with the same name or symbol in the last 7
  days), creators with a dead earlier token (older than an hour and never
  graduated), and stops at **10 launches an hour**. These checks only know
  launches the bot itself has seen, so they get better the longer it runs.
- **First-block flag:** a launch is flagged if the creator bought in the
  creation transaction or other wallets bought in the first ~1 second.
  Without the trade feed only the creator's buy is known, so in practice
  flagged means the creator bought. Flagged launches are still traded
  (`skip_flagged = false`), so flagged and clean launches can be compared
  later.
- **Three speeds, side by side**, each with its own journal in
  `data/launch/5s/`, `30s/` and `90s/`: the same launch is paper-bought **$5**
  at 5 seconds (sniper-bot speed), 30 seconds and 90 seconds (human speed)
  after creation, at the bonding-curve price at that moment. At most **30
  open** per speed.
- **Costs on every buy and sell:** a priority fee (0.003 / 0.001 / 0.0005 SOL
  for 5s / 30s / 90s), a **1% bot fee**, pump.fun's fee (0.95%) and **5%
  extra slippage**. On $5, a round trip at a flat price loses about $1.30 at
  5s, so a launch has to rise roughly 30% before the 5s speed breaks even.
- **Exits:** sell half at **2x**; everything left at **-30%** or **30
  minutes** after the buy, whichever comes first.
- **Results:** each speed's `journal.csv`, `positions.json` and
  `entries.csv` (when it bought, dev buy %, flag; the buys/sells so far,
  first-block buyers and price change since creation, in the 5-minute/1-hour
  columns, need the trade feed, so they're blank. Before October 2026 they
  were saved as 0, which meant "not known", too; Jupiter's organic score,
  looked up every 10 seconds from when a launch is selected, with
  `jupiter_checked_seconds_after_creation` saying how old the token was at
  that reading), plus `data/launch/launches.csv` (every launch it considered
  and why) and `stats.json` (hourly counts: launches seen, skipped by reason,
  flagged, traded). The daily comparison shows **launch 5s / 30s / 90s** next
  to the other strategies.
- **Updates itself:** when the hourly push brings new code the bot uses
  (`screener/autorestart.py`), it saves everything, exits and is started
  again by systemd with the new code, so nobody has to restart it after a
  merge. Each one is logged as "automatic restart" (`journalctl -u
  launch-bot`). Changes to other strategies don't restart it.
- **Caveat:** the simulation is still generous. A real buy at 5 seconds can
  fail or land later, and real slippage in the first seconds can be far
  worse than 5%.

## The "news" strategy (a fifth paper strategy)

It buys an established coin right after **real, official news** about it,
before the price has moved, like The Clearing House choosing Quant on
September 24, 2026. **No X, no AI**: only official sources and rule-based checks.
Settings are under `[news]` in `config.toml`.

**Sources** (`[[news.sources]]`, read every 15 minutes):
- press-release wires: PR Newswire (all news, plus its crypto and blockchain
  lists), GlobeNewswire (public companies' releases, plus releases tagged
  cryptocurrency or blockchain) and Business Wire (all news); releases that
  don't mention crypto are skipped;
- exchanges: OKX's new-listing announcements (Bybit's are turned off,
  `enabled = false`: Bybit refuses GitHub's US servers). The exchange
  listings that move fastest (Binance's new-listing list, Kraken's blog, and
  new coins in the public market lists of Coinbase, Upbit and OKX) are
  marked `runs_on = "server"`: the **news (listings)** bot on your server
  reads them every minute instead (below);
- the SEC: its press releases (only those about crypto) and EDGAR's latest
  S-1 filings by funds ("Canary PEPE ETF"): a new crypto fund's first S-1
  counts as a catalyst, an amendment (S-1/A) doesn't;
- project blogs, each tied to its coin: Quant, Chainlink (its press
  releases: its blog has no feed), Solana, Ripple and Avalanche (read from
  their blog pages, which have no feed), Hedera and Stellar.

Each run's log shows which sources worked (`ok` / `FAIL` with the reason),
and the latest status is saved in `data/news/positions.json`. A feed with no
items at all counts as `FAIL`: Business Wire, for one, answers a wrong
address with an empty feed. Common mistakes in hand-made feeds (HTML
entities like `&nbsp;`, a bare `&`, no character set) are repaired before
reading. The health check has a row for every source: failing, turned off,
or working but with nothing new for longer than usual (4 days for a press
wire, 14 for an exchange or the SEC's press releases, 30 for a blog; set
`stale_days` on a source to change it), which usually means its address
changed. To test every source by hand, run the **News sources check**
workflow (Actions tab), or `python -m screener.news --check-sources`; it
also runs by itself when the news code or `config.toml` changes. A source
that fails is tried again 10 seconds later; one source still failing is a
yellow warning naming it, and the check only fails (red) when two or more
do (`--allow-failing N` changes that).

**Which coin?** CoinGecko's top 500 coins. A coin counts when its name
appears with the right capitals. One-word names that are also everyday words
("Flow", "Core") also need their ticker, like `(FLOW)` or `$FLOW`, or a word
like Network/Protocol/Token after the name. Bitcoin and Ether mentioned in
passing don't count when another coin is the subject. Press releases that
don't mention crypto at all are skipped. Also:
- exchange headlines are read for tickers ("WOJAK is available for
  trading!", "OKX will launch GRVT/USD", "Binance Will List Hyperliquid
  (HYPE)"); a ticker outside the top 500 is looked up in CoinGecko's full
  list of about 20,000 coins (one extra call, only on runs that need it),
  taking the coin named in the headline or else the biggest with that ticker;
- a company named after a coin ("BNB Plus Corp.", "Solana Company Inc.") is
  not the coin, unless the coin's ticker is given too; a project's own
  company ("Ondo Finance Inc.") still counts;
- a release and its translations are checked once, in English: same release
  number in the address (GlobeNewswire, Business Wire), or same wire, minute
  and company (PR Newswire);
- fund filings are matched on the fund's name in any capitals.

**The checks** (all must pass):

| Check | Passes when |
|---|---|
| Fresh news | published in the last 3 hours |
| One coin | exactly one coin is named |
| Not a stablecoin | not a stablecoin or a wrapped/staked token |
| Not paid content | no "sponsored", "paid content", "advertorial" |
| Catalyst wording | "selects", "partners with", "launches", "goes live", "acquires", "approved"... (exchanges: "will list", "listing", "available for trading", "trading starts"...; SEC filings: a fund's first "S-1") |
| No hype wording | not "exploring", "in talks", "potential partnership", "rumor", "memorandum of understanding", "price prediction", "airdrop"... |
| Not bad news | not "hack", "exploit", "delist", "lawsuit", "investigation"... |
| Named counterparty | a well-known institution is named: a bank, payment network, big exchange, tech company or regulator (exchange announcements count the exchange itself, SEC filings the SEC) |
| Big enough | market cap $20M+ and 24h volume $1M+ |
| Not already moved | up less than 15% in the last hour and 40% in 24h |
| Not bought recently | no buy of the same coin in the last 3 days |

**Every candidate is logged** to `data/news/candidates.csv`: the time, source,
headline, link, coin, PASS or FAIL, the failed checks with reasons, and every
check's result. A candidate is any new item that names a coin. Crypto-related
items that name no coin are saved (headline, source, link) to
`data/news/unmatched.csv`, so you can check whether the coin matching misses
real candidates; items not about crypto at all are only counted in the run
log. The first time it reads a
source (including one that just started working), it skips that feed's older
backlog and only checks news from the last 3 hours.

**Buying:** $10 at CoinGecko's price. **Exits** suit moves that take days:

- sell **half at +50%**;
- sell everything left at **-20%** from entry,
- or **25% below the highest price** since entry (trailing stop),
- or after **7 days**.

Costs are assumed at 1% per full trade (bigger, exchange-listed coins). Each
buy gets a GitHub issue titled **PASSED (news): SYMBOL**, labelled
`strategy: news`, with the headline, source, link and exit levels. The results
are in `data/news/journal.csv` and in the daily comparison.

**CoinGecko free plan:** sign up at <https://www.coingecko.com/en/api/pricing>
(the free **Demo** plan, 10,000 calls a month), create a key, and add it as the
repository secret **`COINGECKO_API_KEY`** (Settings → Secrets and variables →
Actions → New repository secret). Without a key the bot tries CoinGecko's
public API, which is often rate-limited on GitHub's shared servers. The bot
counts its calls and stops looking up new candidates at 9,000 a month. It
only looks up the coin list on runs with crypto news to check, which should
stay well under that.

**AI second opinion (Claude Haiku 4.5):** every crypto-related item (each
candidate, and each crypto item that names no coin; never the releases about
other things) is also sent to Claude Haiku 4.5 through Anthropic's API. It
answers which coin the item is about, whether the headline is a real
positive catalyst, whether the rule-based coin match looks wrong (a company
named after a coin, the wrong coin with the same ticker), and whether it
repeats a headline from the last 24 hours. Every verdict is saved next to the
rule-based result in `data/news/ai_verdicts.csv` (with an `agree` column),
shown under each candidate in the run log, and added to the buy's GitHub
issue, so you can compare the two over time.
- **It decides nothing by default:** the rule-based checks alone decide the
  paper buys. To also require the AI's yes, set `must_pass = true` under
  `[news.ai]` in `config.toml`.
- **Key:** create an API key at <https://console.anthropic.com/settings/keys>
  and add it as the repository secret **`CLAUDE_API_KEY`** (Settings →
  Secrets and variables → Actions → New repository secret). No wallet is
  involved; the AI only sees the headline, a short summary, the source's
  name and the rule-based match.
- **Cost:** at most `daily_limit` checks a day (100, UTC), each about
  $0.001-0.002, so at most about $0.20 a day; most days use far fewer. The
  run log and the health check show today's count.
- **If anything goes wrong** (no key, the limit reached, an API error), the
  item is logged as "not checked" and the rule-based checks carry on
  exactly as before. The health check's "news: AI check" row says which.
- To test the key, run the **News sources check** workflow: it sends one
  known headline (The Clearing House choosing Quant) and shows the verdict.

**What it can't do:** it sees news up to 15–20 minutes late (the schedule plus
GitHub's delays), so catalysts that move within seconds, like big exchange
listings, will often already be priced in, and the "Not already moved" check
will skip them. Keyword checks can't understand nuance: a real deal can fail
for the wording it uses, and hype can slip through. The candidate log is there
so you can see which.

## The "robinhood" strategy (a sixth paper strategy, Robinhood Chain)

Robinhood Chain (chain 4663, live since July 2026) is an EVM chain with its
own memecoin launchpads. This strategy only trades tokens from **Pons** and
**Pools.trade** once they trade in a **Uniswap pool that is 30 minutes to 6
hours old**: graduated tokens, not the Pons bonding curve. What the free
sources return was measured first with `robinhood_probe.py` (below). Its
results are in `data/robinhood/` and its column in the daily comparison;
issues are titled **PASSED (robinhood): SYMBOL** with the label
`strategy: robinhood`.

- **New pools:** GeckoTerminal lists the launchpads as DEXes
  (`pons-v2-dex` = graduated Pons pools, `uniswap-pools-trade` = Pools.trade).
  It answers "too many requests" after a few calls a minute from GitHub, so
  each run makes at most 2 calls, 10 seconds apart (Pools.trade's list and
  the newest pools), and tries once more 20 seconds after a "too many
  requests". Pools it lists go on a watchlist and are checked once they're
  30 minutes old, so a pool missed one run is still caught later. Pons'
  graduations come from the chain (below): every one goes on the watchlist,
  named from DexScreener (its pool too, when it's checked), so Pons' own
  GeckoTerminal list is only read when there's a call to spare. Every Pons
  graduation gets the same checks. The health check shows how many runs got
  a "too many requests" over 24 hours.
- **Prices:** DexScreener, from the same pool (DexScreener doesn't list the
  Pons curve itself, so it's only used once a token has a Uniswap pool).
- **Checks** (each pool at most once an hour; a later check only runs when the
  ones before it passed, to stay within the free limits; anything unknown
  counts as a fail):
  - pool age 30 min to 6 h; liquidity at least $10,000 on Pons, $5,000 on
    Pools.trade
  - market (the main strategy's checks, with this chain's numbers): market
    cap at least $25,000, not down more than 50% in 24 hours, and more buys
    than sells in the last hour
  - not a copycat: no other Pons or Pools.trade token with the same name or
    symbol graduated before it in the last 7 days. Ignored: tokens that
    graduated after it, and clones whose liquidity is 90% or more of their
    market cap (real graduations have about 30-60%). Of the ones left, the
    earliest graduation is the original (`copycat_of`). The launchpad tokens
    are the ones GeckoTerminal has listed and the Pons graduations read from
    the chain (named from DexScreener), remembered for 7 days; liquidity
    and market cap are DexScreener's (search) when it has them, else
    GeckoTerminal's
  - GoPlus: not a honeypot, not mintable, no hidden owner, the owner can't
    change balances, no blacklist
  - Pons tokens: holders rebuilt from the token's own Transfer events on the
    public RPC (the whole history since it was minted): the creator (whoever
    sent the transaction that minted it) holds under 5%; the top 10 hold under
    30%, leaving out pools (Uniswap v4's PoolManager), the launchpad's
    contracts, the curve and burn addresses; and no cluster of 5+ wallets with
    near-identical balances holding 3%+ of the supply together (bundled buys).
    When the RPC says "too many requests" (429) it waits and tries again (5,
    10, 15 seconds) before calling the holders unknown. Pools.trade tokens
    skip these.
- **Costs** on every buy and sell: the pool fee (Pools.trade 0.25%; Pons 1%,
  assumed: its graduated pools' fee isn't published), 2% slippage and $0.05 of
  gas per transaction.
- **Exits:** the same as the main strategy: sell half at +50%; the rest at
  -30%, 40% below the peak, or after 48h if it's still within ±10% of entry.
- **Records:** `entries.csv` (every check value at the buy: pool, age,
  liquidity, GoPlus fields, creator, creator %, top 10 %, holders, the heaviest
  equal-balance cluster, and the fee, slippage and gas used; blank = unknown)
  and `candidates.csv` (every pool checked, PASS/FAIL and why; a new row only
  when a pool's result changes). The health section has a row for each data
  source.
- **Graduations from the chain:** the Pons tokens that graduated in the last
  24 hours, from Pons' graduation event (read-only `eth_getLogs`: the whole
  day the first time, then only the new blocks each run, usually one call; a
  "too many requests" is never waited for, the read just carries on next
  run, so the holder checks keep the RPC's patience). The run log shows how
  many graduated, how many GeckoTerminal listed, and the ones found only on
  the chain (which are checked from there).
- **Try it:** `python -m screener.robinhood` does one run against the real
  sources with the results in a temporary folder (nothing is saved). The
  "Robinhood Chain probe" workflow does the same on GitHub.

## Running automatically on GitHub

`.github/workflows/screener.yml` runs the screener every 5 minutes on GitHub
Actions (and you can start a run by hand from the **Actions** tab). GitHub
sometimes starts scheduled runs late, or drops them for hours, when it's
busy. To make the runs reliable, your launch-bot server can start the run
every 10 minutes when none ran in the last 8 (`deploy/trigger_paper_run.py`,
with a token that can only start workflows: see Part F of
[`deploy/LAUNCH_SERVER_SETUP.md`](deploy/LAUNCH_SERVER_SETUP.md)); GitHub's
schedule stays on as a backup. The same trigger also starts the **Daily
strategy comparison** after 00:30 UTC when yesterday's comparison issue
hasn't been posted (GitHub skipped its 00:07 run). Runs never
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

## Automatic repair (issues, and fixes for you to review)

Once a day (00:37 UTC, `.github/workflows/repair.yml`), each problem in the
daily health check gets a GitHub issue labelled `repair`, with the check, what
it said, the strategy's last error, failed runs and the files and settings to
look at. If the issue is still open the next day, only its "Last seen" line is
updated.

- **Left to you** (`needs-you`, and the issue says why): problems on your
  server (launch, main (1 min), momentum, news (listings)), which need the
  server's logs; and secrets, settings or limits (a missing key, a paused
  Helius budget, a daily limit reached).
- **Everything else** (`repair-ready`): Claude Code runs on GitHub with the
  `CLAUDE_API_KEY` secret, reads the issue, looks for the cause and, if it
  finds one in the code, makes the smallest fix and runs the tests. The
  workflow then opens a **draft pull request** ("Fixes #N", with the test
  result and the cost) or, when no code change is needed, explains why on the
  issue. **Nothing is ever merged automatically.** Claude Code can only read
  and edit the code and run the tests: no internet, no pushing, never `data/`
  or the workflow files, no wallet, no keys.

**Limits** (`[repair]` in `config.toml`): one attempt per issue (if you close
an issue and the problem comes back, it gets a new issue and a new attempt);
at most `max_attempts_per_day` (1) a day; no attempt once the day's repairs
cost `max_daily_usd` ($3); each attempt stops after `max_turns` (30) steps or
20 minutes. Model: `claude-sonnet-5-5` ($2 / $10 per million tokens in / out):
usually $0.60-1.50 an attempt, about $2 at most. Opening issues costs nothing.

**Setup (once):** Settings > Actions > General > Workflow permissions: tick
"Allow GitHub Actions to create and approve pull requests". And on
console.anthropic.com, set a monthly spend limit for the key (the hard
ceiling). To try it now: Actions > Automatic repair > Run workflow (leave the
issue number empty, or give one waiting for its attempt).

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
| `repair.py`, `screener/repair.py` | The automatic repair: issues for health problems, Claude Code's attempt, the draft pull request |
| `screener/convergence.py` | The convergence strategy: Helius reads, credit budget, wallet scoring, signals and exits |
| `screener/news.py` | The news strategy: feeds, coin matching, the checks, the candidate log and exits; `--check-sources` tests every source |
| `screener/news_ai.py` | The news strategy's AI second opinion (Claude Haiku 4.5): verdicts, the daily limit and the fallback; run it to test the key |
| `screener/launch.py`, `launch_bot.py` | The launch strategy and the program that runs it on your server |
| `screener/momentum.py`, `screener/pumpfeed.py`, `momentum_bot.py` | The momentum strategy, pump.fun's on-chain events, and the program that runs it on your server |
| `trade_feed_probe.py` | A 2-hour, read-only measurement of the free Solana RPC as a pump.fun trade feed (no trading) |
| `main_1min.py` | The main (1 min) strategy: main's checks and exits every minute, on your server |
| `news_listings_bot.py` | The news (listings) strategy: the news strategy's exchange listings every minute, on your server |
| `screener/robinhood.py` | The robinhood strategy: GeckoTerminal watchlist, DexScreener prices, GoPlus and RPC holder checks, costs and exits |
| `robinhood_probe.py` | Research only: reports what each free data source returns for Robinhood Chain (run by the "Robinhood Chain probe" workflow; no trading) |
| `deploy/` | Server setup guide, systemd services, the hourly push script for the launch bot, and the paper-run trigger that starts the Paper trading run every 10 minutes (and the Daily strategy comparison when yesterday's issue is missing) |
| `screener/health.py` | The health section of the daily comparison, and `data/health.json` |
| `screener/compare.py`, `compare.py` | The side-by-side comparison of all strategies, with Helius credit use |
| `screener/demo.py` | Made-up tokens for `--demo` and the tests |
| `tests/` | Automated checks that the rules work. Run with `python -m unittest -v` (first `pip install -r requirements-launch.txt` too: the launch bot's tests need it) |
| `.github/workflows/screener.yml` | Runs all strategies every 5 minutes on GitHub |
| `.github/workflows/daily-comparison.yml` | Posts the daily comparison issue |
| `.github/workflows/news-sources.yml` | News sources check: reads every news source once and shows what it gives (read-only) |

## Important caveats

- Memecoins are extremely risky. Most go to zero. Passing these checks
  makes a token *less likely* to be an obvious scam, not safe.
- Paper results are more optimistic than real trading: real slippage on small
  tokens can be much worse than 3%, and prices can crash between runs.
  Exits only happen when you run the program, so a stop loss at -30% might
  actually trigger at -60% if the price fell a lot while it wasn't running.
- This is an educational tool, not financial advice.
