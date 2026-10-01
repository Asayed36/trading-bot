"""Talks to the free public websites we use for data (DexScreener, RugCheck
and GeckoTerminal).

Everything here only READS public information. There are no API keys, no
wallets, and no way to place orders. Every function just asks a website a
question and returns the answer.
"""

import time
from urllib.parse import quote

import requests

DEXSCREENER = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz"
GECKOTERMINAL = "https://api.geckoterminal.com/api/v2"

HEADERS = {"User-Agent": "memecoin-screener/1.0 (read-only paper trading)"}


class ApiError(Exception):
    """Raised when a website can't be reached or gives a bad answer."""


class RateLimited(ApiError):
    """Raised when a website keeps saying 'too many requests' (HTTP 429).
    The whole run should be skipped and tried again later."""


class PublicApi:
    def __init__(self, timeout=20, rugcheck_delay=1.5):
        self.timeout = timeout
        self.rugcheck_delay = rugcheck_delay
        self._rugcheck_cache = {}  # both strategies can ask about the same token
        self._last_gecko = 0.0
        self._last_rugcheck = 0.0

    def _get(self, url):
        """Ask a website for data. Retries a couple of times if it's busy."""
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=HEADERS, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise ApiError(f"could not reach {url}: {exc}") from exc
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code == 429:  # "slow down, too many requests"
                if attempt == 2:
                    raise RateLimited(f"{url} kept saying 'too many requests'")
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                raise ApiError(f"{url} answered with error {resp.status_code}")
            return resp.json()

    # ---- DexScreener (prices, volume, liquidity) ----

    def latest_profiles(self):
        return self._get(f"{DEXSCREENER}/token-profiles/latest/v1") or []

    def latest_boosts(self):
        return self._get(f"{DEXSCREENER}/token-boosts/latest/v1") or []

    def pairs_for_tokens(self, addresses):
        """Market data for many tokens. DexScreener allows 30 per request."""
        pairs = []
        addresses = list(addresses)
        for i in range(0, len(addresses), 30):
            chunk = ",".join(addresses[i:i + 30])
            pairs.extend(self._get(f"{DEXSCREENER}/tokens/v1/solana/{chunk}") or [])
        return pairs

    def search_pairs(self, query):
        """Every trading pair whose token name or symbol matches `query`."""
        found = self._get(f"{DEXSCREENER}/latest/dex/search?q={quote(query)}") or {}
        return found.get("pairs") or []

    # ---- GeckoTerminal (newest pools, recent trades) ----

    def gecko_new_pools(self, page=1):
        """The newest Solana pools, 20 per page. The free API allows about 30
        requests a minute, so requests are spaced out."""
        wait = 2.1 - (time.time() - self._last_gecko)
        if wait > 0:
            time.sleep(wait)
        try:
            found = self._get(f"{GECKOTERMINAL}/networks/solana/new_pools?page={page}") or {}
        finally:
            self._last_gecko = time.time()
        return found.get("data") or []

    def gecko_pool_trades(self, pool):
        """The latest trades (up to 300, last 24 hours) in one pool. Each has
        tx_from_address (the trader's wallet), kind ("buy"/"sell"),
        volume_in_usd and block_timestamp. Spaced out like new_pools."""
        wait = 2.1 - (time.time() - self._last_gecko)
        if wait > 0:
            time.sleep(wait)
        try:
            found = self._get(f"{GECKOTERMINAL}/networks/solana/pools/{quote(pool)}/trades") or {}
        finally:
            self._last_gecko = time.time()
        return [t.get("attributes") or {} for t in found.get("data") or []]

    # ---- RugCheck (token safety) ----

    def rugcheck_report(self, address):
        if address in self._rugcheck_cache:
            return self._rugcheck_cache[address]
        wait = self.rugcheck_delay - (time.time() - self._last_rugcheck)
        if wait > 0:
            time.sleep(wait)
        try:
            report = self._get(f"{RUGCHECK}/v1/tokens/{address}/report")
        finally:
            self._last_rugcheck = time.time()
        self._rugcheck_cache[address] = report
        return report
