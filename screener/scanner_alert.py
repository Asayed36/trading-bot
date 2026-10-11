"""Scanner alerts: a GitHub issue labelled "scanner-alert" when

  1. a new coin appears on an exchange's list (Coinbase, Upbit, OKX, Kraken) or
     in Binance's listing announcements, read from the same feeds the news
     listings bot reads ([[news.sources]] with kind = "exchange" in
     config.toml; the ones GitHub's servers can't reach simply fail and are
     named in the run's summary), or
  2. the news AI check has flagged a news item as a positive catalyst for one
     coin (read from the verdicts the news strategy has ALREADY saved in
     data/news/ai_verdicts.csv: no new AI call, no new paid call).

ALERTS ONLY. It trades nothing, uses no wallet or key, and changes no bot,
filter, config or the Paper trading run. It uses only the workflow's own
GITHUB_TOKEN (issues: write); the price lookups are free public APIs without a
key. The issues carry only the "scanner-alert" label: the repair automation
works on "repair" issues alone, and closing an alert changes nothing (what has
been alerted is remembered in one memory issue, labelled "scanner-alert-state",
not in the alerts' open/closed state).

Notification: GitHub's phone app pushes only @mentions and assignments, so each
ALERT issue (listing, news and the daily summary) starts with "@<user>" and is
assigned to that user ([scanner_alert] notify_user in config.toml; empty = do
neither). The memory issue never is. If GitHub refuses the assignment the issue
is still opened with the mention and the run summary says so.

Rules: a coin on an exchange is alerted once, ever; nothing already covered by
the GitHub news strategy's own issue is alerted again; at most MAX_PER_DAY
alerts a day, the rest listed in one summary issue for that day.
"""

import base64
import csv
import io
import json
import re
import subprocess
import time
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from screener.api import ApiError
from screener.github_issues import GitHubError, GitHubIssues
from screener.news import NewsHttp, _words, listing_tickers, read_source

LABEL = "scanner-alert"
STATE_LABEL = "scanner-alert-state"
STATE_TITLE = "Scanner alert memory (do not edit; closing it changes nothing)"
MAX_PER_DAY = 10
MAX_STATE_CHARS = 60_000
KEEP_DAYS = 60
STATE_RE = re.compile(r"<!-- scanner-alert-state\n(.*?)\n-->", re.S)
KEY_RE = re.compile(r"<!-- scanner-alert-key: (.*?) -->")
NOT_ADVICE = ("This is an alert, not advice. Most listing pops fade within hours or days, and "
              "the first price you can get is often far from the one shown here.")
NOT_ADVICE_NEWS = ("This is an alert, not advice. A news-driven jump often fades within hours "
                   "or days, and the first price you can get may be far from the one shown here.")
COINGECKO = "https://api.coingecko.com/api/v3"
DEXSCREENER = "https://api.dexscreener.com/latest/dex/search?q={}"
# The exchange's name, by source name (market lists use their [[news.sources]]
# exchange_name / exchange).
EXCHANGES = {"Binance listings": "Binance", "Kraken blog": "Kraken", "OKX listings": "OKX",
             "Bybit listings": "Bybit"}


def utc(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def exchange_name(source):
    if source["name"] in EXCHANGES:
        return EXCHANGES[source["name"]]
    return source.get("exchange_name") or (source.get("exchange") or source["name"]).capitalize()


def alert_key(kind, exchange, coin):
    return f"{kind}|{exchange.lower()}|{coin.upper()}"


class Gh(GitHubIssues):
    """The repository's issues (screener/github_issues.py), with the label of
    the listing chosen per call."""

    def issues_with_label(self, label=LABEL):
        url = f"/issues?labels={quote(label)}&state=all&per_page=100"
        while url:
            resp = self._request("GET", url)
            yield from (i for i in resp.json() if "pull_request" not in i)
            url = resp.links.get("next", {}).get("url")


    def assign(self, number, user):
        """Assign an issue to `user`. True when GitHub did it: it answers 201
        but silently leaves out a user it won't assign, so the answer is read."""
        resp = self._request("POST", f"/issues/{number}/assignees", json={"assignees": [user]})
        return user.lower() in [(a.get("login") or "").lower()
                                for a in resp.json().get("assignees") or []]


class Alert(dict):
    """kind ("listing" / "news"), exchange, coin (ticker), coin_id, source, title, url, seen
    (ISO), announced (ISO or None), how, key, test, reason."""


# ---------------------------------------------------------------------
# Memory: one issue holds what has been alerted and each market list
# ---------------------------------------------------------------------

def pack(state):
    text = json.dumps(state, separators=(",", ":"), sort_keys=True)
    if len(text) > MAX_STATE_CHARS // 2:
        text = "z:" + base64.b64encode(zlib.compress(text.encode(), 9)).decode()
    return text


def unpack(text):
    text = text.strip()
    if text.startswith("z:"):
        text = zlib.decompress(base64.b64decode(text[2:])).decode()
    return json.loads(text)


class Memory:
    """The state, kept in the body of the memory issue. Without a GitHub client
    (a dry run) it is kept in memory only."""

    def __init__(self, gh=None):
        self.gh, self.number, self.new = gh, None, True
        self.state = {"markets": {}, "markets_new": {}, "alerted": {}, "days": {},
                      "summary": {}, "pending": []}
        if gh is None:
            return
        gh.ensure_label(STATE_LABEL, "ededed", "Scanner alert memory")
        for issue in gh.issues_with_label(STATE_LABEL):
            match = STATE_RE.search(issue.get("body") or "")
            if match:
                self.number, self.new = issue["number"], False
                self.state.update(unpack(match.group(1)))
                break

    def save(self):
        if self.gh is None:
            return
        text = pack(self.state)
        if len(text) > MAX_STATE_CHARS:
            raise ApiError("the scanner memory is too big for an issue; trim 'alerted'")
        body = ("Remembers what the scanner has alerted and each exchange's market list, so "
                "nothing is alerted twice. Don't edit it. Closing it changes nothing.\n\n"
                f"<!-- scanner-alert-state\n{text}\n-->")
        if self.number is None:
            self.number = self.gh.create(STATE_TITLE, body, [STATE_LABEL])
        else:
            self.gh.set_body(self.number, body)
        self.new = False

    def prune(self, now):
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
        self.state["alerted"] = {k: v for k, v in self.state["alerted"].items() if v >= cutoff}
        days = sorted(self.state["days"])[-7:]
        self.state["days"] = {d: self.state["days"][d] for d in days}
        self.state["summary"] = {d: n for d, n in self.state["summary"].items() if d in days}


# ---------------------------------------------------------------------
# Price and liquidity (free public APIs, no key)
# ---------------------------------------------------------------------

class PriceLookup:
    """A current price with its source, and liquidity when known. CoinGecko's
    public API (no key) first, DexScreener's search second. Nothing here is
    needed for the alert: when both fail the alert says so."""

    def __init__(self, http):
        self.http = http

    def lookup(self, symbol, coin_id=None):
        info = {"price": None, "source": "", "liquidity": None, "liquidity_source": "",
                "name": "", "note": ""}
        try:
            self._coingecko(info, symbol, coin_id)
        except (ApiError, ValueError, KeyError, TypeError) as exc:
            info["note"] = f"CoinGecko: {exc}"
        try:
            self._dexscreener(info, symbol)
        except (ApiError, ValueError, KeyError, TypeError) as exc:
            info["note"] = (info["note"] + "; " if info["note"] else "") + f"DexScreener: {exc}"
        return info

    def _coingecko(self, info, symbol, coin_id):
        how = "CoinGecko's public API"
        if not coin_id:
            found = (self.http.json(f"{COINGECKO}/search?query={symbol}") or {}).get("coins") or []
            same = [c for c in found if (c.get("symbol") or "").upper() == symbol.upper()]
            if not same:
                info["note"] = f"{symbol} isn't on CoinGecko yet"
                return
            best = min(same, key=lambda c: c.get("market_cap_rank") or 10 ** 9)
            coin_id = best["id"]
            how += " (matched by ticker: check it is the right coin)"
        data = self.http.json(f"{COINGECKO}/simple/price?ids={coin_id}&vs_currencies=usd")
        price = (data.get(coin_id) or {}).get("usd")
        if price:
            info.update(price=float(price), source=f"{how}, id {coin_id}", name=coin_id)

    def _dexscreener(self, info, symbol):
        pairs = (self.http.json(DEXSCREENER.format(symbol)) or {}).get("pairs") or []
        mine = [p for p in pairs if ((p.get("baseToken") or {}).get("symbol") or "").upper()
                == symbol.upper() and (p.get("liquidity") or {}).get("usd")]
        if not mine:
            return
        best = max(mine, key=lambda p: p["liquidity"]["usd"])
        pool = f"{best.get('dexId')} pool on {best.get('chainId')}"
        info["liquidity"] = float(best["liquidity"]["usd"])
        info["liquidity_source"] = f"DexScreener, largest {symbol} pool ({pool})"
        if info["price"] is None and best.get("priceUsd"):
            info.update(price=float(best["priceUsd"]),
                        source=f"DexScreener, {pool} (a DEX price: check it is the right token)")


# ---------------------------------------------------------------------
# Who to notify (GitHub's phone app pushes only @mentions and assignments)
# ---------------------------------------------------------------------

USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def notify_user(cfg):
    """[scanner_alert] notify_user in config.toml: a GitHub username, or "" for nobody."""
    user = str((cfg.get("scanner_alert") or {}).get("notify_user") or "").strip().lstrip("@")
    return user if USER_RE.match(user) else ""


def with_mention(body, user):
    """The body with @user on its first line (unchanged when there's no user)."""
    return f"@{user}\n\n{body}" if user else body


# ---------------------------------------------------------------------
# The issue text
# ---------------------------------------------------------------------

def money(value):
    return "unknown" if value is None else f"${value:,.0f}"


def issue_title(alert):
    if alert["kind"] == "news":
        return f"ALERT: news {alert['coin']}"
    return f"ALERT: {alert['exchange']} lists {alert['coin']}"


def issue_body(alert, price):
    seen = utc(alert["seen"])
    ann = alert.get("announced")
    if ann:
        announced = f"{utc(ann):%Y-%m-%d %H:%M} UTC"
    elif alert["kind"] == "news":
        announced = "not given by the source"
    else:
        announced = ("not known: this exchange publishes no announcement time we can read "
                     "(we saw the coin appear in its list)")
    if price["price"] is not None:
        shown = f"${price['price']:.10g} ({price['source']})"
    else:
        shown = f"not available ({price['note'] or 'no source answered'})"
    if price["liquidity"] is not None:
        liq = f"{money(price['liquidity'])} ({price['liquidity_source']})"
    else:
        liq = "unknown (no DEX pool found)"
    lines = []
    if alert.get("test"):
        lines += ["**THIS IS A TEST EVENT, not a real listing or news.**", ""]
    lines += [
        f"**Coin:** {alert['coin']}" + (f" ({price['name']})" if price["name"] else ""),
        f"**{'News source' if alert['kind'] == 'news' else 'Exchange'}:** "
        + (alert["source"] if alert["kind"] == "news" else alert["exchange"]),
        f"**Time we saw it:** {seen:%Y-%m-%d %H:%M} UTC ({alert['how']})",
        f"**The exchange's own announcement time:**" if alert["kind"] == "listing"
        else "**The news item's own time:**",
    ]
    lines[-1] += f" {announced}"
    lines += [f"**Current price:** {shown}", f"**Liquidity:** {liq}"]
    if alert.get("title"):
        lines.append(f"**Headline:** {alert['title'][:200]}")
    if alert.get("reason"):
        lines.append(f"**Why the AI check flagged it:** {alert['reason']}")
    if alert.get("url"):
        lines.append(f"**Link:** {alert['url']}")
    lines += ["", f"> {NOT_ADVICE_NEWS if alert['kind'] == 'news' else NOT_ADVICE}",
              "> Nothing was traded: this scanner only sends alerts.", "",
              f"<!-- scanner-alert-key: {alert['key']} -->"]
    return "\n".join(lines)


# ---------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------

def git_news_rows(cfg, ref="origin/main", fetch=False):
    """The news strategy's saved AI verdicts (data/<news>/ai_verdicts.csv),
    from GitHub's newest main when it can be fetched, else the checkout."""
    folder = cfg["files"]["data_folder"]
    paths = [f"{folder}/{cfg['news'].get('folder', 'news')}/ai_verdicts.csv",
             f"{folder}/{cfg['news_listings']['folder']}/ai_verdicts.csv"]
    if fetch:
        try:
            subprocess.run(["git", "fetch", "-q", "--depth=1", "origin", "main"], timeout=60,
                           check=True, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            ref = None
    rows = []
    for path in paths:
        text = None
        if ref:
            done = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True,
                                  text=True)
            text = done.stdout if done.returncode == 0 else None
        if text is None:
            try:
                with open(path, newline="") as fh:
                    text = fh.read()
            except OSError:
                continue
        rows += list(csv.DictReader(io.StringIO(text)))
    return rows


class Scanner:
    def __init__(self, cfg, http, gh=None, passed_gh=None, memory=None, prices=None,
                 news_rows=None, out=print, max_per_day=MAX_PER_DAY):
        self.cfg, self.c = cfg, cfg["news"]
        self.http, self.gh, self.passed_gh = http, gh, passed_gh
        self.memory = memory or Memory(gh)
        self.prices = prices or PriceLookup(http)
        self.news_rows = news_rows or (lambda: git_news_rows(cfg))
        self.out, self.max_per_day = out, max_per_day
        self.user = notify_user(cfg)
        self.notes = []               # things to tell in the run summary
        self.sources = [s for s in self.c["sources"]
                        if s.get("kind") == "exchange" and s.get("enabled") is not False]
        self.status = {}              # source name -> {"ok": polls, "failed": polls, "error": str}
        self.created = []             # (issue number, title) opened by this run
        self._alert_keys = None       # keys on existing alert issues (a second memory)
        self._bot_issues = None       # the news strategy's own "passed" issues

    # ---- 1. exchange listings ----

    def poll_listings(self, now):
        state = self.memory.state
        found = []
        for source in self.sources:
            name = source["name"]
            st = self.status.setdefault(name, {"ok": 0, "failed": 0, "error": ""})
            plan = {"state": state, "markets": {}, "markets_new": {}}
            try:
                items = read_source(self.http, source, now, plan, {})
            except ApiError as exc:
                st["failed"] += 1
                st["error"] = str(exc)[:160]
                continue
            st["ok"] += 1
            for key in ("markets", "markets_new"):
                if plan[key]:
                    state.setdefault(key, {}).update(plan[key])
            found += self._listing_alerts(source, items, now)
        return found

    def _listing_alerts(self, source, items, now):
        c, out = self.c, []
        limit = timedelta(minutes=c["max_age_minutes"])
        exchange = exchange_name(source)
        market_list = source.get("format") == "markets"
        for item in items:
            published = item.get("published")
            if not market_list:
                if published and now - published > limit:
                    continue
                text = f"{item['title']}. {item.get('summary', '')}"
                if not _words(c["exchange_words"]).search(text) \
                        or _words(c["bad_news_words"]).search(text):
                    continue
                tickers = listing_tickers(item["title"])
            else:
                tickers = [item["id"]]
            for sym in tickers:
                out.append(Alert(
                    kind="listing", exchange=exchange, coin=sym.upper(), coin_id=None,
                    source=source["name"], title=item["title"], url=item.get("url", ""),
                    seen=now.isoformat(),
                    announced=None if market_list or not published else published.isoformat(),
                    how=("a new pair in its public market list" if market_list
                         else f"in {source['name']}"),
                    key=alert_key("listing", exchange, sym), test=False, reason=""))
        return out

    # ---- 2. news flagged by the news AI check ----

    def poll_news(self, now, rows=None, window_hours=6):
        out, limit = [], now - timedelta(hours=window_hours)
        for row in (self.news_rows() if rows is None else rows):
            if row.get("kind") == "exchange" or row.get("ai_status") != "ok":
                continue
            if row.get("ai_catalyst") != "yes" or row.get("ai_one_coin") != "yes" \
                    or row.get("ai_false_match") == "yes" or row.get("ai_duplicate") == "yes":
                continue
            symbol = (row.get("ai_symbol") or "").strip().upper()
            try:
                when = datetime.strptime(row["time_utc"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue
            if not symbol or when < limit:
                continue
            coin_id = row.get("rule_coin") if row.get("rule_coin") and ";" not in row["rule_coin"] \
                else None
            try:
                ann = datetime.strptime(row["published_utc"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc).isoformat() if row.get("published_utc") else None
            except ValueError:
                ann = None
            ident = row.get("url") or row.get("title") or ""
            out.append(Alert(
                kind="news", exchange="", coin=symbol, coin_id=coin_id, source=row["source"],
                title=row.get("title", ""), url=row.get("url", ""), seen=now.isoformat(),
                announced=ann, how=f"in the news strategy's AI verdicts ({row['source']})",
                key=f"news|{symbol}|{ident[:120]}", test=False,
                reason=(row.get("ai_reason") or "").strip()))
        return out

    # ---- raising the alerts ----

    def _known_keys(self):
        if self._alert_keys is None:
            self._alert_keys = set()
            if self.gh is not None:
                for issue in self.gh.issues_with_label(LABEL):
                    self._alert_keys.update(KEY_RE.findall(issue.get("body") or ""))
        return self._alert_keys

    def covered_by_the_bot(self, alert):
        """The GitHub news strategy already opened its own issue for this coin
        from this exchange (its "passed" issues name the coin in the title and
        the source in the body)."""
        if self.passed_gh is None or alert["kind"] != "listing":
            return False
        if self._bot_issues is None:
            self._bot_issues = list(self.passed_gh.issues_with_label("passed"))
        word = re.compile(r"(?<![A-Z0-9])" + re.escape(alert["coin"]) + r"(?![A-Z0-9])", re.I)
        names = {alert["source"].lower(), alert["exchange"].lower()}
        return any(word.search(i.get("title") or "")
                   and any(n in (i.get("body") or "").lower() for n in names)
                   for i in self._bot_issues)

    def raise_alerts(self, alerts, now, dry_run=False):
        """Open the issues for new alerts (within the day's cap). Returns what
        was done, one line each."""
        state, done = self.memory.state, []
        day = now.strftime("%Y-%m-%d")
        individual = state["days"].setdefault(day, [])
        for alert in alerts:
            key = alert["key"]
            if key in state["alerted"] or key in self._known_keys():
                continue
            if self.covered_by_the_bot(alert):
                state["alerted"][key] = now.isoformat()
                done.append(f"skipped {key}: the news strategy already opened an issue for it")
                continue
            price = self.prices.lookup(alert["coin"], alert.get("coin_id"))
            title, body = issue_title(alert), with_mention(issue_body(alert, price), self.user)
            if dry_run:
                done.append(f"WOULD OPEN: {title}\n{body}")
                state["alerted"][key] = now.isoformat()
                continue
            try:
                if len(individual) < self.max_per_day:
                    self.gh.ensure_label(LABEL, "1d76db", "Scanner alert (not advice, no trade)")
                    number = self.gh.create(title, body, [LABEL])
                    individual.append(key)
                    self._assign(number)
                    done.append(f"opened #{number}: {title}")
                else:
                    number = self._summary(day, alert, now)
                    done.append(f"over {self.max_per_day} today, added to summary #{number}: "
                                f"{title}")
            except Exception as exc:     # GitHub down: try again next poll, nothing is lost
                done.append(f"could not open {title}: {exc}")
                self._retry(alert)
                continue
            state["alerted"][key] = now.isoformat()
            self._known_keys().add(key)
            self.created.append((number, title))
        return done

    def _assign(self, number):
        """Assign the new alert issue to the notify user. Never fails the alert:
        if GitHub refuses, the issue stays open with the @mention and the run
        summary says so."""
        if not self.user:
            return
        try:
            done = self.gh.assign(number, self.user)
            why = "" if done else "GitHub left the assignee out (not assignable here)"
        except Exception as exc:
            why = str(exc)[:160]
        if why:
            note = (f"could not assign #{number} to {self.user} ({why}); it was opened with "
                    f"the @{self.user} mention only")
            self.notes.append(note)
            self.out(note)

    def _retry(self, alert):
        pending = self.memory.state.setdefault("pending", [])
        if all(p["key"] != alert["key"] for p in pending):
            pending.append(dict(alert))

    def _summary(self, day, alert, now):
        """One summary issue a day for the alerts over the cap."""
        state = self.memory.state
        line = (f"- {now:%H:%M} UTC: **{issue_title(alert)}**"
                + (f" ({alert['url']})" if alert.get("url") else "")
                + f" <!-- scanner-alert-key: {alert['key']} -->")
        number = state["summary"].get(day)
        if number is None:
            body = with_mention(
                f"More than {self.max_per_day} scanner alerts on {day}: the rest are listed "
                f"here instead of one issue each.\n\n{line}\n\n> {NOT_ADVICE}", self.user)
            number = self.gh.create(f"ALERT summary: more alerts on {day}", body, [LABEL])
            state["summary"][day] = number
            self._assign(number)
        else:
            issue = self.gh.issue(number)
            body = (issue.get("body") or "").replace(f"\n\n> {NOT_ADVICE}", f"\n{line}\n\n> "
                                                     f"{NOT_ADVICE}")
            self.gh.set_body(number, body)
        return number

    # ---- the loop ----

    def run(self, polls=1, interval=60, now_fn=None, sleep=time.sleep, fake=None,
            dry_run=False, fetch_news=False):
        now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        first = self.memory.new and self.gh is not None
        for n in range(polls):
            now = now_fn()
            try:
                alerts = list(map(Alert, self.memory.state.pop("pending", [])))
                alerts += self.poll_listings(now)
                if n % 3 == 0:        # the saved verdicts change slowly: every 3rd poll
                    alerts += self.poll_news(
                        now, git_news_rows(self.cfg, fetch=True) if fetch_news and n else None)
                if fake:
                    alerts.append(fake_alert(fake, now))
                if first and n == 0:
                    # A brand-new memory: everything already there is the baseline.
                    real = [a for a in alerts if not a.get("test")]
                    for a in real:
                        self.memory.state["alerted"][a["key"]] = now.isoformat()
                    self.out(f"first run: {len(real)} item(s) already present were noted, not "
                             "alerted")
                    alerts = [a for a in alerts if a.get("test")]
                for line in self.raise_alerts(alerts, now, dry_run=dry_run):
                    self.out(line)
                self.memory.prune(now)
                if not dry_run:
                    self.memory.save()
            except (ApiError, GitHubError) as exc:
                self.out(f"poll {n + 1}: {exc}")
            if n + 1 < polls:
                sleep(interval)
        return self.summary()

    def summary(self):
        lines = [f"WARNING {note}" for note in self.notes]
        for name, st in self.status.items():
            mark = "ok  " if not st["failed"] else "FAIL" if not st["ok"] else "some"
            lines.append(f"{mark} {name}: {st['ok']} poll(s) read, "
                         f"{st['failed']} failed" + (f" ({st['error']})" if st["failed"] else ""))
        return lines


def fake_alert(spec, now):
    """A made-up event for testing: "Coinbase:TESTCOIN" (a listing) or
    "news:TESTCOIN" (a news alert)."""
    exchange, _, coin = spec.partition(":")
    coin = (coin or "TESTCOIN").strip().upper()
    if exchange.lower() == "news":
        return Alert(kind="news", exchange="", coin=coin, coin_id=None, source="a test source",
                     title="Test headline: something good happened", url="", seen=now.isoformat(),
                     announced=None, how="a test event", key=f"news|{coin}|test", test=True,
                     reason="test event")
    exchange = exchange.strip().capitalize() or "Coinbase"
    return Alert(kind="listing", exchange=exchange, coin=coin, coin_id=None, source="test",
                 title=f"{exchange} lists {coin} (test)", url="", seen=now.isoformat(),
                 announced=None, how="a test event", key=alert_key("listing", exchange, coin),
                 test=True, reason="")


def make_http():
    return NewsHttp(20)
