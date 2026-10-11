"""Small synthetic coins for the backtest tests (no network)."""

import os
import random
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest import data  # noqa: E402

HOUR_MS = 3_600_000


def day_number(d):
    return d.toordinal() - data.EPOCH_ORDINAL


def hours_for_day(o, h, l, c):
    """24 hourly (open, high, low, close) bars that start at o, end at c and
    whose extremes are exactly h and l (low in hour 6, high in hour 12)."""
    bars = []
    for k in range(24):
        a = o + (c - o) * k / 24
        b = o + (c - o) * (k + 1) / 24
        hi, lo = max(a, b), min(a, b)
        if k == 12:
            hi = max(hi, h)
        if k == 6:
            lo = min(lo, l)
        bars.append((a, hi, lo, b))
    return bars


def make_coin(label, start, daily, hourly=None):
    """daily: [(o, h, l, c)] one per day from `start` (a date).
    hourly: {day offset: [24 (o, h, l, c) bars]} to override the default path."""
    hourly = hourly or {}
    d_rows, h_rows = [], []
    for k, (o, h, l, c) in enumerate(daily):
        t0 = (day_number(start) + k) * data.DAY_MS
        d_rows.append((t0, o, h, l, c, 1.0))
        bars = hourly.get(k) or hours_for_day(o, h, l, c)
        for j, (a, hi, lo, b) in enumerate(bars):
            h_rows.append((t0 + j * HOUR_MS, a, hi, lo, b, 1.0))
    return data.build_coin(label, [label + "USDT"], d_rows, h_rows)


def flat_days(n, price=100.0):
    return [(price, price, price, price)] * n


def random_walk(label, start, n, seed, drift=0.0005, vol=0.03):
    """A reproducible random-walk coin of n days."""
    rng = random.Random(seed)
    price, daily = 100.0, []
    for _ in range(n):
        o = price
        c = o * (1 + rng.gauss(drift, vol))
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 3)))
        l = min(o, c) * (1 - abs(rng.gauss(0, vol / 3)))
        daily.append((o, h, l, c))
        price = c
    return make_coin(label, start, daily)


def random_daily(n, seed, price=100.0, drift=0.0005, vol=0.03):
    """n reproducible daily candles starting from `price`."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        o = price
        c = o * (1 + rng.gauss(drift, vol))
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 3)))
        l = min(o, c) * (1 - abs(rng.gauss(0, vol / 3)))
        out.append((o, h, l, c))
        price = c
    return out
