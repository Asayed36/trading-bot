"""The X post watcher (xposts_bot.py, the xposts service on your server). RECORDING ONLY: it
never trades and never posts. [xposts] in config.toml.

Every every_seconds (120) it asks X's API (pay-per-use, app-only Bearer token, read-only) for
each watched account's newest ORIGINAL posts (no replies, no reposts), only those newer than
the last one seen (since_id; for an account seen for the first time, only those posted after
the watcher started watching it), and saves each new post in data/xposts/posts-YYYY-MM-DD.csv
(account, post id, time posted, time seen, text).

Costs (X bills per post read; see config.toml): a hard daily limit max_posts_per_day (60): a
request is only made while at least max_results posts are left in today's limit, so the count
never goes over it. Each handle's account ID is looked up once and kept in accounts.json, so
it is never paid for twice. The health file shows the posts read today and the estimated cost,
and any credit or usage header X sends back.

The Bearer token never comes from the repository: systemd hands it to this one service from
/etc/trading-bot/x_bearer_token (LoadCredential=, deploy/xposts.service), or X_BEARER_TOKEN for
a test by hand. It is never written to a file, a log or the health file.
"""

import csv
import json
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger("xposts")

API = "https://api.x.com/2"
POST_COLUMNS = ["account", "post_id", "posted_utc", "seen_utc", "text"]
ISO = "%Y-%m-%dT%H:%M:%SZ"
MIN_RESULTS = 5                   # X's smallest max_results for a user's posts


class XError(Exception):
    """X's API refused or failed a request. `status` is the HTTP status (None: no answer)."""

    def __init__(self, message, status=None, retry_at=None):
        super().__init__(message)
        self.status, self.retry_at = status, retry_at


def secret(name="x_bearer_token", env="X_BEARER_TOKEN"):
    """The token from systemd's credentials folder, else the environment (a test by hand).
    None when there is none."""
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if folder:
        try:
            with open(os.path.join(folder, name)) as fh:
                value = fh.read().strip()
            if value:
                return value
        except OSError:
            pass
    return (os.environ.get(env) or "").strip() or None


def iso(when):
    return when.astimezone(timezone.utc).strftime(ISO)


class XApi:
    """The two read-only calls the watcher makes. Never logs or returns the token."""

    def __init__(self, token, session=None, timeout=20):
        import requests
        self._headers = {"Authorization": f"Bearer {token}",
                         "User-Agent": "trading-bot-xposts/1.0 (read-only)"}
        self.session = session or requests.Session()
        self.timeout = timeout
        self.last_headers = {}

    def _get(self, path, params):
        import requests
        try:
            resp = self.session.get(f"{API}{path}", params=params, headers=self._headers,
                                    timeout=self.timeout)
        except requests.RequestException as exc:
            raise XError(f"X could not be reached: {type(exc).__name__}") from None
        self.last_headers = {k.lower(): v for k, v in (resp.headers or {}).items()}
        if resp.status_code == 429:
            reset = self.last_headers.get("x-rate-limit-reset")
            retry = datetime.fromtimestamp(int(reset), timezone.utc) if reset and reset.isdigit() \
                else None
            raise XError("X says too many requests (429)", 429, retry)
        if resp.status_code != 200:
            try:
                body = resp.json()
                detail = body.get("title") or body.get("detail") or ""
            except ValueError:
                detail = ""
            raise XError(f"X answered {resp.status_code} {detail}".strip()[:160], resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise XError("X sent an answer that is not JSON", resp.status_code) from None

    def lookup(self, handles):
        """{handle (lower case): account id} and [handles X does not know] (one request)."""
        body = self._get("/users/by", {"usernames": ",".join(handles)})
        found = {u["username"].lower(): u["id"] for u in body.get("data") or []}
        missing = [h for h in handles if h.lower() not in found]
        return found, missing

    def posts(self, user_id, max_results, since_id=None, start_time=None):
        """The account's newest original posts (no replies, no reposts), newer than since_id
        (or posted after start_time). Returns (posts, meta)."""
        params = {"max_results": max_results, "exclude": "replies,retweets",
                  "tweet.fields": "created_at"}
        if since_id:
            params["since_id"] = since_id
        elif start_time is not None:
            params["start_time"] = iso(start_time)
        body = self._get(f"/users/{user_id}/tweets", params)
        return body.get("data") or [], body.get("meta") or {}

    def cost_headers(self):
        """Any header X sent about credits, cost or usage (none is documented; kept if seen)."""
        return {k: v for k, v in self.last_headers.items()
                if any(word in k for word in ("credit", "cost", "usage", "billing"))}


class Watcher:
    def __init__(self, cfg, data_folder, api=None, clock=None):
        self.c = cfg["xposts"]
        self.folder = os.path.join(data_folder, self.c.get("folder", "xposts"))
        os.makedirs(self.folder, exist_ok=True)
        self.api = api
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.handles = [h.strip().lstrip("@") for h in self.c["accounts"]]
        self.state = self._read("state.json", {"accounts": {}, "days": {}})
        self.accounts = self._read("accounts.json", {"ids": {}, "missing": [], "looked_up": None})
        self.health = self._read("health.json", {})
        self.health.pop("cost_headers", None)

    # ---- files ----------------------------------------------------------

    def _path(self, name):
        return os.path.join(self.folder, name)

    def _read(self, name, default):
        try:
            with open(self._path(name)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def _write(self, name, data):
        tmp = self._path(name) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self._path(name))

    def _save_posts(self, rows, now):
        path = self._path(f"posts-{now:%Y-%m-%d}.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(POST_COLUMNS)
            w.writerows(rows)

    def _day(self, now):
        key = now.strftime("%Y-%m-%d")
        days = self.state.setdefault("days", {})
        for old in sorted(days)[:-35]:                 # about a month of daily counts
            del days[old]
        return days.setdefault(key, {"posts_read": 0, "requests": 0, "user_lookups": 0,
                                     "errors": 0})

    # ---- the account IDs (looked up once) --------------------------------

    def unknown_handles(self):
        known = {h.lower() for h in self.accounts.get("ids", {})}
        missing = {h.lower() for h in self.accounts.get("missing", [])}
        return [h for h in self.handles if h.lower() not in known | missing]

    def lookup(self, now=None):
        """Look up the handles without a saved ID (one request for all of them) and save the
        result in accounts.json. Handles X does not know are saved too, so they are not paid
        for again. Returns (found, missing) for those handles."""
        now = now or self.clock()
        todo = self.unknown_handles()
        if not todo:
            return {}, []
        found, missing = self.api.lookup(todo)
        day = self._day(now)
        day["requests"] += 1
        day["user_lookups"] += len(found)
        self.accounts.setdefault("ids", {}).update(found)
        self.accounts["missing"] = sorted(set(self.accounts.get("missing", [])) |
                                          {m.lower() for m in missing})
        self.accounts["looked_up"] = iso(now)
        self._write("accounts.json", self.accounts)
        self._write("state.json", self.state)
        return found, missing

    # ---- one round --------------------------------------------------------

    def run_once(self, now=None, out=print):
        """Every watched account once (within the daily limit). Never raises for X's errors:
        they are counted, logged and shown in the health file."""
        now = now or self.clock()
        if self.api is None:
            self._health(now, "no token: put it in /etc/trading-bot/x_bearer_token "
                              "(deploy/LAUNCH_SERVER_SETUP.md, Part M)")
            out(f"{now:%H:%M} no X token: nothing asked")
            return []
        paused = self.state.get("paused_until")
        if paused and now < datetime.fromisoformat(paused):
            self._health(now, None, note=f"paused until {paused} (X said to wait)")
            return []
        error = None
        try:
            if self.unknown_handles():
                self.lookup(now)
        except XError as exc:
            error = self._failed(now, exc, "account lookup")
        saved = []
        day = self._day(now)
        limit, per_request = self.c["max_posts_per_day"], self.c.get("max_results", MIN_RESULTS)
        for handle in self.handles:
            user_id = self.accounts.get("ids", {}).get(handle.lower())
            if not user_id:
                continue
            if day["posts_read"] + per_request > limit:
                self.state["limit_reached"] = now.strftime("%Y-%m-%d")
                break
            a = self.state.setdefault("accounts", {}).setdefault(
                handle.lower(), {"since_id": None, "watching_since": iso(now)})
            start = datetime.strptime(a["watching_since"], ISO).replace(tzinfo=timezone.utc)
            try:
                posts, meta = self.api.posts(user_id, per_request, a.get("since_id"),
                                             None if a.get("since_id") else start)
            except XError as exc:
                error = self._failed(now, exc, handle)
                if exc.status in (401, 403, 429):
                    break                                   # every account would fail too
                continue
            day["requests"] += 1
            day["posts_read"] += len(posts)
            if meta.get("next_token"):                      # more than one page was new
                a["maybe_missed"] = a.get("maybe_missed", 0) + 1
            newest = meta.get("newest_id") or max((p["id"] for p in posts), key=int, default=None)
            if newest and (not a.get("since_id") or int(newest) > int(a["since_id"])):
                a["since_id"] = newest
            for p in sorted(posts, key=lambda p: int(p["id"])):
                posted = (p.get("created_at") or "").replace(".000Z", "Z")
                saved.append([handle, p["id"], posted, iso(now), p.get("text", "")])
        if saved:
            self._save_posts(saved, now)
        self._write("state.json", self.state)
        self._health(now, error)
        out(f"{now:%H:%M} {len(saved)} new post(s); {day['posts_read']} of {limit} read today"
            + (f"; error: {error}" if error else ""))
        for row in saved:
            out(f"  @{row[0]} {row[2]}: {row[4][:100]!r}")
        return saved

    def _failed(self, now, exc, what):
        day = self._day(now)
        day["errors"] += 1
        if exc.status == 429:
            until = exc.retry_at or now + timedelta(minutes=15)
            self.state["paused_until"] = until.isoformat()
        elif exc.status in (401, 403):
            self.state["paused_until"] = (now + timedelta(hours=1)).isoformat()
        text = f"{what}: {exc}"
        log.warning("X request failed (%s)", text)
        return text

    def _health(self, now, error, note=None):
        day = self._day(now)
        month = now.strftime("%Y-%m")
        in_month = [d for k, d in self.state.get("days", {}).items() if k.startswith(month)]
        price_post = self.c.get("price_per_post_usd", 0.005)
        price_user = self.c.get("price_per_user_usd", 0.010)

        def cost(d):
            return d.get("posts_read", 0) * price_post + d.get("user_lookups", 0) * price_user
        data = {
            "updated": iso(now),
            "token": self.api is not None,
            "accounts_watched": sorted(self.accounts.get("ids", {})),
            "accounts_missing": self.accounts.get("missing", []),
            "posts_read_today": day["posts_read"],
            "requests_today": day["requests"],
            "errors_today": day["errors"],
            "max_posts_per_day": self.c["max_posts_per_day"],
            "limit_reached_today": self.state.get("limit_reached") == now.strftime("%Y-%m-%d"),
            "estimated_cost_today_usd": round(cost(day), 4),
            "estimated_cost_month_usd": round(sum(cost(d) for d in in_month), 4),
            "maybe_missed": {h: a["maybe_missed"] for h, a in self.state.get("accounts", {}).items()
                             if a.get("maybe_missed")},
            "note": note,
        }
        if error is None:
            data["last_ok"] = iso(now)
        else:
            data["last_ok"] = self.health.get("last_ok")
            data["last_error"], data["error_at"] = error[:200], iso(now)
        if self.health.get("last_error") and error is None:
            data["last_error"], data["error_at"] = self.health["last_error"], self.health.get("error_at")
        headers = self.api.cost_headers() if self.api is not None else {}
        if headers:
            data["cost_headers"] = headers
        self.health = data
        self._write("health.json", data)
