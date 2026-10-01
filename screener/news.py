"""The "news" paper strategy: buy a coin right after real, official news.

Every 15 minutes (news.every_minutes) it reads official sources only:
press-release wires (PR Newswire, GlobeNewswire, Business Wire), project
blogs and exchange announcements (all listed in [[news.sources]] in
config.toml). Each new item that names a coin CoinGecko knows is a
candidate, and goes through rule-based checks (no AI, no X):

  Fresh news          published in the last 3 hours
  One coin            names exactly one coin (Bitcoin/Ether as background
                      don't count)
  Not a stablecoin    no stablecoins, wrapped or staked tokens
  Not paid content    no "sponsored", "paid content", "advertorial"
  Catalyst wording    "selects", "partners with", "launches", "goes live",
                      "will list", "acquires", "approved"...
  No hype wording     not "exploring", "in talks", "potential", "rumor",
                      "memorandum of understanding", "price prediction"...
  Not bad news        not "hack", "exploit", "delist", "lawsuit"...
  Named counterparty  a well-known institution is named (a bank, payment
                      network, big exchange or tech company); exchange
                      announcements count the exchange itself
  Big enough          market cap and 24h volume above a minimum
  Not already moved   up less than 15% in the last hour and 40% in 24h
  Not bought recently no buy of the same coin in the last 3 days

Every candidate is logged to data/news/candidates.csv with each check's
result. A candidate that passes everything is paper-bought for $10 at
CoinGecko's price. Exits suit moves that take days: sell half at +50%, sell
the rest at -20% from entry, 25% below the peak, or after 7 days.

PAPER TRADING ONLY. It only reads public web pages and CoinGecko's free API.
No wallet, no private key, no exchange account, no orders.
"""

import copy
import csv
import hashlib
import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.entities import name2codepoint
from types import SimpleNamespace

import requests

from screener.api import ApiError, RateLimited
from screener.filters import FAIL, PASS, Check, money, to_float
from screener.paper_trader import PaperTrader, now_utc

COINGECKO = "https://api.coingecko.com/api/v3"
# Identifies the bot as a feed reader, with a link back to this project.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trading-bot-news/1.0; read-only "
                         "paper trading; +https://github.com/Asayed36/trading-bot)",
           "Accept": "application/rss+xml, application/atom+xml, application/xml, "
                     "application/json, text/xml;q=0.9, */*;q=0.8"}
CANDIDATE_COLUMNS = ["time_utc", "source", "kind", "published_utc", "title", "url", "coin",
                     "symbol", "verdict", "failed", "checks"]
QUALIFIERS = r"(?:Network|Protocol|Foundation|Labs|Chain|Blockchain|[Tt]oken|[Cc]oin|DAO|Finance)"
SEEN_DAYS = 4


# ---------------------------------------------------------------------
# Reading the sources
# ---------------------------------------------------------------------

class NewsHttp:
    """Plain read-only HTTP for the news sources and CoinGecko."""

    def __init__(self, timeout=20):
        self.timeout = timeout

    def _get(self, url, headers=None):
        try:
            resp = requests.get(url, headers=dict(HEADERS, **(headers or {})),
                                timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"could not reach {url.split('?')[0]}: {why(exc)}") from exc
        if resp.status_code == 429:
            raise RateLimited(f"{url.split('?')[0]} said 'too many requests'")
        if resp.status_code != 200:
            raise ApiError(f"{url.split('?')[0]} answered with error {resp.status_code}")
        return resp

    def text(self, url):
        return self._get(url).text

    def json(self, url, headers=None):
        return self._get(url, headers).json()


def _utc(when):
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def seen_key(text):
    """A short fingerprint of an item, so the list of items already seen
    (kept for a few days in positions.json) stays small."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def clean(text):
    """Plain text from a bit of HTML."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_time(text):
    if not text:
        return None
    text = text.strip()
    try:
        when = parsedate_to_datetime(text)          # RSS: "Wed, 24 Sep 2026 13:00 GMT"
    except (TypeError, ValueError, IndexError):
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))   # Atom
        except ValueError:
            return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _child(el, *names):
    for name in names:
        for child in el:
            if child.tag.split("}")[-1] == name:
                return child
    return None


def why(exc):
    """The useful part of a connection error, e.g. "ReadTimeout" or
    "ConnectionResetError: [Errno 104] Connection reset by peer"."""
    text = str(exc)
    caused = re.search(r"Caused by (\w+)\((.*)\)\)?\s*$", text)
    if caused:
        return f"{caused.group(1)}: {caused.group(2)[-80:]}"
    return f"{type(exc).__name__}: {text[-80:]}"


XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def repair_xml(text):
    """Fix the usual mistakes in hand-made feeds: HTML entities like &nbsp;
    (not valid XML), a bare "&", and control characters."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    def entity(m):
        name = m.group(1)
        if name in XML_ENTITIES:
            return m.group(0)
        code = name2codepoint.get(name)
        return f"&#{code};" if code else f"&amp;{name};"

    text = re.sub(r"&([A-Za-z][A-Za-z0-9]*);", entity, text)
    return re.sub(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#\d+|#x[0-9A-Fa-f]+);)", "&amp;", text)


def parse_feed(text):
    """Items from an RSS 2.0 or Atom feed: [{id, title, summary, url, published}].
    A feed with no items at all is treated as broken: a working feed always
    lists its latest posts (Business Wire, for one, answers a bad address
    with an empty feed whose description holds the error)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        try:
            root = ET.fromstring(repair_xml(text).encode("utf-8"))
        except ET.ParseError as exc:
            start = clean(text[:300])[:80]
            raise ApiError(f"not a valid feed ({exc}); it starts: {start!r}") from exc
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = _child(el, "title")
        summary = _child(el, "description", "summary", "content")
        link = _child(el, "link")
        url = (link.get("href") or link.text or "").strip() if link is not None else ""
        guid = _child(el, "guid", "id")
        when = _child(el, "pubDate", "published", "updated", "date")
        items.append({
            "id": (guid.text or "").strip() if guid is not None and guid.text else url,
            "title": clean(title.text if title is not None else ""),
            "summary": clean(summary.text if summary is not None else "")[:2000],
            "url": url,
            "published": parse_time(when.text if when is not None else None),
        })
    if not items:
        about = _child(root.find("channel") if root.find("channel") is not None else root,
                       "description", "subtitle", "title")
        note = clean(about.text if about is not None else "")[:80]
        raise ApiError("the feed has no items" + (f" ({note!r})" if note else ""))
    return items


def parse_binance(data):
    """Items from Binance's announcement list (public, no key)."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("title") and node.get("code"):
                found.append(node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    items = []
    for a in found:
        ms = to_float(a.get("releaseDate") or a.get("publishDate"))
        items.append({
            "id": str(a.get("id") or a["code"]),
            "title": clean(a["title"]),
            "summary": clean(a.get("body") or "")[:2000],
            "url": f"https://www.binance.com/en/support/announcement/{a['code']}",
            "published": datetime.fromtimestamp(ms / 1000, timezone.utc) if ms else None,
        })
    if not items:
        raise ApiError("no announcements in the answer")
    return items


# ---------------------------------------------------------------------
# CoinGecko (free plan)
# ---------------------------------------------------------------------

class CoinGecko:
    """Coin list and prices from CoinGecko's free API. Counts calls per month
    in the strategy's state so the free plan's limit is never passed."""

    def __init__(self, http, key, state, monthly_limit, now):
        self.http, self.key, self.limit = http, key, monthly_limit
        month = now.strftime("%Y-%m")
        meter = state.get("coingecko") or {}
        if meter.get("month") != month:
            meter = {"month": month, "calls": 0}
        state["coingecko"] = meter
        self.meter = meter

    def left(self):
        return self.limit - self.meter["calls"]

    def _get(self, path):
        if self.left() <= 0:
            raise ApiError(f"CoinGecko: this month's {self.limit:,} calls are used up")
        self.meter["calls"] += 1
        headers = {"x-cg-demo-api-key": self.key} if self.key else None
        return self.http.json(f"{COINGECKO}{path}", headers)

    def markets(self, page=None, ids=None):
        path = ("/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250"
                "&price_change_percentage=1h,24h")
        path += f"&ids={','.join(ids)}" if ids else f"&page={page}"
        return [coin_info(c) for c in self._get(path) or []]


def coin_info(c):
    return {
        "id": c.get("id"), "symbol": (c.get("symbol") or "").upper(), "name": c.get("name") or "",
        "price": to_float(c.get("current_price")), "market_cap": to_float(c.get("market_cap")),
        "volume": to_float(c.get("total_volume")),
        "change_1h": to_float(c.get("price_change_percentage_1h_in_currency")),
        "change_24h": to_float(c.get("price_change_percentage_24h_in_currency",
                                     c.get("price_change_percentage_24h"))),
    }


# ---------------------------------------------------------------------
# Which coin is it about, and is it a real catalyst?
# ---------------------------------------------------------------------

def _words(words):
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in words) + r")(?!\w)",
                      re.IGNORECASE)


def find_coins(text, coins, c):
    """Coins named in `text`. A coin is named when its name appears with the
    same capitals as on CoinGecko. One-word names that are also everyday
    words ("Quant", "Flow", "Core") also need their ticker - "(QNT)" or
    "$QNT" - or a word like Network/Protocol/Token right after, unless they
    are listed in news.unambiguous_names."""
    found = []
    clear = set(c["unambiguous_names"])
    for coin in coins:
        name, sym = coin["name"], coin["symbol"]
        if len(name) < 3 or not re.search(r"(?<![\w$])" + re.escape(name) + r"(?!\w)", text):
            continue
        if " " in name or name in clear:
            found.append(coin)
            continue
        ticker = sym and len(sym) >= 2 and re.search(
            r"(\$" + re.escape(sym) + r"\b|\(" + re.escape(sym) + r"\))", text)
        qualified = re.search(re.escape(name) + r"\s+" + QUALIFIERS + r"\b", text)
        if ticker or qualified:
            found.append(coin)
    # "Bitcoin Cash" also contains "Bitcoin": keep only the longer name.
    found = [x for x in found
             if not any(x is not y and x["name"] in y["name"] for y in found)]
    # Bitcoin, Ether and stablecoins mentioned in passing don't count when
    # another coin is the subject.
    main = [x for x in found if x["id"] not in c["background_coins"]]
    return main or found


def coin_index(coins):
    by_id = {}
    for coin in coins:
        if coin.get("id") and coin["id"] not in by_id:
            by_id[coin["id"]] = coin
    return list(by_id.values())


def check_candidate(item, source, coins, now, state, c):
    """The rule-based checks for one news item about `coins` (what
    find_coins returned). Returns a list of Check."""
    text = f"{item['title']}. {item['summary']}"
    kind = source.get("kind", "press")
    checks = []

    published = item.get("published")
    if published is None:
        checks.append(Check("Fresh news", PASS, "no time in the feed; first seen just now"))
    else:
        age = (now - published).total_seconds() / 60
        ok = age <= c["max_age_minutes"]
        checks.append(Check("Fresh news", PASS if ok else FAIL,
                            f"published {age:.0f} min ago (limit {c['max_age_minutes']})"))

    if len(coins) == 1:
        coin = coins[0]
        checks.append(Check("One coin", PASS, f"{coin['name']} ({coin['symbol']})"))
    else:
        coin = None
        names = ", ".join(x["name"] for x in coins[:5])
        checks.append(Check("One coin", FAIL, f"names {len(coins)} coins: {names}"))

    if coin:
        odd = (coin["symbol"].lower() in c["stablecoin_symbols"]
               or re.search(r"\b(Wrapped|Staked|Bridged|Liquid Staked)\b", coin["name"]))
        checks.append(Check("Not a stablecoin", FAIL if odd else PASS,
                            f"{coin['name']} is a stablecoin or wrapped/staked token" if odd
                            else "ok"))

    paid = _words(c["paid_words"]).search(text)
    checks.append(Check("Not paid content", FAIL if paid else PASS,
                        f"says \"{paid.group(1)}\"" if paid else "ok"))

    strong = c["exchange_words"] if kind == "exchange" else c["catalyst_words"]
    hit = _words(strong).search(text)
    checks.append(Check("Catalyst wording", PASS if hit else FAIL,
                        f"\"{hit.group(1)}\"" if hit else "no catalyst words (selects, "
                        "partners with, launches, goes live, will list...)"))

    hype = _words(c["hype_words"]).search(text)
    checks.append(Check("No hype wording", FAIL if hype else PASS,
                        f"says \"{hype.group(1)}\"" if hype else "ok"))

    bad = _words(c["bad_news_words"]).search(text)
    checks.append(Check("Not bad news", FAIL if bad else PASS,
                        f"says \"{bad.group(1)}\"" if bad else "ok"))

    if kind == "exchange":
        checks.append(Check("Named counterparty", PASS, f"the exchange itself ({source['name']})"))
    else:
        who = re.search(r"(?<![\w-])(" + "|".join(re.escape(w) for w in c["institutions"])
                        + r")(?!\w)", text)
        checks.append(Check("Named counterparty", PASS if who else FAIL,
                            who.group(1) if who else "no well-known institution named"))

    if coin:
        cap, vol = coin.get("market_cap"), coin.get("volume")
        big = (cap or 0) >= c["min_market_cap_usd"] and (vol or 0) >= c["min_volume_usd"]
        checks.append(Check("Big enough", PASS if big else FAIL,
                            f"market cap {money(cap)}, 24h volume {money(vol)} (need "
                            f"{money(c['min_market_cap_usd'])} and {money(c['min_volume_usd'])})"))
        h1, h24 = coin.get("change_1h"), coin.get("change_24h")
        if h1 is None or h24 is None or coin.get("price") is None:
            checks.append(Check("Not already moved", FAIL, "no price or price change data"))
        else:
            calm = h1 <= c["max_change_1h_pct"] and h24 <= c["max_change_24h_pct"]
            checks.append(Check("Not already moved", PASS if calm else FAIL,
                                f"{h1:+.1f}% in 1h, {h24:+.1f}% in 24h (limits "
                                f"+{c['max_change_1h_pct']:g}% / +{c['max_change_24h_pct']:g}%)"))
        last = (state.get("last_bought") or {}).get(coin["id"])
        recent = last and now - datetime.fromisoformat(last) < timedelta(days=c["cooldown_days"])
        checks.append(Check("Not bought recently", FAIL if recent else PASS,
                            f"bought {last[:16].replace('T', ' ')} UTC" if recent else "ok"))
    return checks


# ---------------------------------------------------------------------
# Paper trader
# ---------------------------------------------------------------------

class NewsTrader(PaperTrader):
    """Sell half at +50% (PaperTrader), then everything left at -20% from
    entry, 25% below the highest price since entry, or after 7 days."""

    def close_reason(self, pos, change_pct, from_peak, hours):
        c = self.cfg
        if change_pct <= -c["stop_loss_pct"]:
            return f"stop loss: down {-change_pct:.0f}% from entry"
        if from_peak <= -c["trailing_stop_pct"]:
            return f"trailing stop: down {-from_peak:.0f}% from peak"
        if hours >= c["max_hold_days"] * 24:
            return f"time limit: {hours / 24:.0f} days ({change_pct:+.0f}%)"
        return None


# ---------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------

class NewsStrategy:
    def __init__(self, cfg, data_folder, http=None, coingecko_key=None):
        self.c = cfg["news"]
        self.pt = self.c["paper_trading"]
        self.folder = os.path.join(data_folder, "news")
        self.trader = NewsTrader(self.pt, self.folder)
        self.http = http or NewsHttp()
        self.key = coingecko_key
        self.candidates_path = os.path.join(self.folder, "candidates.csv")

    def fetch(self, now=None):
        """Read the sources and CoinGecko, and check every new candidate.
        Changes nothing: apply() does the trading and saving."""
        now = now or now_utc()
        c = self.c
        state = copy.deepcopy(self.trader.state)
        plan = {"now": now, "notes": [], "sources": [], "candidates": [], "prices": {},
                "seen": {}, "state": state, "checked": False}
        last = state.get("last_check")
        gap = timedelta(minutes=c["every_minutes"] - 2)    # 2 min slack for GitHub's jitter
        if last and now - datetime.fromisoformat(last) < gap:
            nxt = datetime.fromisoformat(last) + gap
            plan["notes"].append(f"checked at {last[11:16]} UTC; next check from "
                                 f"{nxt:%H:%M} UTC (every {c['every_minutes']} min)")
            return plan
        plan["checked"] = True
        state["last_check"] = now.isoformat()
        gecko = CoinGecko(self.http, self.key, state, c["coingecko_monthly_calls"], now)

        # 1. New items from every source. One broken source doesn't stop the rest.
        seen = state.get("seen") or {}
        # Sources already read successfully. A source read for the first time
        # (the very first run, a new source, or one that just started
        # working) has its backlog noted, not checked: only items still
        # fresh enough are. Older states: sources that gave items before.
        read = state.get("sources_read")
        if read is None:
            read = [n for n, st in (state.get("sources") or {}).items()
                    if st.get("ok") and st.get("items")]
        plan["sources_read"] = list(read)
        new, backlog = [], 0
        for source in c["sources"]:
            status = {"name": source["name"], "kind": source.get("kind", "press")}
            try:
                if source.get("format") == "binance":
                    items = parse_binance(self.http.json(source["url"]))
                else:
                    items = parse_feed(self.http.text(source["url"]))
                status.update(items=len(items), ok=True)
            except ApiError as exc:
                status.update(ok=False, error=str(exc)[:120])
                plan["sources"].append(status)
                continue
            fresh = []
            for item in items:
                key = seen_key(f"{source['name']}|{item['id'] or item['url'] or item['title']}")
                # The same release often goes out on several wires: once is enough.
                same = seen_key("title|" + re.sub(r"\W+", " ", item["title"].lower()).strip())
                if key in seen or key in plan["seen"]:
                    continue
                plan["seen"][key] = now.strftime("%Y-%m-%dT%H:%M")
                if same in seen or same in plan["seen"]:
                    continue
                plan["seen"][same] = now.strftime("%Y-%m-%dT%H:%M")
                fresh.append((source, item, key))
            status["new"] = len(fresh)
            plan["sources"].append(status)
            if source["name"] not in read:
                plan["sources_read"].append(source["name"])
                # The feeds' backlog: only items still fresh enough are checked.
                limit = timedelta(minutes=c["max_age_minutes"])
                kept = [x for x in fresh
                        if x[1]["published"] and now - x[1]["published"] <= limit]
                backlog += len(fresh) - len(kept)
                fresh = kept
            new += fresh
        if backlog:
            plan["notes"].append(f"first read of a source: {backlog} older item(s) already in "
                                 "its feed were noted and skipped")

        # 2. Coins: CoinGecko's top coins (only when there's something to match)
        #    and prices for open positions and project-blog coins.
        # Press releases that don't mention crypto at all are skipped before
        # any CoinGecko call (most of a newswire's items).
        crypto = _words(c["crypto_words"])
        unrelated = [(s, i, k) for s, i, k in new if s.get("kind", "press") == "press"
                     and not s.get("coin") and not crypto.search(f"{i['title']}. {i['summary']}")]
        new = [x for x in new if x not in unrelated]
        held = [p["address"] for p in self.trader.open_positions]
        coins = []
        try:
            if any(not s.get("coin") for s, _, _ in new):
                for page in range(1, c["coin_pages"] + 1):
                    coins += gecko.markets(page=page)
            known = {x["id"] for x in coins}
            want = held + [s["coin"] for s, _, _ in new if s.get("coin")]
            want = [i for i in dict.fromkeys(want) if i not in known]
            if want:
                coins += gecko.markets(ids=want)
        except ApiError as exc:
            # Without coin data nothing can be checked: leave this run's new
            # items unseen so they're checked next run while still fresh.
            plan["notes"].append(f"CoinGecko unavailable, news checks wait for the next run: "
                                 f"{exc}")
            for _, item, key in new:
                plan["seen"].pop(key, None)
                plan["seen"].pop(seen_key("title|" + re.sub(r"\W+", " ",
                                                            item["title"].lower()).strip()), None)
            new = []
        coins = coin_index(coins)
        by_id = {x["id"]: x for x in coins}
        plan["prices"] = {i: by_id[i]["price"] for i in held if by_id.get(i, {}).get("price")}

        # 3. Candidates: new items that name a coin, with every check.
        unnamed = 0
        for source, item, _ in new:
            text = f"{item['title']}. {item['summary']}"
            if source.get("coin"):
                named = [by_id[source["coin"]]] if source["coin"] in by_id else []
            else:
                named = find_coins(text, coins, c)
            if not named:
                unnamed += 1
                continue
            checks = check_candidate(item, source, named, now, state, c)
            plan["candidates"].append({"source": source, "item": item, "coins": named,
                                       "checks": checks})
        if new or unrelated:
            plan["notes"].append(f"{len(new) + len(unrelated)} new item(s): "
                                 f"{len(plan['candidates'])} name a coin, "
                                 f"{unnamed} crypto item(s) name none, "
                                 f"{len(unrelated)} not about crypto")
        plan["coingecko_calls"] = gecko.meter["calls"]
        return plan

    def apply(self, plan, issue_details, out=print):
        trader, now, c = self.trader, plan["now"], self.c
        state = plan["state"]
        # Keep the trader's positions (updated below) but take fetch's other state.
        for key in ("last_check", "coingecko"):
            if key in state:
                trader.state[key] = state[key]
        trader.state.pop("seen_started", None)   # replaced by sources_read
        if plan["checked"]:
            seen = dict(trader.state.get("seen") or {})
            seen.update(plan["seen"])
            cutoff = now - timedelta(days=SEEN_DAYS)
            trader.state["seen"] = {k: v for k, v in seen.items()
                                    if _utc(datetime.fromisoformat(v)) >= cutoff}
            trader.state["sources_read"] = plan["sources_read"]
            trader.state["sources"] = {s["name"]: s for s in plan["sources"]}

        for note in plan["notes"]:
            out(f"  ({note})")
        if plan["checked"]:
            out(f"  CoinGecko calls this month: {plan.get('coingecko_calls', 0):,} of "
                f"{c['coingecko_monthly_calls']:,}")
            for s in plan["sources"]:
                if s.get("ok"):
                    out(f"  ok    {s['name']:<22} {s['items']} item(s), {s.get('new', 0)} new")
                else:
                    out(f"  FAIL  {s['name']:<22} {s['error']}")
        out("")

        for s in trader.update(plan["prices"], when=now):
            out(f"  SELL {s['symbol']:<10} {s['reason']:<45} P&L ${s['pnl_usd']:+.2f}")
            if s["closed"] and s["position"].get("issue_details"):
                trader.state.setdefault("issues_to_close", []).append(s["position"])

        bought = []
        for cand in plan["candidates"]:
            item, source, checks = cand["item"], cand["source"], cand["checks"]
            passed = all(ch.status == PASS for ch in checks)
            coin = cand["coins"][0] if len(cand["coins"]) == 1 else None
            label = coin["symbol"] if coin else ", ".join(x["symbol"] for x in cand["coins"][:3])
            out(f"[{'PASS' if passed else 'FAIL'}] {label}  {source['name']}: "
                f"{item['title'][:90]}")
            out(f"       {item['url']}")
            for ch in checks:
                out(f"   {'  ok ' if ch.status == PASS else ' FAIL'}  {ch.name:<22} {ch.detail}")
            out("")
            self._log(now, source, item, cand["coins"], passed, checks)
            if passed and coin:
                pos = self._buy(coin, item, source, checks, now, issue_details)
                if pos:
                    bought.append(pos)
                    out(f"  BUY  {coin['symbol']:<10} ${self.pt['buy_amount_usd']} at "
                        f"${coin['price']:.10g}")
        if plan["checked"] and not plan["candidates"]:
            out("  No new news about a coin this run.")
        elif plan["candidates"] and not bought:
            out("  No candidate passed every check, so nothing was bought.")
        trader.save()
        return bought

    def _buy(self, coin, item, source, checks, now, issue_details):
        pair = {"priceUsd": coin["price"], "priceChange": {"h1": coin.get("change_1h"),
                                                           "h24": coin.get("change_24h")}}
        result = SimpleNamespace(address=coin["id"], symbol=coin["symbol"], name=coin["name"],
                                 price=coin["price"], pair=pair, insider=None)
        pos = self.trader.buy(result, when=now)
        if not pos:
            return None
        self.trader.state.setdefault("last_bought", {})[coin["id"]] = now.isoformat()
        by = {ch.name: ch.detail for ch in checks}
        pos["news"] = {"title": item["title"], "url": item["url"], "source": source["name"]}
        published = item.get("published")
        pos["issue_details"] = {
            "name": coin["name"], "url": f"https://www.coingecko.com/en/coins/{coin['id']}",
            "link_label": "CoinGecko", "address_label": "CoinGecko id",
            "passed_at": now.isoformat(), "market_cap_usd": coin.get("market_cap"),
            "change_24h_pct": coin.get("change_24h"),
            "extra": [
                ("News", f"[{item['title'][:120]}]({item['url']})"),
                ("Source", source["name"]),
                ("Published", f"{published:%Y-%m-%d %H:%M} UTC" if published else "not given"),
                ("Catalyst", by.get("Catalyst wording", "")),
                ("Counterparty", by.get("Named counterparty", "")),
                ("1h change", f"{coin['change_1h']:+.1f}%" if coin.get("change_1h") is not None
                 else "unknown"),
                ("24h volume", money(coin.get("volume"))),
            ],
        }
        return pos

    def _log(self, now, source, item, coins, passed, checks):
        new = not os.path.exists(self.candidates_path)
        coin = coins[0] if len(coins) == 1 else None
        published = item.get("published")
        with open(self.candidates_path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(CANDIDATE_COLUMNS)
            w.writerow([
                now.strftime("%Y-%m-%d %H:%M:%S"), source["name"], source.get("kind", "press"),
                published.strftime("%Y-%m-%d %H:%M:%S") if published else "",
                item["title"][:200], item["url"],
                coin["id"] if coin else ";".join(x["id"] for x in coins[:5]),
                coin["symbol"] if coin else "",
                "PASS" if passed else "FAIL",
                "; ".join(f"{ch.name}: {ch.detail}" for ch in checks if ch.status != PASS),
                " | ".join(f"{ch.name}={ch.status}" for ch in checks),
            ])
