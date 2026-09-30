"""Opens a GitHub issue for each token that passes every filter, and closes it
when the paper position closes.

Only used by the scheduled GitHub Actions run (`python run.py --github-issues`),
which provides the repository name and a short-lived token. It only creates,
comments on and closes issues in this repository.

What's still to do is kept in data/positions.json, so if GitHub can't be
reached, nothing is lost: the next run tries again.
  - an open position with "issue_details" but no "issue" number still needs
    its issue opened
  - state["issues_to_close"] holds closed positions whose issue still needs
    the result comment and closing
"""

import re
from datetime import datetime, timedelta

import requests

from screener.filters import money, to_float

API = "https://api.github.com"
MARKER = "<!-- screener-token: {} -->"
MARKER_RE = re.compile(r"<!-- screener-token: (\S+) -->")


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

    def ensure_label(self):
        if self._request("GET", f"/labels/{self.label}", allow_404=True) is None:
            self._request("POST", "/labels", json={
                "name": self.label, "color": "0e8a16",
                "description": "Token passed every screener filter",
            })

    def existing(self):
        """{token address: issue number} for every issue with our label,
        open or closed, so a token never gets a second issue."""
        found = {}
        url = f"/issues?labels={self.label}&state=all&per_page=100"
        while url:
            resp = self._request("GET", url)
            for issue in resp.json():
                match = MARKER_RE.search(issue.get("body") or "")
                if match:
                    found.setdefault(match.group(1), issue["number"])
            url = resp.links.get("next", {}).get("url")
        return found

    def create(self, title, body):
        resp = self._request("POST", "/issues",
                             json={"title": title, "body": body, "labels": [self.label]})
        return resp.json()["number"]

    def comment(self, number, body):
        self._request("POST", f"/issues/{number}/comments", json={"body": body})

    def close(self, number):
        self._request("PATCH", f"/issues/{number}",
                      json={"state": "closed", "state_reason": "completed"})


# ---------------------------------------------------------------------
# What goes in the issue
# ---------------------------------------------------------------------

def issue_details(result, when):
    """Snapshot of the numbers at the moment the token passed."""
    pair = result.pair or {}
    return {
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


def issue_title(pos):
    return f"PASSED: {pos['symbol']}"


def issue_body(pos, pt, note):
    d = pos["issue_details"]
    entry = pos["entry_price"]
    change = d["change_24h_pct"]
    holders = d["top_holders"]
    lines = [
        MARKER.format(pos["address"]),
        f"**Token:** {d['name']} ({pos['symbol']})",
        f"**Contract address:** `{pos['address']}`",
        f"**DexScreener:** {d['url'] or 'no link'}",
        "",
        f"### When it passed ({_utc(d['passed_at'])})",
        "| | |",
        "|---|---|",
        f"| Entry price (paper) | {price(entry)} |",
        f"| Market cap | {money(d['market_cap_usd'])} |",
        f"| Liquidity | {money(d['liquidity_usd'])} |",
        f"| 24h change | {'unknown' if change is None else f'{change:+.0f}%'} |",
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

    tp, sl, trail = pt["take_profit_pct"], pt["stop_loss_pct"], pt["trailing_stop_pct"]
    sell_part = pt["take_profit_sell_fraction"]
    sell_part = "half" if sell_part == 0.5 else f"{sell_part * 100:g}%"
    time_stop = datetime.fromisoformat(pos["entry_time"]) + timedelta(hours=pt["max_hold_hours"])
    lines += [
        "",
        f"### Exit levels (from the {price(entry)} entry)",
        "| Rule | Level |",
        "|---|---|",
        f"| Take profit: sell {sell_part} | {price(entry * (1 + tp / 100))} (+{tp:g}%) |",
        f"| Stop loss: sell the rest | {price(entry * (1 - sl / 100))} (-{sl:g}%) |",
        f"| Trailing stop: sell the rest | {trail:g}% below the highest price since entry. "
        f"Starts at {price(entry * (1 - trail / 100))} and rises with the peak |",
        f"| Time stop: sell the rest | {time_stop.strftime('%Y-%m-%d %H:%M UTC')} "
        f"({pt['max_hold_hours']:g}h), if the price is still within "
        f"±{pt['stale_move_pct']:g}% of entry |",
        "",
        f"> [!WARNING]\n> {note}",
        "",
        "_Paper trade only, no real money. This issue closes by itself when the "
        "paper position closes._",
    ]
    return "\n".join(lines)


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

def sync(gh, trader, pt, note, out=print):
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
        known = gh.existing()
    except GitHubError as exc:
        out(f"  (GitHub unavailable, will retry next run: {exc})")
        return

    def open_issue(pos):
        if pos["address"] in known:
            pos["issue"] = known[pos["address"]]
            out(f"  {pos['symbol']:<10} already has issue #{pos['issue']}")
        else:
            pos["issue"] = gh.create(issue_title(pos), issue_body(pos, pt, note))
            known[pos["address"]] = pos["issue"]
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
