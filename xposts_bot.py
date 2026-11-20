"""The X post watcher (screener/xposts.py), on your own server. RECORDING ONLY: no trading.

    python xposts_bot.py --lookup          <- look up the watched handles' account IDs once
                                              (one paid request), save them, list unknown ones
    python xposts_bot.py --test elonmusk   <- ONE paid request: that account's newest original
                                              posts (at most 5); prints them and the estimated
                                              cost; saves no post
    python xposts_bot.py --empty-test elonmusk
                                           <- 3 requests that can only come back EMPTY (posts
                                              newer than now), to see on X's Usage page whether
                                              an empty check costs anything; saves nothing
    python xposts_bot.py                   <- check every account every [xposts] every_seconds
                                              (the xposts service does this)

The Bearer token comes from systemd's credential (deploy/xposts.service, a file only root can
read: deploy/LAUNCH_SERVER_SETUP.md, Part M), or from the X_BEARER_TOKEN environment variable
for a test by hand. It is never printed, logged or saved. deploy/push_results.sh pushes
data/xposts/ (the posts, the account IDs, the health file and the report) once an hour; the
bot restarts itself when that push brings new code it uses.

It also records the ticker mentions in the saved posts (screener/xmentions.py: cashtags and token
addresses, each looked up once on DexScreener and followed for 24 hours). Recording only: no X
request is made for it, nothing is bought or sold.
"""

import argparse
import logging
import os
import signal
import sys

from screener.autorestart import CodeWatcher
from screener.autorestart import forever as run_forever
from screener.settings import HERE, load_config
import threading
import time
from datetime import datetime, timezone

from screener.api import PublicApi
from screener.xmentions import Mentions

from screener.xposts import MIN_RESULTS, Watcher, XApi, XError, secret, snowflake
from screener.xposts_report import write_report

log = logging.getLogger("xposts")
CONFIG_SECTIONS = ("xposts", "files")
REPORT_EVERY_RUNS = 30            # the report is rewritten about once an hour (every 2 minutes x 30)


def data_folder(cfg):
    return os.path.join(HERE, cfg["files"]["data_folder"])


def make_watcher(cfg, folder, token, session=None):
    api = XApi(token, session=session) if token else None
    return Watcher(cfg, folder, api)


def do_lookup(watcher, out=print):
    todo = watcher.unknown_handles()
    if not todo:
        out("Every handle already has a saved account ID (data/xposts/accounts.json); "
            "nothing asked, nothing paid.")
        return 0
    try:
        found, missing = watcher.lookup()
    except XError as exc:
        out(f"The lookup failed: {exc}")
        return 1
    price = watcher.c.get("price_per_user_usd", 0.010)
    out(f"Looked up {len(todo)} handle(s) in one request:")
    for handle in todo:
        user_id = found.get(handle.lower())
        out(f"  @{handle}: " + (f"found, account ID {user_id}" if user_id else "NOT FOUND on X"))
    out(f"Estimated cost: {len(found)} account(s) x ${price:g} = ${len(found) * price:.3f} "
        "(check the Usage page of your X console for the real amount).")
    if missing:
        out("The handles marked NOT FOUND are skipped from now on. To fix one, correct it in "
            "config.toml under [xposts] accounts.")
    return 0


def do_test(watcher, handle, out=print):
    handle = handle.lstrip("@")
    if handle.lower() not in {h.lower() for h in watcher.handles}:
        out(f"@{handle} is not in [xposts] accounts in config.toml.")
        return 1
    if handle.lower() not in watcher.accounts.get("ids", {}):
        out("Its account ID is not saved yet: looking up the watched handles first (one request).")
        if do_lookup(watcher, out) != 0:
            return 1
    user_id = watcher.accounts.get("ids", {}).get(handle.lower())
    if not user_id:
        out(f"@{handle} was not found on X, so there is nothing to test.")
        return 1
    try:
        posts, meta = watcher.api.posts(user_id, MIN_RESULTS)
    except XError as exc:
        out(f"The test request failed: {exc}")
        return 1
    price = watcher.c.get("price_per_post_usd", 0.005)
    out(f"One request for @{handle} (account ID {user_id}): {len(posts)} original post(s) "
        f"returned (X's own count: {meta.get('result_count', len(posts))}).")
    for p in posts:
        out(f"  {p.get('created_at', '?')}  id {p['id']}: {p.get('text', '')[:120]!r}")
    out(f"Estimated cost: {len(posts)} post(s) x ${price:g} = ${len(posts) * price:.3f} "
        "(check the Usage page of your X console for the real amount).")
    headers = watcher.api.cost_headers()
    out("Credit or usage information sent by X: " + (str(headers) if headers else "none"))
    out("Nothing was saved. Next: the empty-check test (deploy/LAUNCH_SERVER_SETUP.md, Part M, "
        "step M5), then the regular checking (step M6).")
    return 0


def do_empty_test(watcher, handle, times=3, out=print, sleep=time.sleep, clock=None):
    """`times` requests for one account asking only for posts newer than its newest one: the
    since_id is made from the current time, which is newer than any post already made, so the
    answer is empty and no post is read. Saves nothing and changes no saved state."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    handle = handle.lstrip("@")
    user_id = watcher.accounts.get("ids", {}).get(handle.lower())
    if not user_id:
        out(f"@{handle} has no saved account ID: run --lookup first (or check the name).")
        return 1
    out(f"Empty-check test for @{handle} (account ID {user_id}): {times} request(s) for posts "
        "newer than right now, so each should return 0 posts.")
    returned = 0
    for i in range(1, times + 1):
        since = snowflake(clock())
        try:
            posts, meta = watcher.api.posts(user_id, MIN_RESULTS, since_id=since)
        except XError as exc:
            out(f"  request {i}: failed: {exc}")
            return 1
        returned += len(posts)
        headers = watcher.api.cost_headers()
        out(f"  request {i} at {clock():%H:%M:%S} UTC: {len(posts)} post(s) returned "
            f"(X's count: {meta.get('result_count', len(posts))})"
            + (f"; X reports: {headers}" if headers else ""))
        if i < times:
            sleep(2)
    price = watcher.c.get("price_per_post_usd", 0.005)
    out(f"Done: {times} request(s), {returned} post(s) returned. If empty checks are free, these "
        f"cost $0.000 (posts returned x ${price:g} = ${returned * price:.3f}). Check the Usage "
        "page of your X console (deploy/LAUNCH_SERVER_SETUP.md, Part M, step M5). Nothing was "
        "saved.")
    return 0


def make_mentions(cfg, folder):
    """The ticker-mention recorder, or None when [xposts] mentions = false. DexScreener lookups
    are tried once each (no retry inside a request: a failed one is tried at the next check)."""
    if not cfg["xposts"].get("mentions", True):
        return None
    return Mentions(cfg, folder, PublicApi(timeout=10, dexscreener_attempts=1))


def mention_checks(mentions, every, stop, sleep=time.sleep):
    """The mentions' lookups and checkpoints every `every` seconds, beside the X rounds (the
    5-minute checkpoint has only a 2-minute tolerance). Never stops the watcher."""
    while not stop():
        mentions.tick()
        sleep(every)


class Bot:
    def __init__(self, watcher, folder, mentions=None):
        self.watcher, self.folder, self.runs = watcher, folder, 0
        self.mentions = mentions

    def run_once(self, now, out):
        saved = self.watcher.run_once(now, out)
        if self.mentions is not None and saved:
            self.mentions.add_posts(saved, now)
        self.runs += 1
        if self.runs % REPORT_EVERY_RUNS == 1:
            try:
                write_report(self.folder, self.watcher.c, now)
            except Exception:                      # a report is never worth stopping for
                log.exception("the report could not be written")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lookup", action="store_true",
                        help="look up the handles' account IDs once (one paid request)")
    parser.add_argument("--test", metavar="HANDLE",
                        help="one paid request for this account's newest posts; saves no post")
    parser.add_argument("--empty-test", metavar="HANDLE",
                        help="3 requests that return no post, to see whether empty checks cost")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config()
    if not cfg.get("xposts", {}).get("enabled"):
        print("The X post watcher is turned off in config.toml ([xposts] enabled = false).")
        return 0
    folder = data_folder(cfg)
    token = secret()
    if args.lookup or args.test or args.empty_test:
        if not token:
            print("No X token found. See deploy/LAUNCH_SERVER_SETUP.md, Part M, step M2.")
            return 1
        watcher = make_watcher(cfg, folder, token)
        if args.empty_test:
            return do_empty_test(watcher, args.empty_test)
        return do_lookup(watcher) if args.lookup else do_test(watcher, args.test)
    watcher = make_watcher(cfg, folder, token)
    if not token:
        log.warning("no X token: the watcher runs but asks X nothing (Part M, step M2)")
    # systemd stops the bot with SIGTERM: between rounds it exits at once; in the middle of a
    # round it finishes and saves first.
    stopping, busy = [], []

    def on_term(*_):
        stopping.append(1)
        if not busy:
            raise SystemExit(0)
    signal.signal(signal.SIGTERM, on_term)

    class Guarded(Bot):
        def run_once(self, now, out):
            busy.append(1)
            try:
                return super().run_once(now, out)
            finally:
                busy.clear()
    every = cfg["xposts"]["every_seconds"]
    print(f"X post watcher: {len(watcher.handles)} account(s) every {every} s, at most "
          f"{cfg['xposts']['max_posts_per_day']} posts a day", flush=True)
    mentions = make_mentions(cfg, folder)
    if mentions is not None:
        threading.Thread(target=mention_checks, daemon=True, name="mentions",
                         args=(mentions, cfg["xposts"].get("mentions_check_seconds", 20),
                               lambda: bool(stopping))).start()
    watch = CodeWatcher(HERE, CONFIG_SECTIONS)
    if run_forever(Guarded(watcher, folder, mentions), every, out=lambda s: print(s, flush=True),
                   stop=lambda: bool(stopping), watcher=watch, logger=log):
        log.info("stopped; systemd starts the new code in about 10 s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
