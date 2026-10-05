"""The "news" paper strategy: buy a coin right after real, official news.

Every 15 minutes (news.every_minutes) it reads official sources only:
press-release wires (PR Newswire, GlobeNewswire, Business Wire), project
blogs, exchange announcements and new trading pairs, and the SEC (press
releases and fund filings), all listed in [[news.sources]] in config.toml.
Each new item that names a coin CoinGecko knows is a candidate, and goes
through rule-based checks (no AI, no X):

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
from urllib.parse import urljoin, urlparse

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
# data/news/unmatched.csv: crypto-related items that named no coin, to check
# whether the coin matching misses real candidates. Logging only.
UNMATCHED_COLUMNS = ["time_utc", "source", "kind", "published_utc", "title", "url"]
CANDIDATE_COLUMNS = ["time_utc", "source", "kind", "published_utc", "title", "url", "coin",
                     "symbol", "verdict", "failed", "checks"]
QUALIFIERS = r"(?:Network|Protocol|Foundation|Labs|Chain|Blockchain|[Tt]oken|[Cc]oin|DAO|Finance)"
# How long an item is remembered as seen. Dated items are only checked while
# under max_age_minutes old, so a day is plenty; undated items ("u" after the
# time) never age out of a feed, so they're remembered longer.
SEEN_DAYS = 1
SEEN_UNDATED_DAYS = 4
# A coin's name at the start of a company's name ("BNB Plus Corp.", "Solana
# Company Inc.") is the company, not the coin.
COMPANY = (r"(?:Corp(?:oration)?|Company|Inc|Incorporated|Ltd|Limited|LLC|L\.L\.C|PLC|plc"
           r"|Holdings?|Group|AB|AG|ASA|GmbH|N\.V|S\.A)\b")
# Words that make a company the coin's own project ("Ondo Finance Inc.").
PROJECT_WORDS = {"Network", "Protocol", "Foundation", "Labs", "Chain", "Blockchain", "Token",
                 "Coin", "DAO", "Finance", "Hashgraph"}
# Exchange headlines name the coin by its ticker: "WOJAK is available for
# trading!", "OKX will launch GRVT/USD", "Binance Will List Hyperliquid (HYPE)".
QUOTES = r"(?:USD|USDT|USDC|USDG|FDUSD|EUR|GBP|KRW|JPY|TRY|BRL|AUD|SGD|BTC|ETH|BNB)"
NOT_TICKERS = {"USD", "EUR", "GBP", "KRW", "JPY", "TRY", "BRL", "AUD", "SGD", "OKX", "API",
               "UTC", "VIP", "ETF", "NEW", "SPOT", "FAQ"}
# Words in a fund's name that aren't a coin ("Canary PEPE ETF").
FUND_WORDS = {"ETF", "ETP", "TRUST", "FUND", "INC", "LLC", "LP", "THE", "AND", "SHARES", "INDEX",
              "CRYPTO", "STAKED", "STAKING", "SPOT", "DIGITAL", "ASSET", "ASSETS", "INCOME",
              "STRATEGY", "PREMIUM", "DAILY", "TARGET", "LEVERAGED", "COVERED", "CALL", "PLUS",
              "SERIES", "CORE", "OPTION", "OPTIONS", "YIELD", "NEXT", "GEN", "TECHNOLOGY"}
# How long a working source may go without a new item before the health
# check warns (set stale_days on a source to change it).
STALE_DAYS = {"press": 4, "exchange": 14, "blog": 30, "regulator": 14, "filing": 4}
MONTHS = ("january february march april may june july august september october november "
          "december").split()


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

    def text(self, url, headers=None):
        resp = self._get(url, headers)
        # Feeds served without a charset are UTF-8 (the XML default), not
        # the Latin-1 requests would guess ("Stellar\u00e2\u0080\u0099s").
        if "charset" not in (resp.headers.get("content-type") or "").lower():
            return resp.content.decode("utf-8", "replace")
        return resp.text

    def json(self, url, headers=None):
        return self._get(url, headers).json()


def _utc(when):
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def seen_key(text):
    """A short fingerprint of an item, so the list of items already seen
    (kept for a few days in positions.json) stays small."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


ENGLISH = re.compile(r"\b(the|and|to|of|for|with|its|announces|launches|completes)\b",
                     re.IGNORECASE)
NOT_ENGLISH = re.compile("[äöüßàâçéèêëîïôùûñåæøœ]")


def is_english(item):
    """Roughly: is this headline in English? (Wires send translations too.)"""
    if re.search(r"/en/", item.get("url") or ""):
        return True
    title = item["title"]
    return bool(ENGLISH.search(title)) and not NOT_ENGLISH.search(title.lower())


def duplicate_keys(item, source):
    """Fingerprints that mark the same release seen elsewhere: the same
    headline on another wire; the same release id in the address (a
    translation on GlobeNewswire or Business Wire: .../3373842/0/sv/...);
    or, for press releases, the same wire, minute and company (PR Newswire
    gives each translation its own address)."""
    keys = [seen_key("title|" + re.sub(r"\W+", " ", item["title"].lower()).strip())]
    url = item.get("url") or ""
    rid = (re.search(r"globenewswire\.com/news-release/\d{4}/\d\d/\d\d/(\d+)/", url)
           or re.search(r"businesswire\.com/news/home/(\d+)/", url))
    if rid:
        keys.append(seen_key(f"release|{urlparse(url).netloc}|{rid.group(1)}"))
    if source.get("kind", "press") == "press" and item.get("published"):
        first = " ".join(re.findall(r"\w+", item["title"].lower())[:2])
        keys.append(seen_key(f"same time|{urlparse(url).netloc}|"
                             f"{item['published']:%Y-%m-%d %H:%M}|{first}"))
    return keys


def crypto_only(source):
    """Sources whose items must mention crypto at all (press wires and
    regulators, which mostly publish other news): set crypto_only on a
    source to change it."""
    if source.get("coin"):
        return False
    return source.get("crypto_only", source.get("kind", "press") in ("press", "regulator"))


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
            start = re.sub(r"\s+", " ", text[:200]).strip()[:60]
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


def _from_ms(value):
    ms = to_float(value)
    return datetime.fromtimestamp(ms / 1000, timezone.utc) if ms else None


def parse_okx(data):
    """Items from OKX's public announcement list (no key)."""
    items = []
    for group in (data or {}).get("data") or []:
        for a in group.get("details") or []:
            if a.get("title"):
                items.append({"id": a.get("url") or a["title"], "title": clean(a["title"]),
                              "summary": "", "url": a.get("url") or "",
                              "published": _from_ms(a.get("pTime"))})
    if not items:
        raise ApiError("no announcements in the answer")
    return items


def parse_bybit(data):
    """Items from Bybit's public announcement list (no key)."""
    items = []
    for a in ((data or {}).get("result") or {}).get("list") or []:
        if a.get("title"):
            items.append({"id": a.get("url") or a["title"], "title": clean(a["title"]),
                          "summary": clean(a.get("description") or "")[:2000],
                          "url": a.get("url") or "",
                          "published": _from_ms(a.get("publishTime") or a.get("dateTimestamp"))})
    if not items:
        raise ApiError("no announcements in the answer"
                       + (f" ({data.get('retMsg')})" if isinstance(data, dict)
                          and data.get("retMsg") not in (None, "", "OK") else ""))
    return items


def parse_markets(exchange, data):
    """{ticker: name} of every coin an exchange trades, from its public list
    of markets (no key). A ticker that wasn't there before is a new listing."""
    found = {}
    if exchange == "coinbase":           # api.exchange.coinbase.com/products
        for p in data if isinstance(data, list) else []:
            if p.get("base_currency") and p.get("status") != "delisted":
                found.setdefault(p["base_currency"].upper(), "")
    elif exchange == "upbit":            # api.upbit.com/v1/market/all
        for m in data if isinstance(data, list) else []:
            base = (m.get("market") or "").partition("-")[2]
            if base:
                found.setdefault(base.upper(), m.get("english_name") or "")
    elif exchange == "okx":              # okx.com/api/v5/public/instruments?instType=SPOT
        for m in (data.get("data") if isinstance(data, dict) else None) or []:
            if m.get("baseCcy"):
                found.setdefault(m["baseCcy"].upper(), "")
    else:
        raise ApiError(f"unknown exchange {exchange!r} (coinbase, upbit or okx)")
    if not found:
        raise ApiError("no markets in the answer")
    return found


def _page_date(text):
    """A date written on a blog page ("September 29, 2026" or "9.14.2026"),
    and the text without it."""
    m = re.search(r"\b(" + "|".join(MONTHS) + r") (\d{1,2}), (20\d\d)\b", text, re.IGNORECASE)
    if m:
        when = (int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    else:
        m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b", text)
        if not m:
            return None, text
        when = (int(m.group(3)), int(m.group(1)), int(m.group(2)))
    try:
        day = datetime(*when, tzinfo=timezone.utc)
    except ValueError:
        return None, text
    return day, (text[:m.start()] + " " + text[m.end():]).strip()


def parse_html(text, base_url, pattern):
    """Posts on a blog page that has no feed (Ripple, Avalanche): every link
    whose address matches `pattern`, its text as the title, and the date
    written next to it, if any."""
    found = {}
    for href, inner in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', text or "",
                                  re.DOTALL):
        if not re.search(pattern, href):
            continue
        url = urljoin(base_url, href)
        words = clean(inner)
        if len(words) > len(found.get(url, "")):     # the same post is linked several times
            found[url] = words
    items = []
    for url, words in found.items():
        published, words = _page_date(words)
        title = re.sub(r"^\d{1,2}\s+", "", words)                  # "01 The Swell..."
        title = re.sub(r"^.*?\bMinute Read\s+", "", title)         # "By Avalanche / 7 Minute Read"
        title = re.sub(r"\s*\bRead More\s*$", "", title).strip(" /")
        if not title:
            title = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").capitalize()
        items.append({"id": url, "title": title[:300], "summary": "", "url": url,
                      "published": published})
    if not items:
        raise ApiError("no posts found on the page (has its layout changed?)")
    return items


def parse_edgar(items):
    """SEC EDGAR's latest S-1 filings, kept only for funds ("Canary PEPE
    ETF", "Grayscale Solana Trust"): a new crypto fund files an S-1 first.
    Amendments (S-1/A) are kept too, but say so in the title."""
    out = []
    for it in items:
        m = re.match(r"^(\S+) - (.+?) \(\d{10}\)", it["title"])
        if not m or not re.search(r"\b(ETF|ETP|Trust|Fund)\b", m.group(2), re.IGNORECASE):
            continue
        form, company = m.group(1), m.group(2).strip()
        what = f"{form} filed" if "/A" not in form else f"{form} amendment filed"
        out.append(dict(it, title=f"{what}: {company}",
                        summary=f"{company} filed form {form} with the SEC."))
    return out


def read_source(http, source, now, plan, status):
    """One source's items (see parse_*). Market lists give an item for
    each coin that wasn't listed before."""
    fmt, url = source.get("format", "rss"), source["url"]
    headers = source.get("headers")
    args = (url, headers) if headers else (url,)
    if fmt == "markets":
        listed = parse_markets(source.get("exchange"), http.json(*args))
        return new_markets(source, listed, now, plan, status)
    if fmt in ("binance", "okx", "bybit"):
        items = {"binance": parse_binance, "okx": parse_okx,
                 "bybit": parse_bybit}[fmt](http.json(*args))
    elif fmt == "html":
        items = parse_html(http.text(*args), url, source["link_pattern"])
    elif fmt in ("rss", "edgar"):
        items = parse_feed(http.text(*args))
    else:
        raise ApiError(f"unknown format {fmt!r}")
    dated = [i["published"] for i in items if i["published"]]
    if dated:
        status["newest"] = max(dated).astimezone(timezone.utc).isoformat()
    if fmt == "edgar":
        status["filings"] = len(items)
        items = parse_edgar(items)
    if fmt == "html" or source.get("dates") == "day":
        # Only the day is given: a post from the last 2 days counts as
        # "first seen just now" (like an undated item); older ones are old.
        for i in items:
            day = i["published"]
            if day and (day.hour, day.minute) == (0, 0) and now - day < timedelta(days=2):
                i["published"] = None
    return items


def new_markets(source, listed, now, plan, status):
    """New tickers on an exchange's market list, as listing items. The
    first read only saves today's list."""
    name, state = source["name"], plan["state"]
    status["markets"] = len(listed)
    last = (state.get("markets_new") or {}).get(name)
    if last:
        status["newest"] = last
    known = (state.get("markets") or {}).get(name)
    if known is None:
        plan["markets"][name] = sorted(listed)
        status["note"] = f"first read: {len(listed)} coin(s) saved; new ones count as listings"
        return []
    known = set(known)
    new = sorted(s for s in listed if s not in known)
    plan["markets"][name] = sorted(known | set(listed))
    if len(new) > 20:
        # Not a normal day's listings: the list itself changed. Saved, not checked.
        status["note"] = f"{len(new)} new tickers at once: saved, not checked"
        return []
    if new:
        status["newest"] = plan["markets_new"][name] = now.isoformat()
    exchange = source.get("exchange_name") or source["exchange"].capitalize()
    items = []
    for sym in new:
        label = f"{listed[sym]} ({sym})" if listed[sym] else f"({sym})"
        items.append({"id": sym, "title": f"{exchange} lists {label} for trading",
                      "summary": f"{sym} is a new market on {exchange}.",
                      "url": (source.get("trade_url") or source["url"]).format(symbol=sym),
                      "published": now})
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

    def coin_list(self):
        """Every coin CoinGecko knows (about 20,000: id, symbol and name, no
        prices). One call, made only on runs with an exchange listing whose
        ticker isn't among the biggest coins."""
        if not hasattr(self, "_all"):
            self._all = [{"id": c.get("id"), "symbol": (c.get("symbol") or "").upper(),
                          "name": c.get("name") or ""}
                         for c in self._get("/coins/list") or [] if c.get("id")]
        return self._all


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


def company_name(name, text):
    """The company named after a coin in `text` ("BNB Plus Corp." for BNB),
    or None. A company that is the coin's own project ("Ondo Finance Inc.",
    "Quant Network Ltd") doesn't count."""
    for m in re.finditer(r"(?<![\w$])" + re.escape(name) + r"((?:\s+[A-Z][\w&'\u2019.-]*){0,2}?)"
                         r",?\s+" + COMPANY + r"\.?", text):
        if not PROJECT_WORDS & set(re.findall(r"[\w]+", m.group(1))):
            return m.group(0)
    return None


def find_coins(text, coins, c):
    """Coins named in `text`. A coin is named when its name appears with the
    same capitals as on CoinGecko. One-word names that are also everyday
    words ("Quant", "Flow", "Core") also need their ticker - "(QNT)" or
    "$QNT" - or a word like Network/Protocol/Token right after, unless they
    are listed in news.unambiguous_names. A company named after a coin
    ("BNB Plus Corp.") doesn't name the coin, unless the coin's ticker is
    given too."""
    found = []
    clear = set(c["unambiguous_names"])
    for coin in coins:
        name, sym = coin["name"], coin["symbol"]
        if len(name) < 3 or not re.search(r"(?<![\w$])" + re.escape(name) + r"(?!\w)", text):
            continue
        ticker = sym and len(sym) >= 2 and re.search(
            r"(\$" + re.escape(sym) + r"\b|\(" + re.escape(sym) + r"\))", text)
        if not ticker and company_name(name, text):
            continue
        if " " in name or name in clear:
            found.append(coin)
            continue
        qualified = re.search(re.escape(name) + r"\s+" + QUALIFIERS + r"\b", text)
        if ticker or qualified:
            found.append(coin)
    return _main_coins(found, c)


def _main_coins(found, c):
    # "Bitcoin Cash" also contains "Bitcoin": keep only the longer name.
    found = [x for x in found
             if not any(x is not y and x["name"] in y["name"] for y in found)]
    # Bitcoin, Ether and stablecoins mentioned in passing don't count when
    # another coin is the subject.
    main = [x for x in found if x["id"] not in c["background_coins"]]
    return main or found


def listing_tickers(title):
    """The tickers an exchange's listing headline names: "WOJAK is available
    for trading!", "OKX will launch GRVT/USD", "Binance Will List Hyperliquid
    (HYPE)", Upbit's "(XRP)"."""
    found = []
    m = re.match(r"^(.+?)\s+(?:is|are)\s+(?:now\s+)?(?:available|live)\s+(?:for|on)\s+trading",
                 title, re.IGNORECASE)
    if m:
        found += re.findall(r"\b[A-Z0-9]{2,15}\b", m.group(1))
    found += re.findall(r"\b([A-Z0-9]{2,15})[/-]" + QUOTES + r"\b", title)
    found += re.findall(r"\(([A-Z0-9]{2,15})\)", title)
    out = []
    for sym in found:
        if sym not in NOT_TICKERS and not sym.isdigit() and sym not in out:
            out.append(sym)
    return out


def ticker_coins(title, tickers, by_symbol):
    """The coin for each ticker: of the coins with that ticker, the one whose
    name is in the headline, else the biggest by market value."""
    named = []
    for sym in tickers:
        options = by_symbol.get(sym) or []
        if not options:
            continue
        in_title = [x for x in options if x["name"] and x["name"].lower() in title.lower()]
        best = max(in_title or options, key=lambda x: x.get("market_cap") or 0)
        if best not in named:
            named.append(best)
    return named


def fund_coins(fund, coins, c):
    """The coin a fund is named after ("Canary PEPE ETF", "Grayscale Solana
    Trust"): EDGAR writes names in any capitals, so names and tickers are
    matched in any case, among CoinGecko's biggest coins only."""
    words = [w.upper() for w in re.findall(r"[A-Za-z0-9]+", fund)]
    padded = " " + " ".join(words) + " "
    found = []
    for coin in coins:
        name = " ".join(w.upper() for w in re.findall(r"[A-Za-z0-9]+", coin["name"]))
        sym = coin["symbol"]
        by_name = len(name) >= 3 and name not in FUND_WORDS and f" {name} " in padded
        by_sym = len(sym) >= 3 and sym not in FUND_WORDS and sym in words
        if by_name or by_sym:
            found.append(coin)
    return _main_coins(found, c)


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

    strong = {"exchange": c["exchange_words"],
              "filing": c["filing_words"]}.get(kind, c["catalyst_words"])
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
    elif kind == "filing":
        checks.append(Check("Named counterparty", PASS,
                            f"a filing with the SEC ({source['name']})"))
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
        self.unmatched_path = os.path.join(self.folder, "unmatched.csv")

    def fetch(self, now=None):
        """Read the sources and CoinGecko, and check every new candidate.
        Changes nothing: apply() does the trading and saving."""
        now = now or now_utc()
        c = self.c
        state = copy.deepcopy(self.trader.state)
        plan = {"now": now, "notes": [], "sources": [], "candidates": [], "prices": {},
                "seen": {}, "state": state, "checked": False, "unmatched": [],
                "markets": {}, "markets_new": {}}
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
            if source.get("enabled") is False:
                continue
            status = {"name": source["name"], "kind": source.get("kind", "press")}
            try:
                items = read_source(self.http, source, now, plan, status)
                status.update(items=len(items), ok=True)
            except ApiError as exc:
                status.update(ok=False, error=str(exc)[:160])
                plan["sources"].append(status)
                continue
            # Items already older than max_age_minutes can never pass "Fresh
            # news", so they're only counted: never stored or checked. (Some
            # feeds, like Business Wire's, list thousands of old releases.)
            limit = timedelta(minutes=c["max_age_minutes"])
            recent = [i for i in items if not i["published"] or now - i["published"] <= limit]
            status["old"] = len(items) - len(recent)
            items = recent
            fresh = []
            # English first, so that of a release and its translations
            # (same time, same company) the English one is the one checked.
            items.sort(key=lambda i: not is_english(i))
            for item in items:
                key = seen_key(f"{source['name']}|{item['id'] or item['url'] or item['title']}")
                if key in seen or key in plan["seen"]:
                    continue
                mark = now.strftime("%Y-%m-%dT%H:%M") + ("" if item["published"] else "u")
                plan["seen"][key] = mark
                # The same release often goes out on several wires, and in
                # several languages: once is enough.
                same = duplicate_keys(item, source)
                if any(k in seen or k in plan["seen"] for k in same):
                    status["duplicates"] = status.get("duplicates", 0) + 1
                    continue
                for k in same:
                    plan["seen"][k] = mark
                fresh.append((source, item, key))
            status["new"] = len(fresh)
            plan["sources"].append(status)
            if source["name"] not in read:
                plan["sources_read"].append(source["name"])
                # First read: items without a date may be old; skip them.
                kept = [x for x in fresh if x[1]["published"]]
                backlog += len(fresh) - len(kept)
                fresh = kept
            new += fresh
        if backlog:
            plan["notes"].append(f"first read of a source: {backlog} undated item(s) already "
                                 "in its feed were noted and skipped")

        # 2. Coins: CoinGecko's top coins (only when there's something to match)
        #    and prices for open positions and project-blog coins.
        # Press releases that don't mention crypto at all are skipped before
        # any CoinGecko call (most of a newswire's items).
        crypto = _words(c["crypto_words"])
        unrelated = [(s, i, k) for s, i, k in new if crypto_only(s)
                     and not crypto.search(f"{i['title']}. {i['summary']}")]
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
            self._retry_later(plan, new)
            new = []
        coins = coin_index(coins)

        # Exchange headlines name a coin by its ticker. Tickers that aren't
        # among the biggest coins are looked up in CoinGecko's full coin list
        # (one call, only on runs that need it, plus one for their prices).
        by_symbol = {}
        for x in coins:
            by_symbol.setdefault(x["symbol"], []).append(x)
        tickers = {id(i): listing_tickers(i["title"]) for s, i, _ in new
                   if s.get("kind") == "exchange" and not s.get("coin")}
        missing = sorted({t for ts in tickers.values() for t in ts if t not in by_symbol})
        if missing:
            try:
                ids = [x["id"] for x in gecko.coin_list() if x["symbol"] in missing][:150]
                more = gecko.markets(ids=ids) if ids else []
                coins = coin_index(coins + more)
                for x in more:
                    by_symbol.setdefault(x["symbol"], []).append(x)
            except ApiError as exc:
                waiting = [x for x in new if set(tickers.get(id(x[1]), [])) & set(missing)]
                plan["notes"].append(f"CoinGecko's full coin list unavailable, {len(waiting)} "
                                     f"listing(s) wait for the next run: {exc}")
                self._retry_later(plan, waiting)
                new = [x for x in new if x not in waiting]
        by_id = {x["id"]: x for x in coins}
        plan["prices"] = {i: by_id[i]["price"] for i in held if by_id.get(i, {}).get("price")}

        # 3. Candidates: new items that name a coin, with every check.
        unnamed = 0
        for source, item, _ in new:
            text = f"{item['title']}. {item['summary']}"
            if source.get("coin"):
                named = [by_id[source["coin"]]] if source["coin"] in by_id else []
            elif source.get("kind") == "filing":
                named = fund_coins(item["title"].split(": ", 1)[-1], coins, c)
            else:
                named = find_coins(text, coins, c)
                if id(item) in tickers:
                    syms = {x["symbol"] for x in named}
                    named += [x for x in ticker_coins(item["title"], tickers[id(item)], by_symbol)
                              if x["symbol"] not in syms]
            if not named:
                unnamed += 1
                plan["unmatched"].append((source, item))
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

    def _retry_later(self, plan, items):
        """Leave these items unseen so they're checked on the next run."""
        for source, item, key in items:
            plan["seen"].pop(key, None)
            for k in duplicate_keys(item, source):
                plan["seen"].pop(k, None)
            if source.get("format") == "markets":
                plan["markets"].pop(source["name"], None)
                plan["markets_new"].pop(source["name"], None)

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
            def keep(v):
                days = SEEN_UNDATED_DAYS if v.endswith("u") else SEEN_DAYS
                return now - _utc(datetime.fromisoformat(v.rstrip("u"))) < timedelta(days=days)

            trader.state["seen"] = {k: v for k, v in seen.items() if keep(v)}
            trader.state["sources_read"] = plan["sources_read"]
            trader.state["sources"] = {s["name"]: s for s in plan["sources"]}
            for key in ("markets", "markets_new"):
                if plan.get(key):
                    trader.state.setdefault(key, {}).update(plan[key])

        for note in plan["notes"]:
            out(f"  ({note})")
        if plan["checked"]:
            out(f"  CoinGecko calls this month: {plan.get('coingecko_calls', 0):,} of "
                f"{c['coingecko_monthly_calls']:,}")
            for s in plan["sources"]:
                if s.get("ok") and "markets" in s:
                    out(f"  ok    {s['name']:<24} {s['markets']} coin(s) listed, "
                        f"{s.get('new', 0)} new" + (f" ({s['note']})" if s.get("note") else ""))
                elif s.get("ok"):
                    out(f"  ok    {s['name']:<24} {s['items']} item(s), {s.get('new', 0)} new, "
                        f"{s.get('old', 0)} older than {c['max_age_minutes']} min"
                        + (f", {s['duplicates']} duplicate(s)" if s.get("duplicates") else ""))
                else:
                    out(f"  FAIL  {s['name']:<24} {s['error']}")
        if plan.get("unmatched"):
            self._log_unmatched(now, plan["unmatched"])
            out(f"  Crypto news naming no coin (saved to {os.path.basename(self.unmatched_path)}):")
            for source, item in plan["unmatched"]:
                out(f"    - {source['name']}: {item['title'][:100]}")
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

    def _log_unmatched(self, now, unmatched):
        """Headline and source of each crypto-related item that named no coin."""
        if not unmatched:
            return
        new = not os.path.exists(self.unmatched_path)
        with open(self.unmatched_path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(UNMATCHED_COLUMNS)
            for source, item in unmatched:
                published = item.get("published")
                w.writerow([now.strftime("%Y-%m-%d %H:%M:%S"), source["name"],
                            source.get("kind", "press"),
                            published.strftime("%Y-%m-%d %H:%M:%S") if published else "",
                            item["title"][:200], item["url"]])

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


# ---------------------------------------------------------------------
# Checking the sources by hand
# ---------------------------------------------------------------------

def check_sources(cfg, http=None, out=print, now=None):
    """Read every source once and show what it gives: whether it works, how
    many items, the newest date and the latest headlines. Read-only: no
    CoinGecko, nothing saved. Returns the number of failing sources."""
    http = http or NewsHttp()
    now = now or now_utc()
    failing = 0
    for source in cfg["news"]["sources"]:
        name = source["name"]
        if source.get("enabled") is False:
            out(f"off   {name}: {source.get('note', 'turned off')}")
            continue
        plan = {"state": {}, "markets": {}, "markets_new": {}}
        status = {}
        try:
            items = read_source(http, source, now, plan, status)
        except ApiError as exc:
            failing += 1
            out(f"FAIL  {name}: {exc}")
            continue
        if "markets" in status:
            out(f"ok    {name}: {status['markets']} coins listed")
            continue
        newest = status.get("newest")
        extra = f", {status['filings']} filing(s) in all" if "filings" in status else ""
        out(f"ok    {name}: {len(items)} item(s){extra}, newest "
            f"{newest[:16].replace('T', ' ') + ' UTC' if newest else 'undated'}")
        dated = sorted(items, key=lambda i: i["published"] or now, reverse=True)
        for item in dated[:3]:
            when = f"{item['published']:%Y-%m-%d %H:%M}" if item["published"] else "undated"
            out(f"        {when}  {item['title'][:100]}")
    return failing


if __name__ == "__main__":
    import argparse
    import sys

    from screener.settings import load_config

    parser = argparse.ArgumentParser(description="The news strategy's sources.")
    parser.add_argument("--check-sources", action="store_true",
                        help="read every source once and show what it gives (saves nothing)")
    args = parser.parse_args()
    if not args.check_sources:
        parser.error("nothing to do: use --check-sources")
    sys.exit(1 if check_sources(load_config()) else 0)
