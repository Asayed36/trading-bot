"""Standard indicators on plain lists. Value i uses data up to and including
index i only (never later), and is None until it can be worked out."""


def sma(values, n):
    out, total = [None] * len(values), 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def highest_before(values, n):
    """out[i] = the highest of the n values BEFORE index i (not i itself)."""
    out = [None] * len(values)
    for i in range(n, len(values)):
        out[i] = max(values[i - n:i])
    return out


def true_range(high, low, close):
    out = [high[0] - low[0]]
    for i in range(1, len(close)):
        out.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return out


def wilder(values, n):
    """Wilder's smoothing: the first value is the mean of the first n."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    out[n - 1] = sum(values[:n]) / n
    for i in range(n, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return out


def atr(high, low, close, n=14):
    return wilder(true_range(high, low, close), n)


def rsi(close, n=2):
    """Wilder's RSI (0-100)."""
    out = [None] * len(close)
    if len(close) <= n:
        return out
    gains = [max(close[i] - close[i - 1], 0.0) for i in range(1, len(close))]
    losses = [max(close[i - 1] - close[i], 0.0) for i in range(1, len(close))]
    avg_gain, avg_loss = sum(gains[:n]) / n, sum(losses[:n]) / n

    def value(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[n] = value(avg_gain, avg_loss)
    for i in range(n + 1, len(close)):
        avg_gain = (avg_gain * (n - 1) + gains[i - 1]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i - 1]) / n
        out[i] = value(avg_gain, avg_loss)
    return out


def adx(high, low, close, n=14):
    """Wilder's ADX (0-100): how strongly the price is trending, either way."""
    size = len(close)
    out = [None] * size
    if size < 2 * n:
        return out
    tr, plus, minus = [0.0], [0.0], [0.0]
    for i in range(1, size):
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    # Wilder sums over the first n changes, then rolling
    s_tr, s_plus, s_minus = sum(tr[1:n + 1]), sum(plus[1:n + 1]), sum(minus[1:n + 1])
    dx = [None] * size

    def dx_value(a, b, c):
        if c == 0:
            return 0.0
        pdi, mdi = 100 * a / c, 100 * b / c
        return 0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi)

    dx[n] = dx_value(s_plus, s_minus, s_tr)
    for i in range(n + 1, size):
        s_tr = s_tr - s_tr / n + tr[i]
        s_plus = s_plus - s_plus / n + plus[i]
        s_minus = s_minus - s_minus / n + minus[i]
        dx[i] = dx_value(s_plus, s_minus, s_tr)
    first = 2 * n - 1
    out[first] = sum(dx[n:2 * n]) / n
    for i in range(first + 1, size):
        out[i] = (out[i - 1] * (n - 1) + dx[i]) / n
    return out


def laguerre_rsi(close, gamma=0.5):
    """Ehlers' Laguerre RSI (0-1)."""
    out = [None] * len(close)
    l0 = l1 = l2 = l3 = close[0]
    for i, price in enumerate(close):
        p0, p1, p2, p3 = l0, l1, l2, l3
        l0 = (1 - gamma) * price + gamma * p0
        l1 = -gamma * l0 + p0 + gamma * p1
        l2 = -gamma * l1 + p1 + gamma * p2
        l3 = -gamma * l2 + p2 + gamma * p3
        up = down = 0.0
        for a, b in ((l0, l1), (l1, l2), (l2, l3)):
            if a >= b:
                up += a - b
            else:
                down += b - a
        out[i] = None if i < 4 else (0.5 if up + down == 0 else up / (up + down))
    return out
