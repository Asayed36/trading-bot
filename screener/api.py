"""Talks to the two free public websites we use for data.

Everything here only READS public information. There are no API keys, no
wallets, and no way to place orders. Every function just asks a website a
question and returns the answer.
"""

import time

import requests

DEXSCREENER = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz"

HEADERS = {"User-Agent": "memecoin-screener/1.0 (read-only paper trading)"}


class ApiError(Exception):
    """Raised when a website can't be reached or gives a bad answer."""


class PublicApi:
    def __init__(self, timeout=20, rugcheck_delay=1.5):
        self.timeout = timeout
        self.rugcheck_delay = rugcheck_delay
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
            if resp.status_code == 429 and attempt < 2:  # "slow down, too many requests"
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                raise ApiError(f"{url} answered with error {resp.status_code}")
            return resp.json()
        raise ApiError(f"{url} kept saying 'too many requests'")

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

    # ---- RugCheck (token safety) ----

    def rugcheck_report(self, address):
        wait = self.rugcheck_delay - (time.time() - self._last_rugcheck)
        if wait > 0:
            time.sleep(wait)
        try:
            return self._get(f"{RUGCHECK}/v1/tokens/{address}/report")
        finally:
            self._last_rugcheck = time.time()
