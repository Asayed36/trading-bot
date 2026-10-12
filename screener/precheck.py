"""The scanner alerts' "Pre-check": the checks one would otherwise do by hand when a
new listing alert arrives. INFORMATION ONLY: it never buys, sells, trades or touches a
wallet or key, and it changes nothing about how alerts are detected, deduplicated,
capped, mentioned or assigned (screener/scanner_alert.py). Only public, read-only
endpoints, and the keys the repo already uses (CoinGecko's, Anthropic's).

For one listing alert it works out, each part on its own (a part that fails is
written as "lookup failed: <reason>", the others still show):
  1. what the coin is (name, ticker, the announcement text and link);
  2. whether the announcing exchange has a SPOT market for it (its public market
     list: for OKX the instruments endpoint, SPOT versus SWAP / FUTURES / MARGIN);
  3. whether the ticker is shared with other coins on CoinGecko (its coin list), at
     most two calls, counted against the scanner's own monthly CoinGecko budget;
  4. the exchange's own last price, 24h change and 24h volume (USDT) for the spot
     pair, the price at detection, and the move since the announcement;
  5. the basic checks, with the thresholds from config.toml [scanner_alert.precheck];
  6. an optional second opinion from the existing Claude Haiku 4.5 check
     (screener/news_ai.py, within its daily limit).
Then data/scanner/alert_checks.csv gets one row per alert, and the price is followed up
1, 6 and 24 hours later (the same CSV-as-memory idea as screener/listing_track.py).
"""

import csv
import os
import re
import time
from datetime import datetime, timedelta, timezone

from screener.api import ApiError
from screener.news_ai import AiChecker

COINGECKO = "https://api.coingecko.com/api/v3"
USD_LIKE = ("USDT", "USDC", "USD", "FDUSD", "USDG", "DAI", "TUSD", "PYUSD", "RLUSD", "USD1")
CHECKPOINTS = (("1h", 60, 30), ("6h", 360, 60), ("24h", 1440, 120))   # name, minutes, grace minutes
BASIC_CHECKS = ("spot", "not a ticker clash", "move since the announcement", "24h change",
                "24h volume", "not a stablecoin or wrapped/staked token")
TIME = "%Y-%m-%d %H:%M:%S"

COLUMNS = ["key", "time_utc", "feed", "exchange", "ticker", "name", "issue", "spot", "pairs", "pair",
           "quote", "clash_count", "clash_detail", "price_at_detection", "price_source", "exchange_change_24h_pct",
           "volume_24h_usdt", "price_at_announcement", "move_since_announcement_pct",
           "check_spot", "check_clash", "check_move", "check_24h", "check_volume", "check_not_stable",
           "verdict", "verdict_line", "ai_answer"] + [
    c for name, _, _ in CHECKPOINTS for c in (f"price_{name}", f"change_{name}_pct", f"time_{name}")]


class LookupFailed(Exception):
    pass


# What a part of the pre-check can raise without the rest being lost (a bad answer
# from an exchange is one of these too).
LOOKUP_ERRORS = (LookupFailed, KeyError, TypeError, ValueError, IndexError, AttributeError)


def reason(exc):
    return f"lookup failed: {str(exc)[:140]}"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pair_rank(quote):
    if quote in USD_LIKE:
        return USD_LIKE.index(quote)
    return 20 if quote == "KRW" else 50


def best_pair(pairs):
    """The pair to read prices from: a USDT-like quote first."""
    return min(pairs, key=lambda p: (pair_rank(p["quote"]), p["id"])) if pairs else None


def pair(pid, base, quote, **extra):
    return dict({"id": pid, "base": base, "quote": quote}, **extra)


# ---------------------------------------------------------------------
# The exchanges' public endpoints
# ---------------------------------------------------------------------

class Venue:
    name = ""

    def __init__(self, http):
        self.http = http

    def _json(self, url):
        try:
            return self.http.json(url)
        except ApiError as exc:
            raise LookupFailed(str(exc)) from exc

    @staticmethod
    def _spot(pairs, text_on_no):
        if pairs:
            return {"status": "yes", "pairs": pairs,
                    "text": "SPOT: yes (pairs: " + ", ".join(p["id"] for p in pairs[:8]) + ")"}
        return {"status": "no", "pairs": [], "text": text_on_no}

    def spot(self, coin):
        raise NotImplementedError

    def ticker(self, p):
        raise NotImplementedError

    def price_at(self, p, when):
        """The price at `when` (a datetime), None when the pair had no trade then, or
        raises LookupFailed. Only the exchanges with announcement feeds have it."""
        raise LookupFailed(f"{self.name}: no price history lookup")


class Binance(Venue):
    """data-api.binance.vision: Binance's spot-only public market-data mirror (the main
    API refuses GitHub's servers)."""
    name = "Binance"
    BASE = "https://data-api.binance.vision/api/v3"
    QUOTES = {"USDT", "USDC", "FDUSD", "TUSD", "USD1", "BTC", "ETH", "BNB", "TRY", "EUR", "BRL", "JPY",
              "ARS", "MXN", "PLN", "RON", "UAH", "ZAR", "CZK", "AUD", "GBP", "IDR", "RUB", "DAI"}

    def spot(self, coin):
        data = self._json(f"{self.BASE}/ticker/price")
        if not isinstance(data, list):
            raise LookupFailed("unexpected answer from Binance's price list")
        pairs = [pair(r["symbol"], coin, r["symbol"][len(coin):]) for r in data
                 if r["symbol"].startswith(coin) and r["symbol"][len(coin):] in self.QUOTES]
        return self._spot(pairs, "NOT SPOT: no spot market for it on Binance yet (its public spot "
                                 "price list has none; derivatives are not checked)")

    def ticker(self, p):
        d = self._json(f"{self.BASE}/ticker/24hr?symbol={p['id']}")
        return {"last": _f(d.get("lastPrice")), "change_pct": _f(d.get("priceChangePercent")),
                "volume_quote": _f(d.get("quoteVolume")), "quote": p["quote"]}

    def price_at(self, p, when):
        ms = int(when.timestamp() * 1000)
        d = self._json(f"{self.BASE}/klines?symbol={p['id']}&interval=1m&startTime={ms}&limit=1")
        if not d or abs(int(d[0][0]) - ms) > 120_000:
            return None
        return _f(d[0][1])


class Coinbase(Venue):
    name = "Coinbase"
    BASE = "https://api.exchange.coinbase.com"

    def spot(self, coin):
        data = self._json(f"{self.BASE}/products")
        if not isinstance(data, list):
            raise LookupFailed("unexpected answer from Coinbase's product list")
        pairs = [pair(r["id"], coin, r.get("quote_currency", r["id"].split("-")[-1]))
                 for r in data if r.get("base_currency") == coin and r.get("status") == "online"
                 and not r.get("trading_disabled")]
        return self._spot(pairs, "NOT SPOT: no online spot product for it in Coinbase's public list")

    def ticker(self, p):
        d = self._json(f"{self.BASE}/products/{p['id']}/stats")
        last, open_, vol = _f(d.get("last")), _f(d.get("open")), _f(d.get("volume"))
        return {"last": last, "change_pct": (last / open_ - 1) * 100 if last and open_ else None,
                "volume_quote": vol * last if vol is not None and last else None, "quote": p["quote"]}


class Upbit(Venue):
    name = "Upbit"
    BASE = "https://api.upbit.com/v1"

    def spot(self, coin):
        data = self._json(f"{self.BASE}/market/all")
        if not isinstance(data, list):
            raise LookupFailed("unexpected answer from Upbit's market list")
        pairs = []
        for r in data:
            quote, _, base = r["market"].partition("-")
            if base == coin:
                pairs.append(pair(r["market"], coin, quote))
        return self._spot(pairs, "NOT SPOT: no market for it in Upbit's public market list")

    def ticker(self, p):
        d = self._json(f"{self.BASE}/ticker?markets={p['id']}")[0]
        last, change, vol = _f(d.get("trade_price")), _f(d.get("signed_change_rate")), \
            _f(d.get("acc_trade_price_24h"))
        quote = p["quote"]
        if quote == "KRW":
            rate = _f(self._json(f"{self.BASE}/ticker?markets=KRW-USDT")[0].get("trade_price"))
            if rate:
                last, vol, quote = (last / rate if last else None), (vol / rate if vol else None), "USDT"
        return {"last": last, "change_pct": change * 100 if change is not None else None,
                "volume_quote": vol, "quote": quote,
                "note": "change is against the previous day's close, converted from KRW at Upbit's "
                        "KRW-USDT rate" if p["quote"] == "KRW" else "change is against the previous "
                                                                  "day's close"}


class Okx(Venue):
    name = "OKX"
    BASE = "https://www.okx.com/api/v5"

    def _instruments(self, kind, coin):
        data = self._json(f"{self.BASE}/public/instruments?instType={kind}")
        if not isinstance(data, dict) or data.get("code") != "0":
            raise LookupFailed(f"OKX {kind} list: unexpected answer")
        return [r["instId"] for r in data.get("data") or []
                if r.get("instId", "").startswith(coin + "-") and r.get("state", "live") == "live"]

    def spot(self, coin):
        spot = self._instruments("SPOT", coin)         # a failure here is "unknown"
        if spot:
            return self._spot([pair(i, coin, i.split("-")[1]) for i in spot], "")
        others = {}
        for kind in ("SWAP", "FUTURES", "MARGIN"):
            try:
                others[kind] = self._instruments(kind, coin)
            except LookupFailed:
                others[kind] = None
        derivs = (others["SWAP"] or []) + (others["FUTURES"] or [])
        if derivs:
            return {"status": "no", "pairs": [], "text": "NOT SPOT: derivatives only (perpetual/futures): "
                    + ", ".join(derivs[:4])}
        if others["MARGIN"]:
            return {"status": "no", "pairs": [], "text": "NOT SPOT: margin market only: "
                    + ", ".join(others["MARGIN"][:4])}
        if None in others.values():
            return {"status": "unknown", "pairs": [],
                    "text": "SPOT: unknown (no spot market in OKX's list, but its derivatives lists "
                            "could not be read)"}
        return {"status": "no", "pairs": [], "text": "NOT SPOT: not in OKX's SPOT, SWAP, FUTURES or "
                                                      "MARGIN lists (yet)"}

    def ticker(self, p):
        d = self._json(f"{self.BASE}/market/ticker?instId={p['id']}")
        row = ((d or {}).get("data") or [None])[0]
        if not row:
            raise LookupFailed("OKX has no ticker for " + p["id"])
        last, open_ = _f(row.get("last")), _f(row.get("open24h"))
        return {"last": last, "change_pct": (last / open_ - 1) * 100 if last and open_ else None,
                "volume_quote": _f(row.get("volCcy24h")), "quote": p["quote"]}

    def price_at(self, p, when):
        ms = int(when.timestamp() * 1000)
        d = self._json(f"{self.BASE}/market/history-candles?instId={p['id']}&bar=1m&after={ms + 60_001}&limit=1")
        rows = (d or {}).get("data") or []
        if not rows or abs(int(rows[0][0]) - ms) > 120_000:
            return None
        return _f(rows[0][1])


class Kraken(Venue):
    name = "Kraken"
    BASE = "https://api.kraken.com/0/public"
    RENAMED = {"XBT": "BTC", "XDG": "DOGE"}

    def spot(self, coin):
        d = self._json(f"{self.BASE}/AssetPairs")
        if not isinstance(d, dict) or d.get("error"):
            raise LookupFailed("Kraken's pair list: " + str((d or {}).get("error"))[:80])
        pairs = []
        for r in (d.get("result") or {}).values():
            ws = r.get("wsname") or ""
            base, _, quote = ws.partition("/")
            base, quote = self.RENAMED.get(base, base), self.RENAMED.get(quote, quote)
            if base == coin and r.get("status", "online") == "online":
                pairs.append(pair(r["altname"], coin, quote))
        return self._spot(pairs, "NOT SPOT: no online spot pair for it in Kraken's public list")

    def _result(self, d):
        if not isinstance(d, dict) or d.get("error") or not d.get("result"):
            raise LookupFailed("Kraken: " + str((d or {}).get("error") or "no result")[:80])
        return d["result"]

    def ticker(self, p):
        row = next(iter(self._result(self._json(f"{self.BASE}/Ticker?pair={p['id']}")).values()))
        last, open_ = _f(row["c"][0]), _f(row.get("o"))
        vol, vwap = _f(row["v"][1]), _f(row["p"][1])
        return {"last": last, "change_pct": (last / open_ - 1) * 100 if last and open_ else None,
                "volume_quote": vol * vwap if vol is not None and vwap else None, "quote": p["quote"],
                "note": "change is against today's 00:00 UTC open"}

    def price_at(self, p, when):
        ts = int(when.timestamp())
        res = self._result(self._json(f"{self.BASE}/OHLC?pair={p['id']}&interval=1&since={ts - 60}"))
        rows = next((v for k, v in res.items() if k != "last"), [])
        if not rows or abs(int(rows[0][0]) - ts) > 120:
            return None
        return _f(rows[0][1])


VENUES = {v.name: v for v in (Binance, Coinbase, Upbit, Okx, Kraken)}


# ---------------------------------------------------------------------
# The checks (pure)
# ---------------------------------------------------------------------

def evaluate(facts, t):
    """The basic checks from the facts and the thresholds `t`
    ([scanner_alert.precheck]). Returns ([(name, "pass"|"fail"|"unknown", detail)],
    verdict "PASS"|"FAIL", line). An unknown part is never a pass: it is listed in the
    FAILS line as unverified."""
    out = []

    def add(name, status, detail):
        out.append((name, status, detail))

    spot = facts.get("spot")
    add("spot", {"yes": "pass", "no": "fail"}.get(spot, "unknown"),
        facts.get("spot_text") or "unknown")
    n = facts.get("clash_count")
    if n is None:
        add("not a ticker clash", "unknown", facts.get("clash_note") or "unknown")
    elif n > 1:
        add("not a ticker clash", "fail", f"{n} different coins share this ticker")
    else:
        add("not a ticker clash", "pass", "not on CoinGecko yet" if n == 0 else "one coin uses this ticker")
    move = facts.get("move_pct")
    limit = t["max_move_since_announcement_pct"]
    if move is None:
        add("move since the announcement", "unknown", facts.get("move_note") or "unknown")
    else:
        add("move since the announcement", "pass" if move < limit else "fail",
            f"{move:+.1f}% (limit +{limit:g}%)")
    change = facts.get("change_24h_pct")
    limit = t["max_change_24h_pct"]
    if change is None:
        add("24h change", "unknown", facts.get("ticker_note") or "unknown")
    else:
        add("24h change", "pass" if change < limit else "fail", f"{change:+.1f}% (limit +{limit:g}%)")
    volume = facts.get("volume_usdt")
    limit = t["min_volume_24h_usdt"]
    if volume is None:
        add("24h volume", "unknown", facts.get("volume_note") or facts.get("ticker_note") or "unknown")
    else:
        add("24h volume", "pass" if volume >= limit else "fail",
            f"{volume:,.0f} USDT (at least {limit:,.0f})")
    stable = facts.get("stable")
    add("not a stablecoin or wrapped/staked token", "unknown" if stable is None else
        "fail" if stable else "pass", facts.get("stable_note") or "")
    bad = [f"{name}: {detail}" if status == "fail" else f"{name}: unverified ({detail})"
           for name, status, detail in out if status != "pass"]
    if bad:
        return out, "FAIL", "FAILS: " + "; ".join(bad)
    return out, "PASS", "PASSES the basic checks"


def stable_or_wrapped(symbol, names, t):
    """(True/False, note): a stablecoin by ticker, or wrapped/staked/bridged by a CoinGecko name."""
    if symbol.lower() in [s.lower() for s in t["stablecoin_symbols"]]:
        return True, f"{symbol} is a stablecoin ticker"
    for name in names:
        if re.search(r"\b(" + "|".join(re.escape(w) for w in t["wrapped_words"]) + r")\b", name, re.I):
            return True, f"{name} looks wrapped/staked/bridged"
    return False, "checked by ticker" + (" and CoinGecko name" if names else " only (no CoinGecko name)")


# ---------------------------------------------------------------------
# One alert's pre-check
# ---------------------------------------------------------------------

class Precheck:
    def __init__(self, cfg, http, state, ai_key=None, ai_client=None, cg_key=None, clock=time.monotonic):
        self.t = cfg["scanner_alert"]["precheck"]
        self.cfg, self.http, self.state = cfg, http, state     # state: a dict kept between runs
        self.ai_key, self.ai_client, self.cg_key, self.clock = ai_key, ai_client, cg_key, clock
        self._cg_list = None

    # -- CoinGecko (budgeted) --

    def _meter(self, now):
        month = now.strftime("%Y-%m")
        meter = self.state.get("coingecko")
        if not meter or meter.get("month") != month:
            meter = self.state["coingecko"] = {"month": month, "calls": 0}
        return meter

    def _cg(self, path, now):
        meter = self._meter(now)
        limit = self.t["coingecko_monthly_calls"]
        if meter["calls"] >= limit:
            raise LookupFailed(f"the scanner's CoinGecko budget for {meter['month']} is used up "
                               f"({meter['calls']} of {limit} calls); no CoinGecko lookup")
        meter["calls"] += 1
        headers = {"x-cg-demo-api-key": self.cg_key} if self.cg_key else None
        try:
            return self.http.json(f"{COINGECKO}{path}", headers)
        except ApiError as exc:
            raise LookupFailed(str(exc)) from exc

    def clash(self, symbol, now):
        """({"count", "coins": [(name, market cap)], "names"}, note). Raises LookupFailed."""
        if self._cg_list is None:
            data = self._cg("/coins/list", now)
            if not isinstance(data, list):
                raise LookupFailed("unexpected answer from CoinGecko's coin list")
            self._cg_list = data
        same = [c for c in self._cg_list if (c.get("symbol") or "").upper() == symbol.upper()]
        if not same:
            return {"count": 0, "coins": [], "names": []}
        coins = []
        try:
            rows = self._cg(f"/coins/markets?vs_currency=usd&symbols={symbol.lower()}"
                            "&include_tokens=all&order=market_cap_desc&per_page=250", now)
            coins = [(r.get("name") or r.get("id"), _f(r.get("market_cap"))) for r in (rows or [])[:3]]
        except LOOKUP_ERRORS as exc:
            coins = [(c.get("name") or c.get("id"), None) for c in same[:3]]
            return {"count": len(same), "coins": coins, "names": [n for n, _ in coins],
                    "note": f"market caps: {reason(exc)}"}
        if not coins:
            coins = [(c.get("name") or c.get("id"), None) for c in same[:3]]
        return {"count": len(same), "coins": coins, "names": [n for n, _ in coins]}

    # -- the whole thing --

    def run(self, alert, now):
        """The pre-check of a listing alert: a dict of facts, checks and the issue section."""
        deadline = self.clock() + self.t.get("max_seconds", 90)
        late = lambda: self.clock() > deadline          # noqa: E731
        r = {"key": alert["key"], "ticker": alert["coin"], "exchange": alert["exchange"],
             "feed": alert["source"], "lookups": {}}
        # 3. the ticker on CoinGecko
        cg = None
        try:
            if late():
                raise LookupFailed("out of time")
            cg = self.clash(alert["coin"], now)
            r["lookups"]["clash"] = cg
        except LOOKUP_ERRORS as exc:
            r["lookups"]["clash_error"] = reason(exc)
        # 2. spot or not
        venue = VENUES.get(alert["exchange"])
        spot = None
        try:
            if venue is None:
                raise LookupFailed(f"no public market list known for {alert['exchange']}")
            if late():
                raise LookupFailed("out of time")
            venue = venue(self.http)
            spot = venue.spot(alert["coin"])
        except LOOKUP_ERRORS as exc:
            r["lookups"]["spot_error"] = reason(exc)
        # 4. price and move
        ticker = at_announce = second = None
        p = best_pair(spot["pairs"]) if spot else None
        detected = None
        if p:
            try:
                if late():
                    raise LookupFailed("out of time")
                ticker = venue.ticker(p)
                detected = datetime.now(timezone.utc)
                ann = alert.get("announced")
                if ann:
                    try:
                        at_announce = venue.price_at(p, datetime.fromisoformat(ann).astimezone(timezone.utc))
                        r["lookups"]["announce_checked"] = True
                    except LOOKUP_ERRORS as exc:
                        r["lookups"]["announce_error"] = reason(exc)
                if not late():
                    second = venue.ticker(p)
            except LOOKUP_ERRORS as exc:
                r["lookups"]["ticker_error"] = reason(exc)
        facts = self._facts(alert, cg, spot, p, ticker, at_announce, second, r["lookups"])
        r["facts"] = facts
        r["checks"], r["verdict"], r["verdict_line"] = evaluate(facts, self.t)
        r["pair"], r["ticker_data"], r["detected_at"], r["spot"] = p, ticker, detected, spot
        r["ai"] = self._ai(alert, now, facts, cg)
        r["markdown"] = self.markdown(alert, r, cg, spot, p, ticker, at_announce, second)
        return r

    def _facts(self, alert, cg, spot, p, ticker, at_announce, second, lookups):
        t = self.t
        f = {"spot": (spot or {}).get("status", "unknown"),
             "spot_text": (spot or {}).get("text") or lookups.get("spot_error") or "unknown"}
        if cg is not None:
            f["clash_count"] = cg["count"]
        else:
            f["clash_note"] = lookups.get("clash_error", "unknown")
        # the biggest coin with this ticker is the one judged (a ticker shared with some bridged
        # or peg copies is flagged as a clash on its own line)
        f["stable"], f["stable_note"] = stable_or_wrapped(alert["coin"], ((cg or {}).get("names") or [])[:1], t)
        if ticker and ticker.get("last"):
            f["price"] = ticker["last"]
            f["change_24h_pct"] = ticker.get("change_pct")
            usd = ticker.get("quote") in USD_LIKE
            f["volume_usdt"] = ticker.get("volume_quote") if usd else None
            if not usd:
                f["volume_note"] = f"the best pair is quoted in {ticker.get('quote')}, not USDT"
            # the move since the announcement
            if at_announce:
                f["price_at_announcement"] = at_announce
                f["move_pct"] = (ticker["last"] / at_announce - 1) * 100
            elif alert.get("announced") and lookups.get("announce_checked"):
                f["move_pct"] = 0.0
                f["move_note"] = "the pair had no trades yet at the announcement"
            elif not alert.get("announced"):
                f["move_pct"] = 0.0
                f["move_note"] = "no announcement time: measured from detection"
            else:
                f["move_note"] = lookups.get("announce_error", "unknown")
            if second and second.get("last"):
                f["price_now"] = second["last"]
        else:
            f["ticker_note"] = lookups.get("ticker_error") or (
                "no spot pair to read a price from" if spot and not spot.get("pairs") else
                lookups.get("spot_error", "unknown"))
        return f

    # -- the AI second opinion --

    def _ai(self, alert, now, facts, cg):
        cfg_ai = dict(self.cfg["news"]["ai"], daily_limit=min(self.cfg["news"]["ai"]["daily_limit"],
                                                              self.t["ai_daily_limit"]))
        checker = AiChecker(cfg_ai, self.ai_key, self.state, now, self.ai_client)
        known = [f"spot: {facts.get('spot_text')}"]
        if "clash_count" in facts:
            known.append(f"{facts['clash_count']} coin(s) on CoinGecko share the ticker")
        item = {"title": alert["title"],
                "summary": (alert.get("text") or "") + " Facts from the exchange's public lists: "
                           + "; ".join(known),
                "published": datetime.fromisoformat(alert["announced"]) if alert.get("announced") else None}
        names = (cg or {}).get("names") or []
        named = [{"name": names[0] if names else alert["coin"], "symbol": alert["coin"]}]
        verdict = checker.check(item, {"name": alert["source"], "kind": "exchange"}, named)
        if verdict.get("status") != "ok":
            return f"not checked ({verdict.get('note')})"
        real = bool(verdict["positive_catalyst"] and verdict["catalyst_kind"] == "listing"
                    and verdict["about_one_coin"] and not verdict["false_match"]
                    and not verdict["duplicate"])
        flags = [f for f, on in (("false match", verdict["false_match"]),
                                 ("repeat of a recent headline", verdict["duplicate"]),
                                 ("several coins", not verdict["about_one_coin"])) if on]
        return (("YES: a real new listing of a real project" if real
                 else "NO: something else (not a clear new listing of a real project)")
                + (f" [{', '.join(flags)}]" if flags else "") + f" - {verdict['reason'][:200]}")

    # -- the issue text --

    def markdown(self, alert, r, cg, spot, p, ticker, at_announce, second):
        f, look = r["facts"], r["lookups"]
        L = ["### Pre-check (information, not advice)"]
        names = (cg or {}).get("names") or []
        count = (cg or {}).get("count") or 0
        name = (names[0] if count == 1 else f"{names[0]} (the biggest of {count} coins using this ticker)"
                if names else None)
        if alert.get("how", "").startswith("a new pair"):
            said = "no announcement text: the coin appeared in the exchange's public market list"
        else:
            said = f"\"{alert['title'][:300]}\"" + (f" - {alert['text'][:300]}" if alert.get("text") else "")
        L.append(f"1. **What it is:** {name + ' ' if name else ''}({alert['coin']}) on {alert['exchange']}. "
                 f"{said}" + (f" Link: {alert['url']}" if alert.get("url") else ""))
        L.append(f"2. **Spot or not:** {f['spot_text']}")
        if cg is None:
            L.append(f"3. **Ticker on CoinGecko:** {look.get('clash_error', 'lookup failed')}")
        elif cg["count"] == 0:
            L.append("3. **Ticker on CoinGecko:** **NOT IN COINGECKO (new or unknown token)**")
        else:
            shown = "; ".join(f"{n} (market cap {'unknown' if c is None else f'${c:,.0f}'})"
                              for n, c in cg["coins"])
            flag = " **TICKER CLASH: verify on the exchange**" if cg["count"] > 1 else ""
            L.append(f"3. **Ticker on CoinGecko:** {cg['count']} coin(s) use {alert['coin']}: {shown}.{flag}"
                     + (f" ({cg['note']})" if cg.get("note") else ""))
        if ticker and ticker.get("last"):
            q = ticker.get("quote")
            parts = [f"last {ticker['last']:.8g} {q}"]
            parts.append("24h change " + (f"{f['change_24h_pct']:+.1f}%" if f.get("change_24h_pct") is not None
                                          else "unknown"))
            parts.append("24h volume " + (f"{f['volume_usdt']:,.0f} USDT" if f.get("volume_usdt") is not None
                                          else f"unknown ({f.get('volume_note', 'no USDT figure')})"))
            line = f"4. **Price on {alert['exchange']} ({p['id']}):** " + ", ".join(parts) + "."
            line += f" Price at detection {ticker['last']:.8g} {q}"
            if second and second.get("last"):
                line += f"; {(second['last'] / ticker['last'] - 1) * 100:+.1f}% since detection (read again a few seconds later; later moves are in data/scanner/alert_checks.csv at 1h, 6h and 24h)"
            line += "."
            if "price_at_announcement" in f:
                line += f" Price at the announcement {f['price_at_announcement']:.8g}: {f['move_pct']:+.1f}% since."
            elif f.get("move_note"):
                line += f" Move since the announcement: {f['move_pct']:+.1f}% ({f['move_note']})." \
                    if f.get("move_pct") is not None else f" Move since the announcement: unknown ({f['move_note']})."
            if ticker.get("note"):
                line += f" ({ticker['note']})"
            L.append(line)
        else:
            L.append("4. **Price:** " + (look.get("ticker_error") or f.get("ticker_note") or "unknown"))
        L.append(f"5. **Basic checks:** **{r['verdict_line']}** (information, not advice)")
        for name_, status, detail in r["checks"]:
            L.append(f"   - {'ok' if status == 'pass' else 'FAIL' if status == 'fail' else '?'} "
                     f"{name_}: {detail}")
        L.append(f"6. **AI second opinion (Claude Haiku 4.5, it decides nothing):** {r['ai']}")
        return "\n".join(L)

    # -- the CSV row --

    def row(self, alert, r, issue, now):
        f, ticker = r["facts"], r.get("ticker_data") or {}
        cg = r["lookups"].get("clash")
        by = {name: status for name, status, _ in r["checks"]}
        spot_pairs = ", ".join(p["id"] for p in (r.get("spot") or {}).get("pairs", [])[:8])
        pair_id = (r.get("pair") or {}).get("id", "")
        row = {
            "key": alert["key"], "time_utc": now.strftime(TIME), "feed": alert["source"],
            "exchange": alert["exchange"], "ticker": alert["coin"],
            "name": ((cg or {}).get("names") or [""])[0],
            "issue": issue, "spot": f["spot"], "pairs": spot_pairs, "pair": pair_id,
            "quote": (r.get("pair") or {}).get("quote", ""),
            "clash_count": "" if f.get("clash_count") is None else f["clash_count"],
            "clash_detail": "; ".join(f"{n} ({'?' if c is None else f'{c:.0f}'})" for n, c in (cg or {}).get("coins", [])),
            "price_at_detection": "" if not ticker.get("last") else f"{ticker['last']:.10g}",
            "price_source": f"{alert['exchange']} {pair_id} {ticker.get('quote', '')}".strip() if ticker.get("last") else "",
            "exchange_change_24h_pct": "" if f.get("change_24h_pct") is None else f"{f['change_24h_pct']:.4g}",
            "volume_24h_usdt": "" if f.get("volume_usdt") is None else f"{f['volume_usdt']:.0f}",
            "price_at_announcement": "" if "price_at_announcement" not in f else f"{f['price_at_announcement']:.10g}",
            "move_since_announcement_pct": "" if f.get("move_pct") is None else f"{f['move_pct']:.4g}",
            "check_spot": by.get("spot", ""), "check_clash": by.get("not a ticker clash", ""),
            "check_move": by.get("move since the announcement", ""), "check_24h": by.get("24h change", ""),
            "check_volume": by.get("24h volume", ""),
            "check_not_stable": by.get("not a stablecoin or wrapped/staked token", ""),
            "verdict": r["verdict"], "verdict_line": r["verdict_line"], "ai_answer": r["ai"],
        }
        return row


# ---------------------------------------------------------------------
# The CSV and the follow-ups
# ---------------------------------------------------------------------

class AlertChecks:
    """data/scanner/alert_checks.csv: one row per alert. Its own memory, like
    screener/listing_track.py: a follow-up price is pending while its cells are blank
    and it is not past its grace time; one missed stays blank (never zero)."""

    def __init__(self, path):
        self.path = path

    def rows(self):
        try:
            with open(self.path, newline="") as fh:
                return list(csv.DictReader(fh))
        except OSError:
            return []

    def _write(self, rows):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, self.path)

    def add(self, row):
        rows = self.rows()
        if any(r["key"] == row["key"] for r in rows):
            return False
        rows.append(row)
        self._write(rows)
        return True

    def due(self, now):
        """[(row index, checkpoint name)] due now: blank, past its time, not past its grace."""
        now = now.replace(tzinfo=None) if now.tzinfo else now
        out = []
        for i, r in enumerate(self.rows()):
            if not r.get("pair") or not r.get("price_at_detection"):
                continue
            start = datetime.strptime(r["time_utc"], TIME)
            for name, minutes, grace in CHECKPOINTS:
                if r.get(f"price_{name}") or r.get(f"time_{name}"):
                    continue
                due = start + timedelta(minutes=minutes)
                if due <= now <= due + timedelta(minutes=grace):
                    out.append((i, name))
        return out

    def fill(self, results, now):
        """results: {(row index, name): price or None}. A price None (lookup failed) stays blank."""
        rows, changed = self.rows(), False
        stamp = (now.replace(tzinfo=None) if now.tzinfo else now).strftime(TIME)
        for (i, name), price in results.items():
            if price is None:
                continue
            base = _f(rows[i]["price_at_detection"])
            rows[i][f"price_{name}"] = f"{price:.10g}"
            rows[i][f"change_{name}_pct"] = f"{(price / base - 1) * 100:.4g}" if base else ""
            rows[i][f"time_{name}"] = stamp
            changed = True
        if changed:
            self._write(rows)
        return changed
