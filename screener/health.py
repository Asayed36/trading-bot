"""Is everything running? The health section at the top of the daily comparison.

Sources:
  - data/health.json, written by every scheduled run (run.py): when each
    strategy last ran without being skipped, and its last error;
  - GitHub's Actions API: failed "Paper trading run" runs in the last 24
    hours, and the last successful one;
  - GitHub's commits API (or data/launch/stats.json): the launch bot's last
    push from your server;
  - data/main-1min/health.json and the commits API: the main (1 min)
    strategy's last good run, its requests per hour, and its last push;
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


def _news_ai(c, meter, now):
    """(status, detail) for the news strategy's AI check: off, not used yet,
    today's count against the daily limit, or the last error."""
    if not c.get("enabled", True):
        return INFO, "turned off (news.ai.enabled = false)"
    if not meter:
        return INFO, ("not used yet: it runs when there's crypto news, and needs the "
                      "CLAUDE_API_KEY secret")
    if meter.get("off"):
        return INFO, f"not used: {meter['off']}; the rule-based checks decide"
    today = meter.get("day") == now.strftime("%Y-%m-%d")
    calls = meter.get("calls", 0) if today else 0
    detail = f"{calls} of {c['daily_limit']} checks today"
    if meter.get("last_ok"):
        detail += f"; last answer {_utc(meter['last_ok']):%Y-%m-%d %H:%M} UTC"
    error = meter.get("last_error")
    if error and (not meter.get("last_ok") or error[:16] > meter["last_ok"][:16].replace("T", " ")):
        return WARN, f"{detail}; failing: {error[:120]} (the rule-based checks decide)"
    if not meter.get("last_ok"):
        return INFO, detail + "; no answer yet (is the CLAUDE_API_KEY secret set?)"
    if today and calls >= c["daily_limit"]:
        return WARN, detail + ": daily limit reached, the rest of today is rule-based only"
    return OK, detail


def _news_source(src, s, now):
    """(status, detail) for a working news source. A source with nothing new
    for longer than its stale_days (by kind, see screener/news.py) warns: its
    address may have changed, or it was replaced by a page that never
    updates."""
    from screener.news import STALE_DAYS
    if "markets" in s:
        detail = f"{s['markets']} coin(s) listed"
    else:
        detail = f"{s.get('items', 0)} item(s)"
    newest = s.get("newest")
    if not newest:
        return OK, detail + ("; no new listing seen yet" if "markets" in s else "")
    when = _utc(newest)
    days = (now - when).total_seconds() / 86400
    limit = src.get("stale_days", STALE_DAYS.get(src.get("kind", "press"), 14))
    detail += f", newest {when:%Y-%m-%d}"
    if days > limit:
        return WARN, detail + f": nothing new for {days:.0f} days (expected within {limit})"
    return OK, detail


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


# Runs that count as "the bot ran": GitHub's schedule, and workflow_dispatch
# (started by the server's paper-run trigger, deploy/trigger_paper_run.py, or
# by hand from the Actions tab).
RUN_EVENTS = ("schedule", "workflow_dispatch")


def run_gaps(runs):
    """Minutes between consecutive runs, scheduled or started by the server
    (GitHub starts scheduled runs late, or drops them, when it's busy)."""
    starts = sorted(_utc(r.get("run_started_at") or r.get("created_at"))
                    for r in runs if r.get("event", "schedule") in RUN_EVENTS
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

def add_momentum(add, folder, cfg, now, github):
    """One row: the momentum bot's live feed (the last time it was up, from
    its pushed health.json), its disconnects, signals and buys over 24 h
    (stats.json), and its last push. A warning when the feed's last good
    moment or the last push is older than [health] launch_stale_hours."""
    name = "momentum: server"
    sub = cfg["momentum"]["folder"]
    late_after = timedelta(hours=cfg.get("health", {}).get("launch_stale_hours", 3))
    data = _load(os.path.join(folder, sub, "health.json")) or {}
    stats = _load(os.path.join(folder, sub, "stats.json")) or {}
    ok = _utc(data.get("last_ok"))
    pushed = None
    if github is not None:
        try:
            pushed = github.last_commit_time(f"data/{sub}")
        except Exception:
            pushed = None
    if not ok:
        add(name, WARN, "no results pushed yet: is it set up (deploy/LAUNCH_SERVER_SETUP.md, "
            "Part I)?", "momentum has never pushed results")
        return
    day = {}
    for hour, counts in stats.items():
        when = _utc(hour.replace(" ", "T"))
        if when and now - when <= timedelta(hours=24):
            for key, n in counts.items():
                day[key] = day.get(key, 0) + n
    signals = sum(n for k, n in day.items() if k.endswith(": signals"))
    buys = sum(n for k, n in day.items() if k.endswith(": buys"))
    detail = (f"feed last up {_at(ok, now)}; last 24 h: {day.get('feed disconnects', 0)} "
              f"disconnect(s), {day.get('launches seen', 0)} launches, {signals} signal(s), "
              f"{buys} buy(s)")
    if pushed:
        detail += f"; last push {_at(pushed, now)}"
    if data.get("feed_up") is False:
        detail += "; the feed was down at the last save"
    late = now - ok > late_after or (pushed is not None and now - pushed > late_after)
    if late:
        detail += f" (older than {late_after.total_seconds() / 3600:.0f} h)"
    add(name, WARN if late else OK, detail)


def add_main_1min(add, folder, cfg, now, github):
    """One row: the main (1 min) strategy's last good run (from its pushed
    health.json), runs and requests per hour over the last 24 h, and its
    last push. A warning when the last good run or the last push is older
    than [health] launch_stale_hours (it pushes about once an hour), or it
    was skipped since."""
    name = "main (1 min): server"
    late_after = timedelta(hours=cfg.get("health", {}).get("launch_stale_hours", 3))
    data = _load(os.path.join(folder, cfg["main_1min"]["folder"], "health.json")) or {}
    ok, err_at = _utc(data.get("last_ok")), _utc(data.get("error_at"))
    pushed = None
    if github is not None:
        try:
            pushed = github.last_commit_time(f"data/{cfg['main_1min']['folder']}")
        except Exception:
            pushed = None
    if not ok:
        add(name, WARN, "no results pushed yet: is it set up (deploy/LAUNCH_SERVER_SETUP.md, "
            "Part G)?", "main (1 min) has never pushed results")
        return
    detail = f"last good run {_at(ok, now)}"
    hours = {k: v for k, v in (data.get("calls_per_hour") or {}).items()
             if _utc(k) and now - _utc(k) <= timedelta(hours=24)}
    if hours:
        runs = sum(h.get("runs", 0) for h in hours.values())
        per = {s: max(h.get(s, 0) for h in hours.values()) for s in ("dexscreener", "rugcheck")}
        detail += (f"; {runs} runs in {len(hours)} h; busiest hour: {per['dexscreener']} "
                   f"DexScreener, {per['rugcheck']} RugCheck requests")
    if pushed:
        detail += f"; last push {_at(pushed, now)}"
    broken = err_at and err_at > ok
    if broken:
        detail += f"; skipped since {err_at:%H:%M} UTC: {data.get('last_error', '')[:100]}"
    if data.get("rugcheck_paused_until"):
        detail += f"; RugCheck paused until {data['rugcheck_paused_until'][11:16]} UTC"
    late = now - ok > late_after or (pushed is not None and now - pushed > late_after)
    if late:
        detail += f" (older than {late_after.total_seconds() / 3600:.0f} h)"
    add(name, WARN if (broken or late) else OK, detail)


def _news_source_rows(add, label, cfg, runs_on, sources, now):
    """One row per news source read on GitHub, or on the server."""
    for src in cfg["news"].get("sources") or []:
        if src.get("runs_on", "github") != runs_on:
            continue
        name = src["name"]
        s = sources.get(name)
        if src.get("enabled") is False:
            add(f"{label}: {name}", INFO, f"turned off: {src.get('note', 'enabled = false')}")
        elif not sources:
            continue
        elif s is None:
            add(f"{label}: {name}", INFO, "not checked yet")
        elif not s.get("ok"):
            add(f"{label}: {name}", WARN, f"failing: {s.get('error', 'unknown error')[:120]}")
        else:
            add(f"{label}: {name}", *_news_source(src, s, now))


def add_news_listings(add, folder, cfg, now, github):
    """The news listings bot: its last good run (pushed health.json), runs
    and requests per hour over the last 24 h, and its last push; then a row
    per source it reads, and its AI check. A warning when the last good run
    or the last push is older than [health] launch_stale_hours."""
    label = "news (listings)"
    sub = cfg["news_listings"]["folder"]
    late_after = timedelta(hours=cfg.get("health", {}).get("launch_stale_hours", 3))
    data = _load(os.path.join(folder, sub, "health.json")) or {}
    state = _load(os.path.join(folder, sub, "positions.json")) or {}
    ok, err_at = _utc(data.get("last_ok")), _utc(data.get("error_at"))
    pushed = None
    if github is not None:
        try:
            pushed = github.last_commit_time(f"data/{sub}")
        except Exception:
            pushed = None
    if not ok:
        add(f"{label}: server", WARN, "no results pushed yet: is it set up "
            "(deploy/LAUNCH_SERVER_SETUP.md, Part J)?", "news (listings) has never pushed results")
        return
    detail = f"last good run {_at(ok, now)}"
    hours = {k: v for k, v in (data.get("calls_per_hour") or {}).items()
             if _utc(k) and now - _utc(k) <= timedelta(hours=24)}
    if hours:
        runs = sum(h.get("runs", 0) for h in hours.values())
        gecko = sum(h.get("coingecko.com", 0) for h in hours.values())
        detail += f"; {runs} runs in {len(hours)} h, {gecko} CoinGecko call(s)"
    if pushed:
        detail += f"; last push {_at(pushed, now)}"
    broken = err_at and err_at > ok
    if broken:
        detail += f"; skipped since {err_at:%H:%M} UTC: {data.get('last_error', '')[:100]}"
    late = now - ok > late_after or (pushed is not None and now - pushed > late_after)
    if late:
        detail += f" (older than {late_after.total_seconds() / 3600:.0f} h)"
    add(f"{label}: server", WARN if (broken or late) else OK, detail)
    _news_source_rows(add, label, cfg, "server", state.get("sources") or {}, now)
    ai_cfg = cfg["news"].get("ai") or {}
    if ai_cfg:
        own = dict(ai_cfg, daily_limit=cfg["news_listings"].get("ai_daily_limit",
                                                                 ai_cfg["daily_limit"]))
        status, detail = _news_ai(own, state.get("ai"), now)
        if status == INFO and data.get("ai_key") is False:
            detail = ("not used: no Claude API key on the server (Part J); the rule-based "
                      "checks decide")
        add(f"{label}: AI check", status, detail)


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
            kinds = [r.get("event", "schedule") for r in runs]
            scheduled, started = kinds.count("schedule"), kinds.count("workflow_dispatch")
            if gaps:
                add("Time between runs (last 24h)", INFO,
                    f"average {sum(gaps) / len(gaps):.1f} min, median "
                    f"{sorted(gaps)[len(gaps) // 2]:.0f} min, longest {max(gaps):.0f} min "
                    f"({len(gaps) + 1} runs: {scheduled} scheduled by GitHub, {started} "
                    "started by the server or by hand"
                    + (f"; the schedule asks for every {every:g} min" if every else "") + ")")
            else:
                add("Time between runs (last 24h)", INFO, "fewer than 2 runs")

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

    # 4. News sources: one row for each source in config.toml.
    if cfg.get("news", {}).get("enabled"):
        news = _load(os.path.join(folder, "news", "positions.json")) or {}
        sources = news.get("sources") or {}
        if not sources:
            add("news: sources", WARN, "not checked yet")
        # (The sources marked runs_on = "server" are the news listings
        # bot's: their rows are with it, in section 9.)
        _news_source_rows(add, "news", cfg, "github", sources, now)
        ai_cfg = cfg["news"].get("ai") or {}
        if ai_cfg:
            add("news: AI check", *_news_ai(ai_cfg, news.get("ai"), now))

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

    # 7. The main (1 min) strategy on your server.
    if cfg.get("main_1min", {}).get("enabled"):
        add_main_1min(add, folder, cfg, now, github)

    # 8. The momentum strategy on your server.
    if cfg.get("momentum", {}).get("enabled"):
        add_momentum(add, folder, cfg, now, github)

    # 9. The news listings bot on your server.
    if cfg.get("news_listings", {}).get("enabled") and cfg.get("news"):
        add_news_listings(add, folder, cfg, now, github)

    head = [f"### Health ({now:%Y-%m-%d %H:%M} UTC)", ""]
    if problems:
        head += [f"> [!WARNING]\n> **{len(problems)} problem(s) need a look:**"]
        head += [f"> - {p}" for p in problems]
    else:
        head += ["**All checks OK.**"]
    return head + ["", "| Check | Status |", "|---|---|"] + rows + [""]
