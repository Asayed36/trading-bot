"""Writes data/main-1min/timing_report.md: when tokens were launched and what
happened to them afterwards (screener/timing_report.py). Report only: it reads
the saved data files, makes no request and changes no bot or setting.

    python timing_report.py
"""

import os
import sys

from screener.settings import HERE, load_config
from screener.timing_report import main

if __name__ == "__main__":
    cfg = load_config()
    path = main(os.path.join(HERE, cfg["files"]["data_folder"]),
                cfg["filters"]["min_liquidity_usd"])
    print(f"Wrote {os.path.relpath(path, HERE)}")
    sys.exit(0)
