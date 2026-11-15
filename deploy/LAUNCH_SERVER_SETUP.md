# Setting up the launch bot on a small server

This puts the **launch** paper strategy (`launch_bot.py`) on a small cloud
server that runs all the time. It listens to PumpPortal's free data feed,
paper-trades new pump.fun launches at three speeds, and pushes the results to
this repository about once an hour. Optionally it also runs the **main (1
min)** strategy (Part G): the main strategy's checks every minute.

**Paper trading only.** Nothing here uses a wallet, a private key or a seed
phrase, and nothing can buy or sell anything. **Never put a wallet or a private
key on this server.** The only secrets on it are GitHub tokens limited to
this repository: one that can read and write its files (Part C), and,
optionally, one that can only start its workflows (Part F); plus, optionally,
a Claude API key for the news listings bot's AI check (Part J), readable by
root only. None of them can move or trade anything.

It takes about 30–45 minutes the first time. Copy each command exactly.
Lines starting with `#` are explanations, not commands.

---

## Part A. Rent the server (Vultr, about $5/month)

**Why Vultr:** it accepts Visa/Mastercard, PayPal and crypto, so it's the
easiest to pay from Egypt, and its 1 GB server is about $5/month, billed by
the hour. (DigitalOcean, about $6/month for 1 GB, is a good second choice.
Hetzner is similar in price but requires ID verification and sometimes
declines new accounts.) Prices and payment options change, so check the
current ones when you sign up.

**Paying from Egypt:** an Egyptian Visa or Mastercard usually works if
**online/international payments are turned on** for the card (check in your
bank's app or call the bank). PayPal works too. Vultr may ask for a small
first payment to activate the account.

### A1. Make an SSH key on your own computer (once)

An SSH key is how you'll log in to the server, instead of a password.

**Windows 10/11:** open **PowerShell**. **Mac or Linux:** open **Terminal**. Then:

```
ssh-keygen -t ed25519 -C "launch-bot"
```

Press Enter to accept the file name, then type a passphrase (twice). The
passphrase protects the key if someone gets your computer, so pick one you'll
remember.

Show the **public** half of the key (this part is safe to share):

- Windows (PowerShell): `type $env:USERPROFILE\.ssh\id_ed25519.pub`
- Mac/Linux: `cat ~/.ssh/id_ed25519.pub`

Copy the whole line it prints (it starts with `ssh-ed25519`).

### A2. Create the server

1. Sign up at **https://www.vultr.com** and add a payment method.
2. Click **Deploy** (or **Deploy +**) and choose **Cloud Compute – Shared CPU**.
3. **Location:** any; Frankfurt or New York are fine.
4. **Image:** **Ubuntu 24.04 LTS x64**.
5. **Plan:** **Regular Performance, 1 vCPU, 1 GB RAM** (about $5/month).
   Don't pick the cheaper IPv6-only plan: GitHub needs IPv4.
6. **SSH Keys:** click **Add New**, paste the line from step A1, name it
   `my-computer`, save, and make sure it's selected.
7. Turn **off** extras you don't need (automatic backups cost extra).
8. **Hostname:** `launch-bot`. Click **Deploy Now**.
9. After a minute or two, the server shows as **Running**. Copy its **IP
   address** (like `203.0.113.10`). Below, replace `YOUR_IP` with it.

---

## Part B. Log in and lock the server down

### B1. First login (as root)

```
ssh root@YOUR_IP
```

Type `yes` if it asks about the fingerprint, then your key's passphrase.

### B2. Update everything

```
apt update && apt -y upgrade
```

If a purple screen asks about restarting services or a config file, press
Enter to accept the default.

### B3. Make a normal user called `bot`

The bot shouldn't run as root (the all-powerful account).

```
adduser bot
```

Give it a strong password (you'll need it for `sudo`); press Enter for the
other questions. Then:

```
usermod -aG sudo bot
rsync --archive --chown=bot:bot ~/.ssh /home/bot
```

**Test it before going on:** open a **second** PowerShell/Terminal window on
your computer and run:

```
ssh bot@YOUR_IP
```

If that works, keep using this `bot` window and close the root one.

### B4. Allow SSH key logins only (no passwords, no root)

```
sudo tee /etc/ssh/sshd_config.d/00-hardening.conf > /dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
sudo sshd -t && sudo systemctl restart ssh
```

(The file name starts with `00-` on purpose: SSH uses the first value it
reads, so this has to come before the provider's own settings.)

Check that it worked: in another window, `ssh root@YOUR_IP` should now be
**refused**, and `ssh bot@YOUR_IP` should still work.

### B5. Turn on the firewall

Only SSH is allowed in. The bot only makes outgoing connections, so it
needs nothing open.

```
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

Type `y` when asked. `ufw status` should show `OpenSSH ALLOW`.

### B6. Automatic security updates

```
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

Choose **Yes**. Optional, so updates that need a restart get one at 04:00
(the bot starts again by itself):

```
echo 'Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";' | sudo tee /etc/apt/apt.conf.d/52auto-reboot
```

---

## Part C. Make the GitHub token (repository contents only)

1. On GitHub, click your profile picture → **Settings** → **Developer
   settings** (bottom of the left menu) → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
2. **Token name:** `launch-bot server`. **Expiration:** 90 days.
3. **Resource owner:** your account (`Asayed36`).
4. **Repository access:** **Only select repositories** → pick
   **trading-bot**.
5. **Permissions → Repository permissions → Contents:** **Read and write**.
   Leave everything else as **No access** (GitHub adds *Metadata: Read-only*
   by itself; that's normal).
6. Click **Generate token** and copy it (it starts with `github_pat_`).
   GitHub shows it only once.

This token can only change files in this one repository. It can't touch
your other repositories, your account settings, or anything else.

---

## Part D. Install the bot

All as the `bot` user.

```
sudo apt install -y git python3-venv
git clone https://github.com/Asayed36/trading-bot.git ~/trading-bot
cd ~/trading-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-launch.txt
```

Save the token so the push job can use it. This asks for it without showing
it, and doesn't keep it in your command history:

```
read -rsp "Paste the GitHub token, then press Enter: " TOKEN; echo
printf 'https://x-access-token:%s@github.com\n' "$TOKEN" > ~/.git-credentials
chmod 600 ~/.git-credentials
unset TOKEN
git config credential.helper store
```

Give git a name and email for the result commits. Without them git can't
make a commit, and a push can get stuck half-way (the push script sets them
too, but set them here so every git command on the server works):

```
git config user.name "launch-bot"
git config user.email "launch-bot@users.noreply.github.com"
```

Try the bot for 2 minutes:

```
.venv/bin/python launch_bot.py --test
```

You should see `connected to PumpPortal` and one or two `PumpPortal says:`
lines (its replies to the subscriptions), then after 2 minutes a short
summary: launches seen, skipped (and why), paper buys at each speed, and the
feed messages by type (`create` and `reply`, sometimes `migrate`; never
`buy`/`sell`, because the bot doesn't subscribe to trades: PumpPortal's
trade stream needs an API key and a funded wallet).
A test run saves **nothing** to `data/launch`: its results go to a temporary
folder that's deleted afterwards. (Don't test with
`timeout 60 .venv/bin/python launch_bot.py`: that writes real results, stops
before the 90s speed can buy, and uses up the hourly limit of new trades.)

Turn it on for good, with the hourly push:

```
sudo cp deploy/launch-bot.service deploy/launch-push.service deploy/launch-push.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now launch-bot launch-push.timer
```

Check on it:

```
systemctl status launch-bot          # should say "active (running)"
journalctl -u launch-bot -f          # live log; Ctrl+C to stop watching
systemctl list-timers launch-push*   # when the next push happens
```

Within an hour or two you should see commits called **"Launch paper results
…"** on GitHub, and the next daily comparison issue will include the
**launch 5s / 30s / 90s** columns.

---

## Part E. Looking after it

- **Bot updates are automatic** (after a pull request is merged): the hourly
  push brings the code on the server up to date with GitHub (like
  `git pull`). Each bot notices when that changed code it uses (its own
  files, or its own settings in `config.toml`), saves everything, exits by
  itself, and systemd starts it again with the new code about 10 seconds
  later. You don't need to do anything. Changes to other strategies' code
  or settings don't restart them. See every automatic restart with:
  `journalctl -u launch-bot -u main-1min -u momentum-bot -u news-listings --no-pager | grep "automatic restart"`.
  (Any of your own edits to a file that also changed on GitHub are replaced
  by GitHub's version.)
- **Two things still need you, and the pull request will say so when they
  happen:** a change to a `.service` file (copy it and run
  `sudo systemctl daemon-reload`, as in Part D/G), or a new Python package
  in `requirements*.txt` (`.venv/bin/pip install -r requirements.txt -r
  requirements-launch.txt`). The bots never get sudo rights to do these
  themselves.
- **Test the push by hand:** `~/trading-bot/deploy/push_results.sh`. It
  never uses a rebase, and if an older version left a rebase or cherry-pick
  stuck, it clears it first and still pushes the newest results. Each
  results folder is added on its own: if one can't be added (say
  `.gitignore` doesn't allow it), it prints `WARNING: could not add ...`,
  still pushes the others and ends with exit code 3, so
  `systemctl status launch-push` shows it as failed. Check the
  push log with `journalctl -u launch-push -n 20`.
- **Restarts:** the bot counts each start as `bot started` in
  `data/launch/stats.json`. A launch that was being followed when the bot
  stopped keeps the positions it had, but the speeds it hadn't reached yet
  (say 90s) don't buy it after the restart.
- **Token expired** (after 90 days): make a new one (Part C) and run the
  `read -rsp …` lines in Part D again.
- **Pause:** `sudo systemctl stop launch-bot`. **Turn off for good:**
  `sudo systemctl disable --now launch-bot launch-push.timer`
- **Paper-run trigger** (Part F): see what it did with
  `journalctl -u paper-run-trigger -n 20 --no-pager`. Pause it with
  `sudo systemctl disable --now paper-run-trigger.timer` (GitHub's own
  schedule keeps running). When its token expires the log says "the token has
  expired or lacks permission": make a new one (F1) and repeat F2. It also
  starts the Daily strategy comparison when yesterday's issue is missing
  after 00:30 UTC (`started Daily strategy comparison ...` in the log).
- **Main (1 min)** (Part G): `journalctl -u main-1min -n 30 --no-pager`
  shows one line a minute. Pause it with `sudo systemctl stop main-1min`;
  turn it off for good with `sudo systemctl disable --now main-1min`.
- **News (listings)** (Part J): `journalctl -u news-listings -n 30 --no-pager`
  shows one line a minute. Its Claude API key is in
  `/etc/trading-bot/claude_api_key` (root only); see J2 to change or remove it.
- **Stop paying:** in Vultr, **destroy** the server. Just stopping it keeps
  billing.
- **Never** install a wallet, paste a private key or seed phrase, or use
  PumpPortal's trading API on this server. This bot doesn't need any of that,
  and nobody should ask you for it.

---

## Part F. Start the Paper trading runs from the server (optional)

GitHub's own schedule for the **Paper trading run** (every 5 minutes) is
best-effort: when GitHub is busy it drops scheduled runs, sometimes for hours.
This makes the server ask GitHub to start the run every 10 minutes, unless
one is queued or running, or one started in the last 8 minutes (then GitHub's
schedule did its job and nothing happens). GitHub's schedule stays on as a
backup. The run itself is the normal one, on GitHub: nothing about the
strategies changes.

The same trigger also watches the **Daily strategy comparison**: after 00:30
UTC, if yesterday's "Daily comparison: YYYY-MM-DD" issue isn't on GitHub yet
(GitHub skipped its 00:07 run), it starts that workflow, at most once an hour
and never while one is queued or running. The issue lookup needs no extra
permission: if the token isn't allowed to read issues, it asks again
without a token, which works because the repository is public.

### F1. Make a second GitHub token (start workflows only)

Keep it separate from the Part C token, so each can be revoked on its own.

1. On GitHub: your picture (top right) → **Settings** → **Developer
   settings** → **Personal access tokens** → **Fine-grained tokens** →
   **Generate new token**.
2. **Token name:** `paper-run trigger`. **Expiration:** 90 days.
3. **Repository access:** **Only select repositories** → `trading-bot`.
4. **Repository permissions:** **Actions → Read and write**. Leave everything
   else at **No access** (GitHub adds **Metadata: Read-only** by itself).
5. Click **Generate token** and copy it (it starts with `github_pat_`).

This token can start, re-run or cancel this repository's workflow runs and
read their logs (it starts the Paper trading run and, when needed, the Daily
strategy comparison). It **can't** change any file or workflow, read or change
secrets, open issues, or touch any other repository. (GitHub has no narrower
permission that can start a workflow.)

### F2. Save it on the server

Log in as `bot` (`ssh bot@YOUR_SERVER_IP`). This asks for the token without
showing it:

```
mkdir -p ~/.config/trading-bot && chmod 700 ~/.config/trading-bot
read -rsp "Paste the paper-run token, then press Enter: " TOKEN; echo
printf '%s' "$TOKEN" > ~/.config/trading-bot/dispatch-token
chmod 600 ~/.config/trading-bot/dispatch-token
unset TOKEN
```

### F3. Get the new files and test once

The hourly push brings the code up to date; start it now instead of waiting:

```
sudo systemctl start launch-push
cd ~/trading-bot && git log -1 --oneline
~/trading-bot/deploy/trigger_paper_run.sh
```

It prints either `started Paper trading run on main (...)` (a new run
appears in the **Actions** tab within a minute or so) or `skipped: a run
started N min ago`. Either means it works. After 00:30 UTC, when yesterday's
comparison issue is missing, it also prints `started Daily strategy
comparison on main (the issue for YYYY-MM-DD wasn't posted)`; when the issue
is there it says nothing about it. `could not start ...` says why
(for example a missing or expired token).

### F4. Turn on the 10-minute timer

```
sudo cp ~/trading-bot/deploy/paper-run-trigger.service ~/trading-bot/deploy/paper-run-trigger.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paper-run-trigger.timer
systemctl list-timers paper-run-trigger*
journalctl -u paper-run-trigger -n 20 --no-pager
```

The daily comparison's **Time between runs** row counts both kinds of runs
and says how many GitHub scheduled and how many the server started.

---

## Part G. Run the main strategy every minute (optional)

The **main (1 min)** strategy is the main strategy with exactly the same
entry checks, exits and costs ($10 buys; sell half at +50%; everything left
at -30%, 40% below the peak, or after 48 hours if the price is still within
10% of entry; 3% costs), checked **every minute** instead of every few
minutes on GitHub. Its results go to `data/main-1min/` only: it never
touches the GitHub main strategy's files and opens no GitHub issues. The
hourly push (Part D) sends them to GitHub, and the daily comparison shows
them as **main (1 min)** next to **main**, with a health row.

It needs no new token or key. It only reads DexScreener, RugCheck and
Jupiter's free data, and stays within their free limits: about 4–6
DexScreener requests a minute, and RugCheck only for tokens that pass the
market checks, once per token per 10 minutes, at most 10 a minute.

### G1. Get the new files and test once

```
sudo systemctl start launch-push
cd ~/trading-bot && git log -1 --oneline
.venv/bin/python main_1min.py --test
```

The test does one run against the real sites and saves **nothing** (a
temporary folder). It prints one line like
`12:01 43 candidate(s), 43 checked, 2 passed; 2 open; P&L $+0.00`, plus a
`BUY` line for each token that passed.

### G2. Turn it on

```
sudo cp ~/trading-bot/deploy/main-1min.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now main-1min
systemctl status main-1min --no-pager
journalctl -u main-1min -n 20 --no-pager
```

`status` should say **active (running)**; the log gets one line a minute.
Within about an hour the push commits `data/main-1min/` (commits called
**"Server paper results …"**).

Two paper versions run inside the same bot, on the same data
(`[[main_1min.versions]]` in `config.toml`): **A** buys only after 3
consecutive passing minutes, **B** skips tokens up more than 100% in the
last hour and needs a Jupiter organic score of 60+. Their results go to
`data/main-1min/a/` and `data/main-1min/b/` and are pushed with the rest.
The log line shows them at the end (`A: 1 open, P&L $+0.00; B: ...`), and
their buys and sells are marked `[A]` / `[B]`. They need nothing extra on
the server.

---

## Part H. Measure the free trade feed for 2 hours (one-off, optional)

Before building a "momentum on launches" strategy, this checks whether
Solana's free public RPC is good enough as a live feed of pump.fun trades.
It **doesn't trade** and keeps **no trade data**: it only counts trades per
second, bandwidth, disconnects, silent gaps, the feed's delay, and how
quickly DexScreener lists new launches and how far behind its price is. It
writes only `data/trade-feed-probe/summary.json` (the hourly push sends it
to GitHub), and **stops by itself after 2 hours** (systemd also stops it at
2 h 5 min, whatever happens). No key, no wallet, no new token.

### H1. Get the new files and start it

```
sudo systemctl start launch-push
cd ~/trading-bot && git log -1 --oneline
sudo cp ~/trading-bot/deploy/trade-feed-probe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start trade-feed-probe
journalctl -u trade-feed-probe -n 5 --no-pager
```

The log should say `connected to wss://api.mainnet-beta.solana.com;
subscribed to pump.fun's logs`. Every 10 minutes it adds one progress line
(trades, megabytes, disconnects). It is never started again by itself:
don't `enable` it.

### H2. After 2 hours

```
systemctl status trade-feed-probe --no-pager      # "inactive (dead)" = finished
journalctl -u trade-feed-probe -n 15 --no-pager    # the final summary
```

Within the next hour the push puts `data/trade-feed-probe/summary.json` on
GitHub, so it can be read there. To stop it early:
`sudo systemctl stop trade-feed-probe` (the summary so far is kept).

---

## Part I. Run the momentum strategy (optional)

The **momentum** strategy paper-buys a new pump.fun launch only when it
rises fast in its first minutes on real buying. It reads every pump.fun
trade live from Solana's **free public RPC** (the 2-hour measurement in
Part H showed it works: a few short disconnects, about 1.4 s delay, little
CPU and memory). Three variants run side by side, each with its own journal
in `data/momentum/`: **+30% within 2 minutes**, **+50% within 3 minutes** and
**+100% within 5 minutes**. Costs and exits are the launch bot's. No key, no
wallet, no new token. It uses about 1 GB of bandwidth an hour (the feed).

### I1. Get the new files and test it for 2 minutes

```
sudo systemctl start launch-push
cd ~/trading-bot && git log -1 --oneline
.venv/bin/python momentum_bot.py --test
```

It prints `connected to wss://api.mainnet-beta.solana.com; subscribed to
pump.fun's events` and, after 2 minutes, a summary (launches seen, trades,
signals, near misses). A test saves **nothing**.

### I2. Turn it on

```
sudo cp ~/trading-bot/deploy/momentum-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now momentum-bot
systemctl status momentum-bot --no-pager
journalctl -u momentum-bot -n 20 --no-pager
```

`status` should say **active (running)**. Every 10 minutes the log gets a
line with the feed's state and the hour's counts. Like the other bots, it
restarts itself when the hourly push brings new code it uses
(`journalctl -u momentum-bot | grep "automatic restart"`). Pause it with
`sudo systemctl stop momentum-bot`; turn it off for good with
`sudo systemctl disable --now momentum-bot`.

### I3. The feed's backup endpoints

The bot reads pump.fun's events from the free public Solana RPC endpoints in
`ws_urls` under `[momentum]` in `config.toml` (no key, no sign-up). After a
drop it reconnects to the same one within about a second; if that one keeps
failing, it moves on to the next. To see which of them work from your
server right now (15 seconds each; it saves nothing and doesn't disturb the
running bot):

```
cd ~/trading-bot && .venv/bin/python momentum_bot.py --check-feeds
```

`OK` lines work. The health check's "momentum: server" row shows the
disconnects over 24 hours (per hour, and per endpoint), how long the feed
was down, and the endpoint it's on; it warns when the feed was down more
than `max_down_pct` (5%) of the day.

---

## Part J. Check the exchange listings every minute (optional)

The **news (listings)** strategy is the news strategy for the exchange
listings only: Binance's new-listing list, Kraken's blog, and new coins in
the public market lists of Coinbase, Upbit and OKX. Your server checks them
**every minute** instead of every 15 minutes on GitHub; GitHub no longer
reads these five (all the other news sources stay on GitHub). Everything
else is the news strategy's: the coin matching, the checks, the AI check,
the costs and the exits. Its results go to `data/news-listings/` only (its
own journal, candidate log and AI verdicts), the hourly push sends them to
GitHub, and the daily comparison shows them as **news (listings)** next to
**news**, with health rows for the bot, each of its sources and its AI
check.

It only reads public data (each source once a minute; CoinGecko only for a
new listing, and the open positions' prices every 15 minutes) and asks
Anthropic's API about new listing headlines, at most 50 a day (about $0.10
at most). No wallet, no private key.

### J1. Get the new files

```
sudo systemctl start launch-push
cd ~/trading-bot && git log -1 --oneline
.venv/bin/pip install -r requirements.txt -r requirements-launch.txt
```

(The last line installs `anthropic`, Anthropic's Python library, which this
bot is the first on the server to use.)

### J2. Save the Claude API key (the safe way)

1. **Make a separate key for the server** in Anthropic's console
   (<https://console.anthropic.com/settings/keys> → **Create Key**, name it
   `trading-bot server`), instead of reusing the one in GitHub's secret. You
   can then revoke either one without breaking the other. If your console
   offers a monthly spend limit (Settings → Limits), set a low one there
   too, as a backstop to the bot's own daily limit.
2. **Store it in a file only root can read.** These lines ask for the key
   without showing it or saving it in your command history:

   ```
   sudo install -d -m 700 -o root -g root /etc/trading-bot
   sudo install -m 600 -o root -g root /dev/null /etc/trading-bot/claude_api_key
   read -rsp "Paste the Claude API key, then press Enter: " KEY; echo
   printf '%s' "$KEY" | sudo tee /etc/trading-bot/claude_api_key >/dev/null
   unset KEY
   sudo stat -c '%U %a %s bytes' /etc/trading-bot/claude_api_key
   ```

   The last line should say `root 600` and a size of about 100 bytes (not 0).

Why this way: the key is **not** in the bot's folder (which is pushed to
GitHub), not in a `.env` file the `bot` user can read, and not in an
environment variable. When the service starts, systemd reads the file as
root and hands a copy to this one service only (its `LoadCredential=`
line), in a private folder that other services can't see. The other bots
never get it, and it doesn't show in `ps` or `systemctl show`.

To run **without** the AI check, still create the empty file (the first two
lines only): the bot then logs every item as "not checked" and the
rule-based checks decide, as always.

To change the key later, repeat the `read`/`printf` lines, then
`sudo systemctl restart news-listings`. To remove it:
`sudo truncate -s 0 /etc/trading-bot/claude_api_key` and restart.

### J3. Test it

```
.venv/bin/python -m screener.news --check-sources --runs-on server
sudo systemd-run --quiet --pipe --wait -p User=bot -p WorkingDirectory=/home/bot/trading-bot \
  -p LoadCredential=claude_api_key:/etc/trading-bot/claude_api_key \
  /home/bot/trading-bot/.venv/bin/python -m screener.news_ai
.venv/bin/python news_listings_bot.py --test
```

- The first line reads the five sources once: five `ok` lines (Coinbase,
  Upbit and OKX show how many coins they list). If Upbit says `ok` here but
  failed on GitHub, that's because your server isn't in the US.
- The second sends one known headline to the AI check, with the key given
  to it exactly as the service will get it: it should end with
  `yes: Quant (QNT); catalyst: partnership ...` and the cost (about $0.001).
- The third does one run of the bot and saves **nothing**. It prints one
  line like `12:01 5/5 source(s) ok, 0 new item(s); 0 open; P&L $+0.00`
  (the first read of each market list only notes today's coins, so nothing
  is new yet).

### J4. Turn it on

```
sudo cp ~/trading-bot/deploy/news-listings.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-listings
systemctl status news-listings --no-pager
journalctl -u news-listings -n 20 --no-pager
```

`status` should say **active (running)**, and the log starts with
`AI check: on` and gets one line a minute (the full report, with each
check, when there's a new listing). Within about an hour the push commits
`data/news-listings/`. Like the other bots, it restarts itself when the
hourly push brings new code it uses
(`journalctl -u news-listings | grep "automatic restart"`). Pause it with
`sudo systemctl stop news-listings`; turn it off for good with
`sudo systemctl disable --now news-listings`. While it's off, the five
exchange sources aren't read anywhere: to read them on GitHub again,
remove their `runs_on = "server"` lines in `config.toml`.

---

## Part K. Turn off the launch bot (after it was stopped)

On 2026-10-05 the three launch speeds were stopped (`stopped = true` under
`[launch]` in `config.toml`): the bot makes no new buys, and the positions it
still holds close within 30 minutes (the time stop). Its journals and files
stay in `data/launch/`. The momentum bot, main (1 min) (with its new
versions A and B) and the news listings bot keep running; they restart by
themselves when the hourly push brings the new code.

### K1. Get the new code now (instead of waiting up to an hour)

```
sudo systemctl start launch-push
cd ~/trading-bot && git log -1 --oneline
journalctl -u launch-bot -u main-1min -u momentum-bot --since "15 min ago" --no-pager | grep "automatic restart"
```

### K2. Wait until the launch bot holds nothing, then turn it off

About 30 minutes after the automatic restart, check that every speed is
down to 0 open positions:

```
cd ~/trading-bot && for s in 5s 30s 90s; do .venv/bin/python -c "import json; print('$s:', len(json.load(open('data/launch/$s/positions.json'))['open_positions']), 'open')"; done
```

When all three say `0 open`:

```
sudo systemctl disable --now launch-bot
systemctl is-active launch-bot
```

The last line should say `inactive`. **Don't** turn off `launch-push.timer`:
the same hourly push sends every server bot's results to GitHub. The health
check's "launch: server push" row says "stopped" (and "finished" once nothing
is open).

To bring the launch bot back one day: remove `stopped = true` under
`[launch]`, then `sudo systemctl enable --now launch-bot`.

### K3. Positions stuck without a price

A position whose token DexScreener never listed has no price after a
restart, so its time stop can't sell it. While the launch strategy is
stopped, the bot sells such a position at its last known price (with the
normal costs) once it's 10 minutes past its time stop, marked
`closed after the bot was stopped` in the journal. If the launch bot is
still running, it does this by itself when the hourly push brings the new
code. If you already turned it off, do it by hand:

```
systemctl is-active launch-bot
cd ~/trading-bot && .venv/bin/python launch_bot.py --close-stuck
```

Run the second line only when the first says `inactive`. It prints one
`SELL` line per position and `0 still open`; the next hourly push takes the
journals to GitHub (or `sudo systemctl start launch-push` to send them now).

## Part L. The early-launch recorder (nothing to install)

The recorder (`launch_record_bot.py`, `screener/launch_record.py`) records data only: for
every new pump.fun launch it saves what was known at creation and the real price path for
the first hour, to `data/launch-record/launches-YYYY-MM-DD.csv`. It never buys or sells.

**It needs no server step.** It runs inside the `launch-bot` service that is already
installed and enabled, while `[launch] stopped = true` and `[launch_record] enabled = true`
in `config.toml`. The hourly push (`deploy/push_results.sh`) brings the new code; the
service notices ("automatic restart" in `journalctl -u launch-bot`), saves and restarts
itself within a minute or so; the same push script then sends `data/launch-record/` to
GitHub.

- **Do not turn the `launch-bot` service off** (Part K): it is what runs the recorder now.
  To stop the recorder, set `[launch_record] enabled = false`; the service restarts by itself.
- It uses the same free Solana public RPC endpoints as the momentum bot ([momentum] ws_urls),
  as one more read-only connection from this server. **That feed is heavy**: 261 messages a
  second on 2026-10-23 (74 a second on 2026-10-04, Part H), about 2.5 GB an hour. If your
  server has a monthly transfer limit, check it first; `enabled = false` switches it off.
- Size: a 15-minute live run measured about 8 MB of rows a day with the default settings, but
  the daily cap (`max_rows_per_day = 4000`, spread evenly through the UTC day) holds the
  qualified rows to about 4,000 a day plus the 2% sample (about 850 a day): roughly 2 MB a day. It makes no other request, apart from
  the shared market-backdrop lookup (at most 2 requests per 15 minutes, cached in
  `data/backdrop_cache.json` together with the other bots).
- The daily comparison has one line, "launch record: server": it warns when the feed has been
  silent for more than 10 minutes or no row was written for an hour, and it says when rows
  were skipped by the daily cap.
- A restart (new code) drops the launches being followed at that moment (a partial hour would
  bias the data); their number is in `health.json` (`dropped_at_last_restart`).
- `data/launch-record/state.json` (the copycat and creator ledger, about 30 MB after a week)
  stays on the server and is not pushed.

---

## Part M. The X post watcher (recording only)

The watcher (`xposts_bot.py`, `screener/xposts.py`) reads the newest **original** posts (no
replies, no reposts) of the accounts in `[xposts] accounts` (`config.toml`) every 2 minutes,
only the posts newer than the last one it saw, and saves them in
`data/xposts/posts-YYYY-MM-DD.csv`. It never trades and never posts. X charges your
pay-per-use credits for each post read: the watcher stops for the day after **60 posts**
(`max_posts_per_day`), which is at most about $0.30 a day at X's listed $0.005 a post. Each
account's ID is looked up only once and saved in `data/xposts/accounts.json`.

Your **Bearer Token** goes in one file on the server that only the administrator (root) can
read: `/etc/trading-bot/x_bearer_token`. It is never in the bot's folder (which is pushed to
GitHub), never in the logs and never in the health file. When the service starts, systemd
hands a copy to this one service only.

Do these steps in order. Each command goes on one line: copy it, paste it into the terminal
window, press **Enter**, and compare what you see with the text after it.

### M1. Connect to the server and get the new code

1. On your own computer, open the terminal: on a Mac, press **Cmd + Space**, type
   `Terminal`, press **Enter**; on Windows, click **Start**, type `PowerShell`, press
   **Enter**.
2. Type `ssh bot@YOUR_IP` (your server's address, as in Part B) and press **Enter**. Type
   your key's passphrase if it asks (nothing shows while you type; that is normal) and press
   **Enter**.
   *You should see* a line ending in `bot@...:~$`. You are now on the server.
3. Paste `sudo systemctl start launch-push` and press **Enter** (type your password for
   `bot` if asked). *You should see* nothing; the prompt comes back after a few seconds.
4. Paste `cd ~/trading-bot && git log -1 --oneline` and press **Enter**.
   *You should see* one line with a short code and a message, for example
   `Server paper results ...` or `Merge pull request ...`.
5. Paste `ls xposts_bot.py deploy/xposts.service` and press **Enter**.
   *You should see* `deploy/xposts.service  xposts_bot.py`. If it says *No such file*, the
   new code is not there yet: wait 10 minutes and repeat steps 3 to 5.

### M2. Put the token on the server (once)

1. Paste this and press **Enter**:

   ```
   sudo install -d -m 700 -o root -g root /etc/trading-bot && sudo install -m 600 -o root -g root /dev/null /etc/trading-bot/x_bearer_token
   ```

   *You should see* nothing; the prompt comes back. (If `/etc/trading-bot` already exists
   from Part J, that is fine: it is not changed.)
2. Paste this and press **Enter**:

   ```
   read -rsp "Paste the X Bearer Token, then press Enter: " KEY; echo
   ```

   *You should see* `Paste the X Bearer Token, then press Enter:`.
3. Open your password manager, copy the **Bearer Token** (only the token, not the API key or
   the secret), click back into the terminal and paste it: on a Mac **Cmd + V**; in
   PowerShell **right-click**. **Nothing appears** (it is hidden on purpose, and it is not
   saved in the command history). Press **Enter** once.
4. Paste this and press **Enter**:

   ```
   printf '%s' "$KEY" | sudo tee /etc/trading-bot/x_bearer_token >/dev/null; unset KEY; sudo stat -c '%U %a %s bytes' /etc/trading-bot/x_bearer_token
   ```

   *You should see* one line like `root 600 112 bytes`: `root`, `600`, and a size of about
   100 bytes or more. If the size is `0 bytes`, the paste did not work: repeat steps 2 to 4.
5. Close nothing yet. Never paste the token into a chat, an email, GitHub or a file in
   `~/trading-bot`.

### M3. Look up the accounts (one paid request, about $0.12)

Paste this (it is one long line) and press **Enter**:

```
sudo systemd-run --quiet --pipe --wait -p User=bot -p WorkingDirectory=/home/bot/trading-bot -p LoadCredential=x_bearer_token:/etc/trading-bot/x_bearer_token /home/bot/trading-bot/.venv/bin/python xposts_bot.py --lookup
```

*You should see* `Looked up 12 handle(s) in one request:`, then one line per account, like
`@elonmusk: found, account ID 44196397`, and a last line with the estimated cost. An account
marked `NOT FOUND on X` is skipped from now on; send me its name. If you see
`The lookup failed: X answered 401`, the token was not pasted correctly: repeat M2.

### M4. One test request (about $0.025)

Paste this and press **Enter**:

```
sudo systemd-run --quiet --pipe --wait -p User=bot -p WorkingDirectory=/home/bot/trading-bot -p LoadCredential=x_bearer_token:/etc/trading-bot/x_bearer_token /home/bot/trading-bot/.venv/bin/python xposts_bot.py --test elonmusk
```

*You should see* `One request for @elonmusk ...: 5 original post(s) returned`, up to five lines
with a time, a post number and the start of each post, then `Estimated cost: 5 post(s) x $0.005
= $0.025` and `Nothing was saved.`

Then, on your own computer, open your X developer console in the browser, go to its **Usage**
page and check what the lookup (M3) and this test really cost. Copy everything M3 and M4
printed into our chat (it holds no token) with the amounts from the Usage page. **Only then**
do M5.

### M5. Turn on the regular checking

Paste these one at a time, pressing **Enter** after each:

```
sudo cp ~/trading-bot/deploy/xposts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xposts
systemctl status xposts --no-pager
```

*You should see*, after the last one, `Active: active (running)` in green. Then paste
`journalctl -u xposts -n 5 --no-pager` and press **Enter**: *you should see*
`X post watcher: 12 account(s) every 120 s, at most 60 posts a day`, and a new line every 2
minutes like `12:04 0 new post(s); 0 of 60 read today`. The first round only notes the time:
it never pays for posts from before the watcher started.

Within about an hour the push sends `data/xposts/` to GitHub, and the daily comparison shows a
row **xposts: server** with the posts read today and the estimated cost.

- **Pause it:** `sudo systemctl stop xposts`. **Turn it off for good:**
  `sudo systemctl disable --now xposts`.
- **Change the token:** repeat M2 steps 2 to 4, then `sudo systemctl restart xposts`.
- **Remove the token:** `sudo truncate -s 0 /etc/trading-bot/x_bearer_token` and
  `sudo systemctl restart xposts`: the watcher then asks X nothing.
- The report `data/xposts/report.md` (rewritten about once an hour) lists, for each post, the
  pump.fun launches in the next 10 minutes whose name or symbol matches a word of the post,
  with how their price moved. It is a measurement only.
