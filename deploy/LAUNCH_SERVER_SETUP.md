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
optionally, one that can only start its workflows (Part F).

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
  `journalctl -u launch-bot -u main-1min --no-pager | grep "automatic restart"`.
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
  stuck, it clears it first and still pushes the newest results. Check the
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
