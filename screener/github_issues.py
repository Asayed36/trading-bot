"""Opens a GitHub issue for each token that passes every filter, and closes it
when the paper position closes. Each paper strategy ("main", "early", "news",
"robinhood") gets its own issues, told apart by title, a "strategy: ..." label
and a hidden marker, so the same token can have one issue per strategy but
never two.

Only used by the scheduled GitHub Actions run (`python run.py --github-issues`),
which provides the repository name and a short-lived token. It only creates,
comments on and closes issues in this repository.

What's still to do is kept in each strategy's positions.json, so if GitHub can't be
reached, nothing is lost: the next run tries again.
  - an open position with "issue_details" but no "issue" number still needs
    its issue opened
  - state["issues_to_close"] holds closed positions whose issue still needs
    the result comment and closing
"""

import re
from datetime import datetime, timedelta
from urllib.parse import quote

import requests

from screener.filters import money, to_float

API = "https://api.github.com"
MARKER_RE = re.compile(r"<!-- screener-token: (\S+?)(?: strategy: (\S+))? -->")


def marker(address, strategy="main"):
    # The main strategy keeps the original marker, so its older issues still match.
    if strategy == "main":
        return f"<!-- screener-token: {address} -->"
    return f"<!-- screener-token: {address} strategy: {strategy} -->"


MARKER = "<!-- screener-token: {} -->"  # main strategy marker, kept for reference


class GitHubError(Exception):
    """Raised when GitHub can't be reached or refuses a request."""


class GitHubIssues:
    def __init__(self, token, repo, label="passed", timeout=20):
        self.repo = repo
        self.label = label
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method, path, allow_404=False, **kwargs):
        url = path if path.startswith("http") else f"{API}/repos/{self.repo}{path}"
        try:
            resp = requests.request(method, url, headers=self.headers,
                                    timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise GitHubError(f"could not reach GitHub: {exc}") from exc
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code >= 400:
            raise GitHubError(f"{method} {path} answered with error {resp.status_code}: "
                              f"{resp.text[:200]}")
        return resp

    def ensure_label(self, name=None, color="0e8a16",
                     description="Token passed every screener filter"):
        name = name or self.label
        if self._request("GET", f"/labels/{quote(name)}", allow_404=True) is None:
            self._request("POST", "/labels", json={
                "name": name, "color": color, "description": description,
            })

    def issues_with_label(self):
        """Every issue with our label, open or closed."""
        url = f"/issues?labels={quote(self.label)}&state=all&per_page=100"
        while url:
            resp = self._request("GET", url)
            yield from resp.json()
            url = resp.links.get("next", {}).get("url")

    def existing(self):
        """{(strategy, token address): issue number} for every issue with our
        label, open or closed, so a token never gets a second issue."""
        found = {}
        for issue in self.issues_with_label():
            match = MARKER_RE.search(issue.get("body") or "")
            if match:
                found.setdefault((match.group(2) or "main", match.group(1)), issue["number"])
        return found

    def workflow_runs(self, workflow, since):
        """Runs of one workflow (file name) created since `since`, newest first.
        Needs "actions: read" permission."""
        stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"/actions/workflows/{quote(workflow)}/runs?created=%3E%3D{stamp}&per_page=100"
        runs = []
        while url and len(runs) < 1000:
            resp = self._request("GET", url)
            runs += resp.json().get("workflow_runs") or []
            url = resp.links.get("next", {}).get("url")
        return runs

    def run_failure(self, run_id):
        """Why a failed run failed: "no machine" when GitHub never gave it a
        machine to run on (no runner, no step ran: GitHub's problem), else
        the name of the step that failed (or "unknown")."""
        jobs = self._request("GET", f"/actions/runs/{run_id}/jobs").json().get("jobs") or []
        for job in jobs:
            if job.get("conclusion") not in ("failure", "cancelled", "timed_out"):
                continue
            steps = job.get("steps") or []
            if not job.get("runner_name") and not steps:
                return "no machine"
            failed = [s["name"] for s in steps if s.get("conclusion") == "failure"]
            return failed[0] if failed else "unknown"
        return "no machine" if not jobs else "unknown"

    def count_runs(self, workflow, start, end, event="schedule"):
        """How many runs of one workflow started between `start` and `end`
        (scheduled ones only by default). One request: GitHub reports the
        total."""
        span = f"{start:%Y-%m-%dT%H:%M:%SZ}..{end:%Y-%m-%dT%H:%M:%SZ}"
        resp = self._request("GET", f"/actions/workflows/{quote(workflow)}/runs?created="
                             f"{quote(span)}&event={event}&per_page=1")
        return resp.json().get("total_count", 0)

    def last_commit_time(self, path):
        """When the newest commit touching `path` was made, or None."""
        resp = self._request("GET", f"/commits?path={quote(path)}&per_page=1")
        commits = resp.json()
        if not commits:
            return None
        when = commits[0]["commit"]["committer"]["date"]
        return datetime.fromisoformat(when.replace("Z", "+00:00"))

    def create(self, title, body, labels=None):
        resp = self._request("POST", "/issues", json={
            "title": title, "body": body, "labels": labels or [self.label]})
        return resp.json()["number"]

    def comment(self, number, body):
        self._request("POST", f"/issues/{number}/comments", json={"body": body})

    def close(self, number):
        self._request("PATCH", f"/issues/{number}",
                      json={"state": "closed", "state_reason": "completed"})

    def issue(self, number):
        return self._request("GET", f"/issues/{number}").json()

    def set_body(self, number, body):
        self._request("PATCH", f"/issues/{number}", json={"body": body})

    def add_labels(self, number, labels):
        self._request("POST", f"/issues/{number}/labels", json={"labels": list(labels)})

    def create_pull(self, title, head, base, body, draft=True):
        """Open a pull request (a draft by default). Needs "pull-requests:
        write", and the repository setting that lets GitHub Actions create
        pull requests. Returns its web address."""
        resp = self._request("POST", "/pulls", json={
            "title": title, "head": head, "base": base, "body": body, "draft": draft})
        return resp.json()["html_url"]


# ---------------------------------------------------------------------
# What goes in the issue
# ---------------------------------------------------------------------

def issue_details(result, when, extra=None):
    """Snapshot of the numbers at the moment the token passed. `extra` is a
    list of (label, value) rows a strategy wants to add."""
    pair = result.pair or {}
    return {
        "extra": [list(row) for row in extra or []],
        "name": result.name,
        "url": pair.get("url"),
        "passed_at": when.isoformat(),
        "market_cap_usd": to_float(pair.get("marketCap")) or to_float(pair.get("fdv")),
        "liquidity_usd": to_float((pair.get("liquidity") or {}).get("usd")),
        "change_24h_pct": to_float((pair.get("priceChange") or {}).get("h24")),
        "top_holders": [
            {"wallet": h.get("owner") or h.get("address"), "pct": to_float(h.get("pct")) or 0.0}
            for h in result.top_holders
        ],
    }


def _utc(iso):
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")


def price(x):
    return f"${x:.10g}"


def issue_title(pos, strategy="main"):
    return STRATEGIES[strategy]["title"].format(symbol=pos["symbol"])


def issue_body(pos, pt, note, strategy="main"):
    d = pos["issue_details"]
    entry = pos["entry_price"]
    change = d["change_24h_pct"]
    lines = [
        marker(pos["address"], strategy),
        f"**Strategy:** {strategy} ({STRATEGIES[strategy]['about']})",
        f"**Token:** {d['name']} ({pos['symbol']})",
        f"**{d.get('address_label', 'Contract address')}:** `{pos['address']}`",
        f"**{d.get('link_label', 'DexScreener')}:** {d['url'] or 'no link'}",
        "",
        f"### When it passed ({_utc(d['passed_at'])})",
        "| | |",
        "|---|---|",
        f"| Entry price (paper) | {price(entry)} |",
        f"| Market cap | {money(d['market_cap_usd'])} |",
    ]
    if "liquidity_usd" in d:
        lines.append(f"| Liquidity | {money(d['liquidity_usd'])} |")
    lines.append(f"| 24h change | {'unknown' if change is None else f'{change:+.0f}%'} |")
    lines += [f"| {label} | {value} |" for label, value in d.get("extra") or []]
    if "top_holders" in d:  # the news strategy has no holder data
        holders = d["top_holders"]
        lines += [
            "",
            f"### Top 10 holders ({sum(h['pct'] for h in holders):.1f}% together, "
            "pool wallets excluded)",
        ]
        if holders:
            lines += ["| # | Wallet | Share |", "|---|---|---|"]
            lines += [f"| {i} | `{h['wallet']}` | {h['pct']:.2f}% |"
                      for i, h in enumerate(holders, 1)]
        else:
            lines.append("No holder data.")

    lines += [
        "",
        f"### Exit levels (from the {price(entry)} entry)",
        "| Rule | Level |",
        "|---|---|",
    ]
    lines += STRATEGIES[strategy]["exit_rows"](pos, pt)
    lines += [
        "",
        f"> [!WARNING]\n> {note}",
        "",
        "_Paper trade only, no real money. This issue closes by itself when the "
        "paper position closes._",
    ]
    return "\n".join(lines)


def _sell_part(pt):
    part = pt["take_profit_sell_fraction"]
    return "half" if part == 0.5 else f"{part * 100:g}%"


def _main_exit_rows(pos, pt):
    entry = pos["entry_price"]
    tp, sl, trail = pt["take_profit_pct"], pt["stop_loss_pct"], pt["trailing_stop_pct"]
    time_stop = datetime.fromisoformat(pos["entry_time"]) + timedelta(hours=pt["max_hold_hours"])
    return [
        f"| Take profit: sell {_sell_part(pt)} | {price(entry * (1 + tp / 100))} (+{tp:g}%) |",
        f"| Stop loss: sell the rest | {price(entry * (1 - sl / 100))} (-{sl:g}%) |",
        f"| Trailing stop: sell the rest | {trail:g}% below the highest price since entry. "
        f"Starts at {price(entry * (1 - trail / 100))} and rises with the peak |",
        f"| Time stop: sell the rest | {time_stop.strftime('%Y-%m-%d %H:%M UTC')} "
        f"({pt['max_hold_hours']:g}h)"
        + (" |" if pt.get("time_exit_any_move") else
           f", if the price is still within ±{pt['stale_move_pct']:g}% of entry |"),
    ]


def _early_exit_rows(pos, pt):
    entry = pos["entry_price"]
    tp, sl, trail = pt["take_profit_pct"], pt["stop_loss_pct"], pt["trailing_stop_pct"]
    start = datetime.fromisoformat(pos["entry_time"])
    time_stop = start + timedelta(minutes=pt["time_stop_minutes"])
    give_up = start + timedelta(hours=pt["max_hold_hours"])
    return [
        f"| Take profit: sell {_sell_part(pt)} | {price(entry * (1 + tp / 100))} (+{tp:g}%) |",
        f"| Hard stop: sell everything left | {price(entry * (1 - sl / 100))} (-{sl:g}%) |",
        f"| Time stop: sell everything | {time_stop.strftime('%Y-%m-%d %H:%M UTC')} "
        f"({pt['time_stop_minutes']:g} min), if take profit hasn't hit by then |",
        f"| After take profit: sell the rest | {trail:g}% below the highest price since "
        f"entry, or at {give_up.strftime('%Y-%m-%d %H:%M UTC')} ({pt['max_hold_hours']:g}h) |",
    ]


def _news_exit_rows(pos, pt):
    entry = pos["entry_price"]
    tp, sl, trail = pt["take_profit_pct"], pt["stop_loss_pct"], pt["trailing_stop_pct"]
    limit = datetime.fromisoformat(pos["entry_time"]) + timedelta(days=pt["max_hold_days"])
    return [
        f"| Take profit: sell {_sell_part(pt)} | {price(entry * (1 + tp / 100))} (+{tp:g}%) |",
        f"| Stop loss: sell everything left | {price(entry * (1 - sl / 100))} (-{sl:g}%) |",
        f"| Trailing stop: sell everything left | {trail:g}% below the highest price since "
        f"entry. Starts at {price(entry * (1 - trail / 100))} and rises with the peak |",
        f"| Time limit: sell everything left | {limit.strftime('%Y-%m-%d %H:%M UTC')} "
        f"({pt['max_hold_days']:g} days) |",
    ]


STRATEGIES = {
    "main": {"title": "PASSED: {symbol}", "about": "established tokens, all filters",
             "exit_rows": _main_exit_rows, "color": "1d76db"},
    "early": {"title": "PASSED (early): {symbol}",
              "about": "tokens under 6h old, bought on a pullback",
              "exit_rows": _early_exit_rows, "color": "d93f0b"},
    "news": {"title": "PASSED (news): {symbol}",
             "about": "official news about an established coin, rule-based checks",
             "exit_rows": _news_exit_rows, "color": "0052cc"},
    "robinhood": {"title": "PASSED (robinhood): {symbol}",
                  "about": "graduated Pons and Pools.trade memecoins on Robinhood Chain",
                  "exit_rows": _main_exit_rows, "color": "00c805"},
}


def strategy_label(strategy):
    return f"strategy: {strategy}"


def close_comment(pos):
    sells = pos.get("sells") or []
    total = sum(s["pnl_usd"] for s in sells)
    cost = pos["cost_usd"]
    lines = ["### Paper position closed", "",
             "| Time | Sold | Reason | Price | P&L |", "|---|---|---|---|---|"]
    lines += [f"| {_utc(s['time'])} | {s['fraction'] * 100:.0f}% | {s['reason']} | "
              f"{price(s['price'])} | ${s['pnl_usd']:+.2f} |" for s in sells]
    lines.append("")
    if sells:
        held = (datetime.fromisoformat(sells[-1]["time"])
                - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 3600
        lines.append(f"**Exit:** {sells[-1]['reason']} at {price(sells[-1]['price'])} "
                     f"(entry {price(pos['entry_price'])}, held {held:.1f}h)")
    lines.append(f"**Result:** ${total:+.2f} ({total / cost * 100:+.1f}% on "
                 f"${cost:g}, after fees)")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Bringing GitHub up to date
# ---------------------------------------------------------------------

def sync(gh, trader, pt, note, out=print, strategy="main"):
    """Open issues for newly passed tokens and close the ones whose position
    closed. Never raises: anything that fails is retried next run."""
    state = trader.state
    to_open = [p for p in trader.open_positions if p.get("issue_details") and not p.get("issue")]
    to_close = state.get("issues_to_close") or []
    if not (to_open or to_close):
        out("  Nothing to do.")
        return
    try:
        gh.ensure_label()
        gh.ensure_label(strategy_label(strategy), STRATEGIES[strategy]["color"],
                        f"Paper strategy: {STRATEGIES[strategy]['about']}")
        known = gh.existing()
    except GitHubError as exc:
        out(f"  (GitHub unavailable, will retry next run: {exc})")
        return

    def open_issue(pos):
        key = (strategy, pos["address"])
        if key in known:
            pos["issue"] = known[key]
            out(f"  {pos['symbol']:<10} already has issue #{pos['issue']}")
        else:
            pos["issue"] = gh.create(issue_title(pos, strategy),
                                     issue_body(pos, pt, note, strategy),
                                     [gh.label, strategy_label(strategy)])
            known[key] = pos["issue"]
            out(f"  {pos['symbol']:<10} opened issue #{pos['issue']}")

    for pos in to_open:
        try:
            open_issue(pos)
        except GitHubError as exc:
            out(f"  ({pos['symbol']}: could not open issue, will retry: {exc})")

    for pos in list(to_close):
        try:
            if not pos.get("issue"):
                open_issue(pos)  # it closed before its issue could be opened
            if not pos.get("commented"):
                gh.comment(pos["issue"], close_comment(pos))
                pos["commented"] = True
            gh.close(pos["issue"])
            to_close.remove(pos)
            out(f"  {pos['symbol']:<10} closed issue #{pos['issue']}")
        except GitHubError as exc:
            out(f"  ({pos['symbol']}: could not close issue, will retry: {exc})")
