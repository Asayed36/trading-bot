"""Checks for the server bots' automatic restarts (screener/autorestart.py,
launch_bot.py, main_1min.py) when the hourly push brings new code.
Run with:  python -m unittest -v
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launch_bot  # noqa: E402
import main_1min as m1  # noqa: E402
from screener.autorestart import CodeWatcher, project_files, restart_message  # noqa: E402
from screener.settings import HERE, load_config  # noqa: E402

CFG = load_config()
CONFIG = '[launch]\nbuy = 5\n\n[robinhood]\nmin = 10\n'


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "screener"))
        self.write("bot.py", "v1")
        self.write("screener/lib.py", "v1")
        self.write("config.toml", CONFIG)
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w") as fh:
            fh.write(text)

    def watcher(self, sections=("launch",)):
        return CodeWatcher(self.root, sections, files=["bot.py", "screener/lib.py"],
                           settle_seconds=30, clock=self.clock)

    def after(self, seconds, w):
        self.clock.now += seconds
        return w.changed()


class WatcherTests(Repo):
    def test_nothing_changed(self):
        w = self.watcher()
        self.assertIsNone(self.after(60, w))
        self.assertIsNone(self.after(3600, w))

    def test_a_change_restarts_once_it_has_settled(self):
        w = self.watcher()
        self.write("screener/lib.py", "v2")
        self.assertIsNone(self.after(1, w))          # just seen
        self.assertIsNone(self.after(20, w))         # still settling
        self.write("bot.py", "v2")                   # the push is still writing
        self.assertIsNone(self.after(20, w))         # starts settling again
        self.assertIsNone(self.after(20, w))
        self.assertEqual(self.after(15, w), ["bot.py", "screener/lib.py"])

    def test_a_change_undone_before_it_settles_is_forgotten(self):
        w = self.watcher()
        self.write("bot.py", "v2")
        self.assertIsNone(self.after(1, w))
        self.write("bot.py", "v1")
        self.assertIsNone(self.after(40, w))
        self.assertIsNone(self.after(40, w))

    def test_only_the_bots_own_config_sections_count(self):
        w = self.watcher(("launch",))
        self.write("config.toml", CONFIG.replace("min = 10", "min = 5"))   # robinhood's
        self.assertIsNone(self.after(1, w))
        self.assertIsNone(self.after(60, w))
        self.write("config.toml", CONFIG.replace("buy = 5", "buy = 10"))   # its own
        self.assertIsNone(self.after(1, w))
        self.assertEqual(self.after(31, w), ["config.toml [launch]"])

    def test_a_half_written_config_waits(self):
        w = self.watcher()
        self.write("config.toml", "[launch\nbuy =")
        for _ in range(3):
            self.assertIsNone(self.after(60, w))
        self.write("config.toml", CONFIG)
        self.assertIsNone(self.after(60, w))

    def test_a_deleted_file_counts(self):
        w = self.watcher()
        os.remove(os.path.join(self.root, "screener", "lib.py"))
        self.assertIsNone(self.after(1, w))
        self.assertEqual(self.after(31, w), ["screener/lib.py"])

    def test_the_log_message(self):
        self.assertEqual(restart_message(["launch_bot.py", "screener/launch.py"]),
                         "automatic restart: new code from the hourly push in launch_bot.py, "
                         "screener/launch.py; saving everything and exiting so systemd starts "
                         "the new version")


class ProjectFilesTests(Repo):
    def test_only_the_projects_own_python_files(self):
        def mod(path):
            return types.SimpleNamespace(__file__=os.path.join(self.root, path))
        modules = {"a": mod("bot.py"), "b": mod("screener/lib.py"),
                   "c": mod(".venv/lib/python3.12/site-packages/requests/api.py"),
                   "d": types.SimpleNamespace(__file__="/usr/lib/python3.12/json/__init__.py"),
                   "e": types.SimpleNamespace(), "f": mod("data/thing.so")}
        self.assertEqual(project_files(self.root, modules), ["bot.py", "screener/lib.py"])

    def test_the_bots_dont_load_other_strategies(self):
        # So a change to another strategy (robinhood, news, ...) or to run.py
        # never restarts them.
        files = {}
        for bot in ("launch_bot", "main_1min"):
            out = subprocess.run(
                [sys.executable, "-c", f"import {bot}, json; from screener.autorestart import "
                 "project_files; from screener.settings import HERE; "
                 "print(json.dumps(project_files(HERE)))"],
                cwd=HERE, capture_output=True, text=True, check=True).stdout
            files[bot] = json.loads(out)
        self.assertIn("screener/launch.py", files["launch_bot"])
        self.assertNotIn("main_1min.py", files["launch_bot"])
        self.assertNotIn("screener/launch.py", files["main_1min"])
        files = files["launch_bot"] + files["main_1min"]
        for name in ("run.py", "screener/robinhood.py", "screener/news.py",
                     "screener/convergence.py", "screener/early.py"):
            self.assertNotIn(name, files)
        for name in ("launch_bot.py", "main_1min.py", "screener/launch.py",
                     "screener/filters.py", "screener/paper_trader.py"):
            self.assertIn(name, files)


class FakeWatcher:
    def __init__(self, after_calls, changed=("screener/launch.py",)):
        self.calls, self.after, self.result = 0, after_calls, list(changed)
        self.files = []

    def changed(self):
        self.calls += 1
        return self.result if self.calls >= self.after else None


class LaunchBotTests(unittest.TestCase):
    def test_saves_everything_and_exits_on_new_code(self):
        with tempfile.TemporaryDirectory() as d:
            runner = launch_bot.Runner(CFG, d, FakeWatcher(after_calls=2))

            async def idle(self=runner):
                await self.stop.wait()
            runner.feed = runner.prices = runner.organic = idle
            saves = []
            runner.engine.save = lambda: saves.append(1)
            with mock.patch.object(launch_bot, "CODE_CHECK_SECONDS", 0.01), \
                    self.assertLogs("launch_bot", "INFO") as logs:
                asyncio.run(asyncio.wait_for(runner.main(), 5))
        self.assertEqual(runner.restarting, ["screener/launch.py"])
        self.assertTrue(saves)                               # saved before exiting
        text = "\n".join(logs.output)
        self.assertIn("automatic restart: new code from the hourly push in "
                      "screener/launch.py", text)
        self.assertIn("stopped; everything saved; systemd starts the new code", text)

    def test_no_watcher_in_test_mode(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(launch_bot.Runner(CFG, d).watcher)


class MainOneMinuteTests(unittest.TestCase):
    def test_exits_between_runs_on_new_code(self):
        runs, sleeps = [], []

        class Bot:
            def run_once(self, now, out):
                runs.append(now)

        with self.assertLogs("main_1min", "WARNING") as logs:
            changed = m1.forever(Bot(), 60, clock=lambda: 1_000_000.0, sleep=sleeps.append,
                                 watcher=FakeWatcher(after_calls=3, changed=["main_1min.py"]))
        self.assertEqual(changed, ["main_1min.py"])
        self.assertEqual(len(runs), 3)          # the third run finished (and saved) first
        self.assertEqual(len(sleeps), 2)        # no sleep after the last run
        self.assertIn("automatic restart: new code from the hourly push in main_1min.py",
                      logs.output[0])

    def test_keeps_going_without_changes(self):
        runs = []

        class Bot:
            def run_once(self, now, out):
                runs.append(now)

        m1.forever(Bot(), 60, clock=lambda: 0.0, sleep=lambda s: None,
                   stop=lambda: len(runs) >= 5, watcher=FakeWatcher(after_calls=99))
        self.assertEqual(len(runs), 5)


class ServiceTests(unittest.TestCase):
    def test_systemd_restarts_a_clean_exit(self):
        # The bots exit with code 0 on new code; Restart=always (not
        # on-failure) is what makes systemd start them again.
        for name in ("launch-bot.service", "main-1min.service"):
            with open(os.path.join(HERE, "deploy", name)) as fh:
                text = fh.read()
            self.assertIn("Restart=always", text)
            self.assertIn("RestartSec=10", text)
            self.assertIn("User=bot", text)
            self.assertNotIn("sudo", text.lower())


if __name__ == "__main__":
    unittest.main()
