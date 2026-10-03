"""Is everything running? The health section at the top of the daily comparison.

Sources:
  - data/health.json, written by every scheduled run (run.py): when each
    strategy last ran without being skipped, and its last error;
  - GitHub's Actions API: failed "Paper trading run" runs in the last 24
    hours, and the last successful one;
  - GitHub's commits API (or data/launch/stats.json): the launch bot's last
    push from your server;
  - the strategies' own files: convergence's tracked wallets and Helius
    pause, the news strategy's source status, the robinhood strategy's data
    sources (GeckoTerminal, DexScreener, GoPlus, the Robinhood Chain RPC).

Read-only: nothing here trades or changes any setting.
"""

import json
import os
from datetime import datetime, timedelta, timezone

OK, WARN, INFO = "✅", "⚠️", "ℹ️"
FAILED = ("failure", "timed_out", "startup_failure")
GITHUB_STRATEGIES = ("main", "early", "convergence", "news", "robinhood")


def _utc(text):
    if not text:
        return None
    when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def _ago(when, now):
    minutes = (now - when).total_seconds() / 60
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    if minutes < 48 * 60:
        return f"{minutes / 60:.1f} h ago"
    return f"{minutes / 1440:.1f} days ago"


def _at(when, now):
    return f"{when:%Y-%m-%d %H:%M} UTC ({_ago(when, now)})"


def run_gaps(runs):
    """Minutes between consecutive scheduled runs (GitHub starts them late
    when it's busy, so the real gap is often longer than the cron line)."""
    starts = sorted(_utc(r.get("run_started_at") or r.get("created_at"))
                    for r in runs if r.get("event", "schedule") == "schedule"
                    and (r.get("run_started_at") or r.get("created_at")))
    return [(b - a).total_seconds() / 60 for a, b in zip(starts, starts[1:])]


# ---------------------------------------------------------------------
# Written by every run
# ---------------------------------------------------------------------

def record_health(data_folder, now, outcomes):
    """Save each strategy's outcome this run. `outcomes` maps a strategy name
    to None (ran fine) or the reason it was skipped."""
    path = os.path.join(data_folder, "health.json")
    data = _load(path) or {}
    data["updated"] = now.isoformat()
    strategies = data.setdefault("strategies", {})
    for name, error in outcomes.items():
        s = strategies.setdefault(name, {})
        if error is None:
            s["last_ok"] = now.isoformat()
        else:
            s["last_error"] = str(error)[:200]
            s["error_at"] = now.isoformat()
    os.makedirs(data_folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------

def health_lines(folder, cfg, now, github=None):
    """Markdown lines for the health section. `github` is a GitHubIssues
    (or anything with workflow_runs() and last_commit_time()), or None when
    there's no token: those checks then say so instead of guessing."""
    h = cfg.get("health", {})
    stale = timedelta(minutes=h.get("stale_minutes", 60))
    rows, problems = [], []

    def add(check, status, detail, problem=None):
        rows.append(f"| {check} | {status} {detail.replace('|', '/')} |")
        if status == WARN:
            problems.append(problem or f"{check}: {detail}")

    # 1. The scheduled GitHub runs.
    if github is None:
        add("Scheduled runs (last 24h)", WARN, "not checked: no GitHub token",
            "scheduled runs not checked (no GitHub token)")
    else:
        try:
            runs = github.workflow_runs(h.get("workflow", "screener.yml"),
                                        now - timedelta(hours=24))
        except Exception as exc:  # GitHub down: say so, don't break the report
            runs = None
            add("Scheduled runs (last 24h)", WARN, f"couldn't ask GitHub: {str(exc)[:100]}")
        if runs is not None:
            failed = [r for r in runs if r.get("conclusion") in FAILED]
            good = [_utc(r.get("updated_at")) for r in runs if r.get("conclusion") == "success"]
            limit = h.get("max_failed_runs_24h", 0)
            detail = f"{len(failed)} failed of {len(runs)}"
            if good:
                detail += f"; last successful run {_at(max(good), now)}"
            else:
                detail += "; no successful run in 24h"
            bad = len(failed) > limit or not good or now - max(good) > stale
            add("Scheduled runs (last 24h)", WARN if bad else OK, detail)
            gaps = run_gaps(runs)
            every = cfg.get("schedule", {}).get("run_every_minutes")
            if gaps:
                add("Time between runs (last 24h)", INFO,
                    f"average {sum(gaps) / len(gaps):.1f} min, median "
                    f"{sorted(gaps)[len(gaps) // 2]:.0f} min, longest {max(gaps):.0f} min "
                    f"({len(gaps) + 1} scheduled runs"
                    + (f"; the schedule asks for every {every:g} min" if every else "") + ")")
            else:
                add("Time between runs (last 24h)", INFO, "fewer than 2 scheduled runs")

    # 2. Each GitHub strategy's last good run (data/health.json).
    record = (_load(os.path.join(folder, "health.json")) or {}).get("strategies", {})
    for name in GITHUB_STRATEGIES:
        if name != "main" and not cfg.get(name, {}).get("enabled"):
            continue
        s = record.get(name) or {}
        ok, err_at = _utc(s.get("last_ok")), _utc(s.get("error_at"))
        if not ok:
            add(f"{name}: last successful run", WARN, "never recorded yet",
                f"{name} has no recorded successful run yet")
            continue
        detail = _at(ok, now)
        broken = err_at and err_at > ok
        if broken:
            detail += f"; skipped since {err_at:%H:%M} UTC: {s.get('last_error', '')[:100]}"
        too_old = now - ok > stale
        if too_old:
            detail += f" (older than {stale.total_seconds() / 60:.0f} min)"
        add(f"{name}: last successful run", WARN if (broken or too_old) else OK, detail)

    # 3. Convergence: wallets to follow, and the Helius budget.
    if cfg.get("convergence", {}).get("enabled"):
        conv = _load(os.path.join(folder, "convergence", "positions.json")) or {}
        c = cfg["convergence"]
        tracked = len(conv.get("tracked") or [])
        detail = f"{tracked} tracked"
        if conv.get("list_updated"):
            detail += f" (list from {conv['list_updated'][:10]})"
        job = conv.get("refresh")
        if job:
            detail += f"; rebuilding: {len(job['scored'])} scored, {len(job['queue'])} to go"
        if not conv.get("helius"):
            add("convergence: wallets", WARN, "not active: is the HELIUS_API_KEY secret set?")
        elif tracked < c["min_wallets"]:
            add("convergence: wallets", WARN,
                detail + f" - fewer than {c['min_wallets']}, so it can't give a signal")
        else:
            add("convergence: wallets", OK, detail)
        if conv.get("paused_until"):
            add("convergence: Helius", WARN,
                f"paused until {conv['paused_until'][:10]} (credit limit reached)")

    # 4. News sources.
    if cfg.get("news", {}).get("enabled"):
        news = _load(os.path.join(folder, "news", "positions.json")) or {}
        sources = news.get("sources") or {}
        if not sources:
            add("news: sources", WARN, "not checked yet")
        for name, s in sources.items():
            if s.get("ok"):
                add(f"news: {name}", OK, f"{s.get('items', 0)} item(s)")
            else:
                add(f"news: {name}", WARN, f"failing: {s.get('error', 'unknown error')[:120]}")

    # 5. The robinhood strategy's data sources (the last run that used each).
    if cfg.get("robinhood", {}).get("enabled"):
        rh = _load(os.path.join(folder, "robinhood", "positions.json")) or {}
        sources = rh.get("sources") or {}
        for name in ("geckoterminal", "dexscreener", "goplus", "rpc"):
            s = sources.get(name) or {}
            if not s.get("at"):
                add(f"robinhood: {name}", INFO, "not used yet")
                continue
            detail = (f"{s.get('calls', 0)} call(s), {s.get('errors', 0)} failed"
                      + (f", {s['rate_limited']} rate-limited" if s.get("rate_limited") else "")
                      + f" (last used {_at(_utc(s['at']), now)})")
            if s.get("ok"):
                add(f"robinhood: {name}", OK, detail)
            else:
                add(f"robinhood: {name}", WARN, f"failing: {detail}: "
                    f"{s.get('error', 'unknown error')[:120]}")

    # 6. The launch bot on your server.
    if cfg.get("launch", {}).get("enabled"):
        launch_stale = timedelta(hours=h.get("launch_stale_hours", 3))
        pushed, source = None, ""
        if github is not None:
            try:
                pushed, source = github.last_commit_time("data/launch"), "last push"
            except Exception:
                pushed = None
        if pushed is None:
            stats = _load(os.path.join(folder, "launch", "stats.json")) or {}
            hours = sorted(k for k in stats if k[:2] == "20")
            if hours:
                pushed = _utc(hours[-1] if "T" in hours[-1] else hours[-1].replace(" ", "T"))
                source = "latest hour in stats.json"
        if pushed is None:
            add("launch: server push", WARN, "no results pushed yet: is the server set up "
                "(deploy/LAUNCH_SERVER_SETUP.md)?", "launch bot has never pushed results")
        else:
            late = now - pushed > launch_stale
            detail = f"{source} {_at(pushed, now)}"
            if late:
                detail += f" (older than {launch_stale.total_seconds() / 3600:.0f} h)"
            add("launch: server push", WARN if late else OK, detail)

    head = [f"### Health ({now:%Y-%m-%d %H:%M} UTC)", ""]
    if problems:
        head += [f"> [!WARNING]\n> **{len(problems)} problem(s) need a look:**"]
        head += [f"> - {p}" for p in problems]
    else:
        head += ["**All checks OK.**"]
    return head + ["", "| Check | Status |", "|---|---|"] + rows + [""]
