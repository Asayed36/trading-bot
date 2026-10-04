"""pump.fun's on-chain events, read from the Solana public RPC's
logsSubscribe on the pump.fun program (read-only, no key, no wallet).

Each pump.fun transaction logs its events as "Program data: <base64>"
lines (Anchor events, recognised by their first 8 bytes). Three are used:

  TradeEvent    every buy or sell on the bonding curve: the token, SOL and
                token amounts, buy or sell, the wallet, the on-chain time,
                and the curve's reserves after the trade (= the price)
  CreateEvent   a new launch: name, symbol, the token and its creator
  CompleteEvent the curve is complete: the token graduates (it then
                trades elsewhere, not on this program)

The layouts were checked against the real chain with trade_feed_probe.py.
"""

import base64
import json

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# Anchor event discriminators: sha256("event:<Name>")[:8].
TRADE_EVENT = bytes.fromhex("bddb7fd34ee661ee")
CREATE_EVENT = bytes.fromhex("1b72a94ddeeb6376")
COMPLETE_EVENT = bytes.fromhex("5f72619cd42e9808")
# The only request ever sent to the RPC (a read-only subscription).
ALLOWED_METHODS = {"logsSubscribe"}
# A pump.fun curve starts with this many tokens to sell (793.1 million,
# 6 decimals): how far it is to graduating is the share already sold.
CURVE_TOKENS = 793_100_000 * 10**6
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def subscribe_request(method="logsSubscribe", request_id=1):
    """The one subscription message, refusing anything that isn't read-only."""
    if method not in ALLOWED_METHODS:
        raise ValueError(f"{method} is not an allowed read-only request")
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                       "params": [{"mentions": [PUMP_PROGRAM]}, {"commitment": "confirmed"}]})


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def _u64(data, at):
    return int.from_bytes(data[at:at + 8], "little")


def decode(logs):
    """The events in one transaction's logs, in order, as dicts with a
    "kind" of "trade", "create" or "complete"."""
    events = []
    for line in logs or []:
        if not line.startswith("Program data: "):
            continue
        try:
            data = base64.b64decode(line[14:], validate=False)
        except ValueError:
            continue
        head = data[:8]
        if head == TRADE_EVENT and len(data) >= 129:
            vsol, vtok, real_tok = _u64(data, 97), _u64(data, 105), _u64(data, 121)
            events.append({
                "kind": "trade", "mint": b58encode(data[8:40]),
                "sol": _u64(data, 40) / 1e9, "is_buy": data[56] == 1,
                "user": b58encode(data[57:89]),
                "ts": int.from_bytes(data[89:97], "little", signed=True),
                # SOL per token after the trade (9 and 6 decimals).
                "price_sol": (vsol / 1e9) / (vtok / 1e6) if vtok else None,
                "progress_pct": round(100 * (1 - real_tok / CURVE_TOKENS), 2),
            })
        elif head == CREATE_EVENT:
            pos, texts = 8, []
            try:
                for _ in range(3):           # name, symbol, uri: u32 length + bytes
                    size = int.from_bytes(data[pos:pos + 4], "little")
                    texts.append(data[pos + 4:pos + 4 + size].decode("utf-8", "replace"))
                    pos += 4 + size
            except (IndexError, ValueError):
                continue
            if len(data) >= pos + 96:        # mint, bonding curve, creator
                events.append({"kind": "create", "name": texts[0].strip(),
                               "symbol": texts[1].strip(), "mint": b58encode(data[pos:pos + 32]),
                               "creator": b58encode(data[pos + 64:pos + 96])})
        elif head == COMPLETE_EVENT and len(data) >= 72:   # user, mint, ...
            events.append({"kind": "complete", "mint": b58encode(data[40:72])})
    return events
