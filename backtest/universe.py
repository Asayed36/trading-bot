"""The coins, and what trading each costs.

Prices come from Binance's public data archive (data.binance.vision), USDT
pairs. The list was written by hand before any result was looked at. It is
NOT a list of everything that existed in 2020-2023: coins that collapsed or
were delisted (LUNA, FTT, ...) are not in it, so it flatters every long-only
strategy (survivorship bias). The summary says so.
"""

# label -> Binance spot symbols, oldest first (a coin renamed on the exchange
# is stitched together: RNDR became RENDER 1:1 in 2024).
COINS = {
    "BTC": ["BTCUSDT"], "ETH": ["ETHUSDT"], "SOL": ["SOLUSDT"],
    "BNB": ["BNBUSDT"], "XRP": ["XRPUSDT"], "ADA": ["ADAUSDT"], "DOGE": ["DOGEUSDT"],
    "LINK": ["LINKUSDT"], "AVAX": ["AVAXUSDT"], "DOT": ["DOTUSDT"], "LTC": ["LTCUSDT"],
    "ATOM": ["ATOMUSDT"], "NEAR": ["NEARUSDT"], "UNI": ["UNIUSDT"],
    "SUI": ["SUIUSDT"], "ONDO": ["ONDOUSDT"], "TAO": ["TAOUSDT"],
    "RENDER": ["RNDRUSDT", "RENDERUSDT"],
}
MAJORS = ("BTC", "ETH", "SOL")

# Quick check of the tool (a workflow option): four coins.
QUICK = ("BTC", "ETH", "SOL", "LINK")

FEE = 0.0010              # per side, on the money traded
SLIPPAGE_MAJOR = 0.0005   # per side, BTC / ETH / SOL
SLIPPAGE_OTHER = 0.0020   # per side, every other coin


def slippage(label):
    return SLIPPAGE_MAJOR if label in MAJORS else SLIPPAGE_OTHER
