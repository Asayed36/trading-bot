"""Automatic restarts for the server bots when their code changes.

The hourly push (deploy/push_results.sh) brings the server's checkout up to
date with GitHub. A bot that keeps running would go on with its old code,
so each bot (launch_bot.py, main_1min.py) watches what it actually runs:

  - every project file it has loaded (its own script and the screener/
    modules it imported; nothing from .venv or other installed packages), and
  - the parts of config.toml it reads (other strategies' settings don't
    count, so changing those never restarts it).

When any of that changes, and has stayed the same for settle_seconds (so a
push that is still writing files is never caught half-way), the bot logs
"automatic restart: ...", saves everything and exits cleanly. systemd's
Restart=always (in its .service file) then starts it again with the new
code. No sudo is needed: the bot only ever stops itself.
"""

import hashlib
import json
import logging
import os
import sys
import time
import tomllib

log = logging.getLogger("autorestart")


def project_files(root, modules=None):
    """The project's .py files among the loaded modules (paths relative to
    root): the bot's own code, not Python's or installed packages'."""
    root = os.path.realpath(root)
    files = set()
    for module in list((modules if modules is not None else sys.modules).values()):
        path = getattr(module, "__file__", None)
        if not path or not path.endswith(".py"):
            continue
        path = os.path.realpath(path)
        rel = os.path.relpath(path, root)
        if rel.startswith("..") or "site-packages" in rel or rel.split(os.sep)[0].startswith("."):
            continue
        files.add(rel)
    return sorted(files)


def _file_hash(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None                       # deleted counts as a change too


class CodeWatcher:
    """Tells the bot when its code (or its config sections) changed."""

    def __init__(self, root, config_sections, files=None, settle_seconds=30,
                 clock=time.time):
        self.root = root
        self.files = files if files is not None else project_files(root)
        self.sections = list(config_sections)
        self.settle = settle_seconds
        self.clock = clock
        self.started = self._snapshot()
        self.pending, self.pending_since = None, None

    def _config(self):
        """A fingerprint of the bot's own config.toml sections, or None if
        the file can't be read right now (half-written: try again later)."""
        try:
            with open(os.path.join(self.root, "config.toml"), "rb") as fh:
                cfg = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            return None
        picked = {name: cfg.get(name) for name in self.sections}
        return hashlib.sha256(json.dumps(picked, sort_keys=True, default=str)
                              .encode()).hexdigest()

    def _snapshot(self):
        snap = {rel: _file_hash(os.path.join(self.root, rel)) for rel in self.files}
        snap["config.toml " + ", ".join(f"[{s}]" for s in self.sections)] = self._config()
        return snap

    def changed(self):
        """None while nothing changed (or a change is still settling);
        otherwise the list of what changed since the bot started."""
        now, snap = self.clock(), self._snapshot()
        if any(v is None for k, v in snap.items() if k.startswith("config.toml")):
            return None                   # config.toml half-written: look again later
        if snap == self.started:
            self.pending = self.pending_since = None
            return None
        if snap != self.pending:
            self.pending, self.pending_since = snap, now
            return None
        if now - self.pending_since < self.settle:
            return None
        return sorted(k for k in snap if snap[k] != self.started.get(k))


def restart_message(changed):
    return ("automatic restart: new code from the hourly push in "
            + ", ".join(changed)
            + "; saving everything and exiting so systemd starts the new version")
