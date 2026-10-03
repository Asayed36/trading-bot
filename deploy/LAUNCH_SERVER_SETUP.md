# Setting up the launch bot on a small server

This puts the **launch** paper strategy (`launch_bot.py`) on a small cloud
server that runs all the time. It listens to PumpPortal's free data feed,
paper-trades new pump.fun launches at three speeds, and pushes the results to
this repository about once an hour.

**Paper trading only.** Nothing here uses a wallet, a private key or a seed
phrase, and nothing can buy or sell anything. **Never put a wallet or a private
key on this server.** The only secret on it is a GitHub token that can do one
thing: read and write this repository's files.

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

- **Get bot updates** (after a pull request is merged): the hourly push
  already brings the code on the server up to date with GitHub (like
  `git pull`), so you only need to restart the bot to use it:
  `sudo systemctl restart launch-bot`. (Any of your own edits to a file that
  also changed on GitHub are replaced by GitHub's version.)
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
- **Stop paying:** in Vultr, **destroy** the server. Just stopping it keeps
  billing.
- **Never** install a wallet, paste a private key or seed phrase, or use
  PumpPortal's trading API on this server. This bot doesn't need any of that,
  and nobody should ask you for it.
