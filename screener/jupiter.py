"""Jupiter's organic score for a Solana token, for the entries.csv logs.

Logging only: nothing here decides a trade. Jupiter scores how much of a
token's trading looks organic (real wallets) rather than bots or wash
trading. It's saved at every paper buy so we can later check whether
low-scoring tokens did worse.

Source: Jupiter's free Tokens API (no key), one GET per token:
    https://lite-api.jup.ag/tokens/v2/search?query=<mint>

Values (blank in entries.csv when unknown):
    jupiter_organic_score          0-100
    jupiter_organic_label          "low" / "medium" / "high"
    jupiter_organic_volume_1h_pct  organic buy volume / all buy volume, last hour
    jupiter_organic_buyers_1h_pct  organic buyers / all traders, last hour
    jupiter_{traders,buys,sells}_{1h,5m}             distinct traders, buys and
                                   sells over the last hour / 5 minutes
    jupiter_{buy,sell}_volume_{1h,5m}_usd           buy and sell volume ($)
                                   (from the same answer: Jupiter's stats1h
                                   and stats5m numTraders, numBuys, numSells,
                                   buyVolume and sellVolume; blank when
                                   Jupiter doesn't give them)

Read-only. A failed or slow lookup just leaves the values blank: it never
stops or delays a paper buy by more than the timeout.
"""

import requests

from screener.filters import to_float

URL = "https://lite-api.jup.ag/tokens/v2/search"
HEADERS = {"User-Agent": "memecoin-screener/1.0 (read-only paper trading)"}
# Logged as they come, per window: column suffix -> Jupiter's field.
ACTIVITY = {"traders": "numTraders", "buys": "numBuys", "sells": "numSells",
            "buy_volume": "buyVolume", "sell_volume": "sellVolume"}
WINDOWS = {"1h": "stats1h", "5m": "stats5m"}


def _column(name, window):
    return f"jupiter_{name}_{window}" + ("_usd" if "volume" in name else "")


ACTIVITY_COLUMNS = [_column(name, w) for w in WINDOWS for name in ACTIVITY]
COLUMNS = ["jupiter_organic_score", "jupiter_organic_label",
           "jupiter_organic_volume_1h_pct", "jupiter_organic_buyers_1h_pct",
           *ACTIVITY_COLUMNS]


def _ratio(part, whole):
    part, whole = to_float(part), to_float(whole)
    if part is None or not whole:
        return None
    return round(part / whole * 100, 2)


def organic_values(token, mint):
    """The values (COLUMNS) from one Tokens API row (None where unknown)."""
    if not token or token.get("id") != mint:
        return dict.fromkeys(COLUMNS)
    stats = token.get("stats1h") or {}
    score = to_float(token.get("organicScore"))
    label = token.get("organicScoreLabel")
    activity = {}
    for w, key in WINDOWS.items():
        window = token.get(key) or {}
        for name, field in ACTIVITY.items():
            value = to_float(window.get(field))
            activity[_column(name, w)] = None if value is None else round(value, 2)
    return {
        **activity,
        "jupiter_organic_score": None if score is None else round(score, 2),
        "jupiter_organic_label": label if isinstance(label, str) and label else None,
        "jupiter_organic_volume_1h_pct": _ratio(stats.get("buyOrganicVolume"),
                                                stats.get("buyVolume")),
        "jupiter_organic_buyers_1h_pct": _ratio(stats.get("numOrganicBuyers"),
                                                stats.get("numTraders")),
    }


# In the values when Jupiter didn't answer (an error or no reply), so a
# caller can tell "no answer yet" from "answered: no score for this token".
ERROR = "jupiter_error"


class JupiterOrganic:
    """Callable: mint -> the four values (plus ERROR when Jupiter didn't
    answer). Never raises."""

    def __init__(self, timeout=8, get=requests.get):
        self.timeout = timeout
        self.get = get

    def __call__(self, mint):
        try:
            resp = self.get(URL, params={"query": mint}, headers=HEADERS, timeout=self.timeout)
            if resp.status_code != 200:
                return dict(dict.fromkeys(COLUMNS), **{ERROR: f"HTTP {resp.status_code}"})
            rows = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return dict(dict.fromkeys(COLUMNS), **{ERROR: type(exc).__name__})
        rows = rows if isinstance(rows, list) else []
        token = next((r for r in rows if isinstance(r, dict) and r.get("id") == mint), None)
        return organic_values(token, mint)
