"""Where the project lives and how config.toml is read. Kept apart from
run.py so the server bots (launch_bot.py, main_1min.py) don't load every
strategy just to read their settings: they only restart for code they use
(screener/autorestart.py)."""

import os
import tomllib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=os.path.join(HERE, "config.toml")):
    with open(path, "rb") as fh:
        return tomllib.load(fh)
