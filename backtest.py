from bot import get_daily_bars, TAKE_PROFIT_R_MULTIPLE

SYMBOLS = [
    "AAPL", "AMD", "NVDA", "TSLA", "MSFT", "META", "AMZN", "GOOGL",
    "AVGO", "NFLX", "PLTR", "COIN", "SOFI", "RIVN", "SMCI", "QQQ", "IWM"
]

MIN_STOCK_PRICE = 10
MAX_STOCK_PRICE = 750
MIN_AVG_VOLUME = 250_000
STOP_BUFFER_PERCENT = 0.01
MIN_BREAKOUT_REL_VOLUME = 1.1
MAX_EXTENSION_FROM_SMA20 = 0.10


def breakout_signal_from_bars(symbol, bars):
    if len(bars) < 50:
        return None

    yesterday = bars.iloc[-2]
    today = bars.iloc[-1]

    avg_volume = bars["volume"].tail(20).mean()
    current_volume = float(today["volume"])
    current_price = float(today["close"])
    prior_high = float(yesterday["high"])

    sma_20 = bars["close"].tail(20).mean()

    relative_volume = current_volume / avg_volume if avg_volume > 0 else 0
    extension_from_sma20 = (current_price - sma_20) / sma_20

    if current_price < MIN_STOCK_PRICE or current_price > MAX_STOCK_PRICE:
        return None

    if avg_volume < MIN_AVG_VOLUME:
        return None

    if relative_volume < MIN_BREAKOUT_REL_VOLUME:
        return None

    if extension_from_sma20 > MAX_EXTENSION_FROM_SMA20:
        return None

    if current_price <= prior_high:
        return None

    entry = round(current_price, 2)
    stop = round(prior_high * (1 - STOP_BUFFER_PERCENT), 2)

    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return None

    target = round(entry + risk_per_share * TAKE_PROFIT_R_MULTIPLE, 2)

    return {
        "symbol": symbol,
        "model": "breakout",
        "entry": entry,
        "stop": stop,
        "target": target
    }


def pullback_signal_from_bars(symbol, bars):
    if len(bars) < 50:
        return None

    today = bars.iloc[-1]
    yesterday = bars.iloc[-2]
    two_days_ago = bars.iloc[-3]

    close = float(today["close"])
    open_price = float(today["open"])
    yesterday_close = float(yesterday["close"])
    two_days_ago_close = float(two_days_ago["close"])

    avg_volume = bars["volume"].tail(20).mean()
    sma_20 = bars["close"].tail(20).mean()
    sma_50 = bars["close"].tail(50).mean()

    if close < MIN_STOCK_PRICE or close > MAX_STOCK_PRICE:
        return None

    if avg_volume < MIN_AVG_VOLUME:
        return None

    if close < sma_20 or close < sma_50:
        return None

    if sma_20 < sma_50:
        return None

    if yesterday_close >= two_days_ago_close:
        return None

    if close <= yesterday_close:
        return None

    if close <= open_price:
        return None

    entry = round(close, 2)
    stop = round(min(float(yesterday["low"]), float(two_days_ago["low"])) * 0.99, 2)

    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return None

    target = round(entry + risk_per_share * TAKE_PROFIT_R_MULTIPLE, 2)

    return {
        "symbol": symbol,
        "model": "pullback",
        "entry": entry,
        "stop": stop,
        "target": target
    }


def simulate_trade(signal, future_bars):
    entry = signal["entry"]
    stop = signal["stop"]
    target = signal["target"]

    for _, bar in future_bars.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])

        if high >= target:
            return TAKE_PROFIT_R_MULTIPLE

        if low <= stop:
            return -1

    return 0


def backtest_symbol(symbol):
    bars = get_daily_bars(symbol, days=180)

    if len(bars) < 70:
        return []

    results = []

    for i in range(60, len(bars) - 5):
        history = bars.iloc[:i]
        future = bars.iloc[i:i + 5]

        signal = breakout_signal_from_bars(symbol, history)

        if signal is None:
            signal = pullback_signal_from_bars(symbol, history)

        if signal is None:
            continue

        result = simulate_trade(signal, future)

        results.append({
            "symbol": symbol,
            "model": signal["model"],
            "result": result
        })

    return results


def run_backtest():
    all_results = []

    for symbol in SYMBOLS:
        print(f"Testing {symbol}...")
        all_results.extend(backtest_symbol(symbol))

    if not all_results:
        print("No trades found.")
        return

    total = len(all_results)
    wins = sum(1 for r in all_results if r["result"] > 0)
    losses = sum(1 for r in all_results if r["result"] < 0)
    flat = sum(1 for r in all_results if r["result"] == 0)
    profit = sum(r["result"] for r in all_results)
    win_rate = wins / total * 100

    print("\n===== BACKTEST RESULTS =====")
    print(f"Trades: {total}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Flat/No Exit: {flat}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total R: {profit:.2f}")
    print("============================")

    print("\n===== BY STRATEGY =====")
    models = sorted(set(r["model"] for r in all_results))

    for model in models:
        model_results = [r for r in all_results if r["model"] == model]
        model_total = len(model_results)
        model_wins = sum(1 for r in model_results if r["result"] > 0)
        model_profit = sum(r["result"] for r in model_results)
        model_win_rate = model_wins / model_total * 100 if model_total else 0

        print(f"{model}: Trades={model_total}, Win Rate={model_win_rate:.2f}%, Total R={model_profit:.2f}")


if __name__ == "__main__":
    run_backtest()
