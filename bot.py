import time
import os
import csv
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import time as sleep_time

import pandas as pd
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, AssetStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from trade_logger import log_trade_event


load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

PAPER_TRADING = True

USE_AUTO_SCANNER = True
MAX_SYMBOLS_TO_SCAN = int(os.getenv("MAX_SYMBOLS_TO_SCAN", "500"))
MAX_CANDIDATES_TO_TRADE = int(os.getenv("MAX_CANDIDATES_TO_TRADE", "10"))
SCANNER_BATCH_SIZE = int(os.getenv("SCANNER_BATCH_SIZE", "100"))

# Liquid symbols are scanned first; the remaining tradable universe is still
# included up to MAX_SYMBOLS_TO_SCAN. This avoids spending an hour before the
# bot reaches symbols it actually trades most often.
PREFERRED_SCANNER_SYMBOLS = [
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA",
    "META", "AMZN", "GOOGL", "NFLX", "PLTR", "COIN", "SOFI",
    "SMCI", "AVGO", "MU", "INTC", "ARM", "RIVN", "HOOD"
]

MANUAL_WATCHLIST = [
    "AAPL",
    "AMD",
    "NVDA",
    "TSLA",
    "MSFT",
    "META",
    "AMZN",
    "GOOGL"]

MAX_RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS_PERCENT = 0.02
MAX_OPEN_TRADES = 5
MAX_TRADES_PER_DAY = 10
ENABLE_BREAKOUT = True
ENABLE_PULLBACK = True
MAX_TRADES_BREAKOUT = 2
MAX_TRADES_PULLBACK = 1
MAX_RISK_PER_TRADE_BREAKOUT = 0.01
MAX_RISK_PER_TRADE_PULLBACK = 0.005

MIN_STOCK_PRICE = 10
MAX_STOCK_PRICE = 750
MIN_AVG_VOLUME = 250_000
MAX_DOLLARS_PER_TRADE = float(os.getenv("MAX_DOLLARS_PER_TRADE", "100"))
MIN_RELATIVE_VOLUME = 1.2
MIN_DAILY_GAIN_PERCENT = 0.005
MIN_DOLLAR_VOLUME = 50_000_000
EXCLUDE_SYMBOLS = ["NAT", "SQQQ", "TQQQ", "UVXY", "VXX"]
MIN_BREAKOUT_REL_VOLUME = 1.1
MAX_EXTENSION_FROM_SMA20 = 0.10
MAX_PULLBACK_DEPTH = 0.05
MIN_PULLBACK_RECOVERY_VOLUME = 0.8
MIN_PULLBACK_REL_VOLUME = 1.0

USE_TRAILING_STOP = False

TAKE_PROFIT_R_MULTIPLE = 2.0
STOP_BUFFER_PERCENT = 0.01
CLOSE_POSITIONS_AFTER = time(15, 30)
CLOSE_POSITIONS_CUTOFF = time(15, 55)

TRAILING_STOP_PERCENT = 3.0


LOG_FILE = "trade_log.csv"

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER_TRADING)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# ==============================
# Dashboard Database Logging
# ==============================

import json
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
db_engine = None

if DATABASE_URL:
    try:
        # pool_pre_ping checks out each pooled connection before use, so a
        # connection the Postgres server already closed (seen as
        # "SSL SYSCALL error: EOF detected") is transparently replaced
        # instead of failing the query.
        db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    except Exception as e:
        print(f"Database engine setup failed: {e}", flush=True)
        db_engine = None

print(f"DATABASE_URL loaded: {'YES' if DATABASE_URL else 'NO'}", flush=True)
print(f"Database engine ready: {'YES' if db_engine else 'NO'}", flush=True)


def log_db_event(
    event_type,
    symbol=None,
    side=None,
    strategy=None,
    model=None,
    status=None,
    qty=None,
    entry=None,
    stop_loss=None,
    take_profit=None,
    order_id=None,
    message=None,
    raw_payload=None,
):
    if db_engine is None:
        print("Database log skipped: db_engine is None", flush=True)
        return

    try:
        payload_text = None
        if raw_payload is not None:
            payload_text = json.dumps(raw_payload)

        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO bot_events (
                        bot_name,
                        event_type,
                        symbol,
                        side,
                        strategy,
                        model,
                        status,
                        qty,
                        entry,
                        stop_loss,
                        take_profit,
                        order_id,
                        message,
                        raw_payload
                    )
                    VALUES (
                        :bot_name,
                        :event_type,
                        :symbol,
                        :side,
                        :strategy,
                        :model,
                        :status,
                        :qty,
                        :entry,
                        :stop_loss,
                        :take_profit,
                        :order_id,
                        :message,
                        :raw_payload
                    )
                """),
                {
                    "bot_name": "Alpaca Direct Bot - Auto Scanner",
                    "event_type": event_type,
                    "symbol": symbol,
                    "side": side,
                    "strategy": strategy,
                    "model": model,
                    "status": status,
                    "qty": qty,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "order_id": order_id,
                    "message": message,
                    "raw_payload": payload_text,
                },
            )
    except Exception as e:
        print(f"Database log failed: {e}", flush=True)


def log_event(
    symbol,
    decision,
    reason,
    entry=None,
    stop=None,
    target=None,
    qty=None,
    model=None):
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "timestamp", "symbol", "decision", "reason",
                "entry", "stop", "target", "qty", "model"
            ])

        writer.writerow([
            datetime.now().isoformat(),
            symbol,
            decision,
            reason,
            entry,
            stop,
            target,
            qty,
            model
        ])


def market_is_open():
    clock = trading_client.get_clock()
    return clock.is_open


def trading_time_window_check():
    now = datetime.now(ZoneInfo("America/New_York")).time()

    trading_start = time(9, 45)
    trading_end = time(15, 30)

    if trading_start <= now <= trading_end:
        return True, "Trading window approved"

    return False, "Outside approved trading time window"


def daily_loss_check():
    account = trading_client.get_account()

    equity = float(account.equity)
    last_equity = float(account.last_equity)

    daily_change_percent = (equity - last_equity) / last_equity

    if daily_change_percent <= -MAX_DAILY_LOSS_PERCENT:
        return False, f"Daily loss limit hit: {daily_change_percent:.2%}"

    return True, f"Daily loss check passed: {daily_change_percent:.2%}"


def get_account_equity():
    account = trading_client.get_account()
    return float(account.equity)


def get_open_positions_count():
    positions = trading_client.get_all_positions()
    return len(positions)


def get_daily_bars(symbol, days=60):
    end = datetime.now(ZoneInfo("America/New_York"))
    start = end - timedelta(days=days)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed="iex"
    )

    bars = data_client.get_stock_bars(request).df

    if bars.empty:
        return pd.DataFrame()

    if isinstance(bars.index, pd.MultiIndex):
        try:
            bars = bars.xs(symbol)
        except KeyError:
            return pd.DataFrame()

    return bars


def spy_market_filter():
    bars = get_daily_bars("SPY", days=120)

    if len(bars) < 20:
        return False, f"Not enough SPY data. Only got {len(bars)} bars"

    spy_close = float(bars.iloc[-1]["close"])
    spy_sma_20 = bars["close"].tail(20).mean()

    if spy_close < spy_sma_20:
        return False, "SPY below 20-day moving average"

    return True, "SPY market filter approved"


def already_in_position(symbol):
    try:
        positions = trading_client.get_all_positions()

        for pos in positions:
            if pos.symbol == symbol:
                return True, "Already holding position"

        orders = trading_client.get_orders()

        for order in orders:
            if order.symbol == symbol:
                return True, "Open order already exists"

        return False, "No existing position"

    except Exception as e:
        return True, f"Position check error: {e}"

def get_tradable_symbols():
    assets = trading_client.get_all_assets()
    symbols = []

    allowed_exchanges = ["NASDAQ", "NYSE", "ARCA", "AMEX"]

    for asset in assets:
        if not asset.tradable:
            continue

        if asset.asset_class != "us_equity":
            continue

        if asset.exchange not in allowed_exchanges:
            continue

        if "." in asset.symbol or "/" in asset.symbol or "-" in asset.symbol:
            continue

        if asset.symbol in EXCLUDE_SYMBOLS:
            continue

        symbols.append(asset.symbol)

    available = set(symbols)
    preferred = [s for s in PREFERRED_SCANNER_SYMBOLS if s in available]
    remaining = sorted(s for s in symbols if s not in preferred)
    return (preferred + remaining)[:MAX_SYMBOLS_TO_SCAN]


def get_daily_bars_batch(symbols, days=60):
    """Retrieve daily candles in batches instead of one API request per symbol."""
    if not symbols:
        return {}

    end = datetime.now(ZoneInfo("America/New_York"))
    start = end - timedelta(days=days)
    results = {}

    for offset in range(0, len(symbols), SCANNER_BATCH_SIZE):
        batch = symbols[offset:offset + SCANNER_BATCH_SIZE]
        request = StockBarsRequest(
            symbol_or_symbols=batch,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex"
        )
        bars = data_client.get_stock_bars(request).df
        if bars.empty:
            continue

        for symbol in batch:
            try:
                symbol_bars = bars.xs(symbol) if isinstance(bars.index, pd.MultiIndex) else bars
            except KeyError:
                continue
            if not symbol_bars.empty:
                results[symbol] = symbol_bars

    return results


def scan_stock_from_bars(symbol, bars):
    if bars is None or len(bars) < 25:
        return None

    today = bars.iloc[-1]
    yesterday = bars.iloc[-2]

    close = float(today["close"])
    prior_close = float(yesterday["close"])
    volume = float(today["volume"])
    avg_volume = float(bars["volume"].tail(20).mean())

    if close < MIN_STOCK_PRICE or close > MAX_STOCK_PRICE:
        return None

    if avg_volume < MIN_AVG_VOLUME:
        return None

    percent_change = (close - prior_close) / prior_close
    relative_volume = volume / avg_volume if avg_volume > 0 else 0
    score = (percent_change * 100) + relative_volume

    return {
        "symbol": symbol,
        "close": close,
        "percent_change": percent_change,
        "relative_volume": relative_volume,
        "score": score
    }


def build_auto_watchlist():
    started = sleep_time.perf_counter()
    print("Building auto watchlist...", flush=True)

    symbols = get_tradable_symbols()
    candidates = []
    scan_errors = 0

    try:
        all_bars = get_daily_bars_batch(symbols)
    except Exception as e:
        elapsed = round(sleep_time.perf_counter() - started, 2)
        message = f"Auto watchlist batch download failed after {elapsed}s: {e}"
        print(message, flush=True)
        log_db_event(
            event_type="SCAN_ERROR", status="ERROR", message=message,
            raw_payload={"symbols_requested": len(symbols), "seconds": elapsed}
        )
        return []

    for symbol in symbols:
        try:
            result = scan_stock_from_bars(symbol, all_bars.get(symbol))
            if result:
                candidates.append(result)
        except Exception as e:
            scan_errors += 1
            log_event(symbol, "SCAN_ERROR", str(e))

    candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
    selected = [item["symbol"] for item in candidates[:MAX_CANDIDATES_TO_TRADE]]
    elapsed = round(sleep_time.perf_counter() - started, 2)

    summary = {
        "symbols_scanned": len(symbols),
        "symbols_with_bars": len(all_bars),
        "candidates_found": len(candidates),
        "selected_symbols": selected,
        "scan_errors": scan_errors,
        "runtime_seconds": elapsed,
    }
    print(
        f"Auto watchlist selected: {selected} | scanned={len(symbols)} "
        f"candidates={len(candidates)} runtime={elapsed}s errors={scan_errors}",
        flush=True,
    )
    log_db_event(
        event_type="WATCHLIST_COMPLETE", status="COMPLETE",
        message=(
            f"Scanner checked {len(symbols)} symbols in {elapsed}s; "
            f"selected {len(selected)} candidates"
        ),
        raw_payload=summary,
    )

    for item in candidates[:MAX_CANDIDATES_TO_TRADE]:
        log_event(
            item["symbol"],
            "SCANNER_SELECTED",
            f"Score={item['score']:.2f}, Change={item['percent_change']:.2%}, RelVol={item['relative_volume']:.2f}"
        )

    return selected


def breakout_signal(symbol):
    bars = get_daily_bars(symbol, days=90)

    if len(bars) < 50:
        return None, "Not enough data"

    yesterday = bars.iloc[-2]
    today = bars.iloc[-1]

    avg_volume = bars["volume"].tail(20).mean()
    current_volume = float(today["volume"])
    current_price = float(today["close"])
    prior_high = float(yesterday["high"])

    sma_20 = bars["close"].tail(20).mean()
    sma_50 = bars["close"].tail(50).mean()

    relative_volume = current_volume / avg_volume if avg_volume > 0 else 0
    extension_from_sma20 = (current_price - sma_20) / sma_20

    if current_price < MIN_STOCK_PRICE:
        return None, "Price too low"

    if current_price > MAX_STOCK_PRICE:
        return None, "Price too high"

    if avg_volume < MIN_AVG_VOLUME:
        return None, "Volume too low"

    if current_price < sma_20 or current_price < sma_50:
        return None, "Not in uptrend"

    if relative_volume < MIN_BREAKOUT_REL_VOLUME:
        return None, "Breakout volume too weak"

    if extension_from_sma20 > MAX_EXTENSION_FROM_SMA20:
        return None, "Too extended from 20-day average"

    if current_price <= prior_high:
        return None, "No breakout"

    entry = round(current_price, 2)
    stop = round(entry - 1.50, 2)
    target = round(entry + 3.00, 2)

    risk_per_share = entry - stop

    if risk_per_share <= 0:
        return None, "Invalid risk setup"

    return {
        "symbol": symbol,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_per_share": risk_per_share,
        "strategy": "breakout_momentum_v1",
        "model": "direct_breakout_live_v1"
    }, "Valid tightened breakout"


def calculate_position_size(account_equity, risk_per_share):
    max_risk = account_equity * MAX_RISK_PER_TRADE
    qty = int(max_risk / risk_per_share)
    return max(qty, 0)


def pullback_signal(symbol):
    bars = get_daily_bars(symbol, days=90)

    if len(bars) < 50:
        return None, "Not enough data for pullback"

    today = bars.iloc[-1]
    yesterday = bars.iloc[-2]
    two_days_ago = bars.iloc[-3]

    close = float(today["close"])
    open_price = float(today["open"])
    yesterday_close = float(yesterday["close"])
    two_days_ago_close = float(two_days_ago["close"])

    avg_volume = bars["volume"].tail(20).mean()
    current_volume = float(today["volume"])
    relative_volume = current_volume / avg_volume if avg_volume > 0 else 0

    sma_20 = bars["close"].tail(20).mean()
    sma_50 = bars["close"].tail(50).mean()

    if close < MIN_STOCK_PRICE or close > MAX_STOCK_PRICE:
        return None, "Price outside range"

    if avg_volume < MIN_AVG_VOLUME:
        return None, "Volume too low"

    if close < sma_20 or close < sma_50:
        return None, "Not in uptrend"

    if sma_20 < sma_50:
        return None, "Trend not strong enough"

    pullback_depth = (two_days_ago_close - yesterday_close) / two_days_ago_close

    if pullback_depth <= 0:
        return None, "No pullback"

    if pullback_depth > MAX_PULLBACK_DEPTH:
        return None, "Pullback too deep"

    if close <= yesterday_close:
        return None, "No recovery"

    if close <= open_price:
        return None, "Recovery candle not green"

    if relative_volume < MIN_PULLBACK_RECOVERY_VOLUME:
        return None, "Recovery volume too weak"

    entry = round(close, 2)
    stop = round(entry - 1.50, 2)
    risk_per_share = entry - stop

    if risk_per_share <= 0:
        return None, "Invalid pullback risk"

    target = round(entry + risk_per_share * TAKE_PROFIT_R_MULTIPLE, 2)

    return {
        "symbol": symbol,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_per_share": risk_per_share,
        "strategy": "pullback_reclaim_v1",
        "model": "direct_pullback_live_v1"
    }, "Valid tightened pullback"

def risk_check(signal):
    equity = get_account_equity()
    open_positions = get_open_positions_count()

    if open_positions >= MAX_OPEN_TRADES:
        return False, "Too many open trades", 0

    entry_price = float(signal["entry"])
    risk_qty = int(calculate_position_size(equity, signal["risk_per_share"]))

    if risk_qty <= 0:
        return False, "Position size too small", 0

    equity_qty = int(equity / entry_price)
    max_dollar_qty = int(MAX_DOLLARS_PER_TRADE / entry_price)

    # Strategies 1/2 use protected exit orders (bracket or trailing stop).
    # Alpaca rejects fractional protected/bracket entries, so these strategies
    # intentionally submit whole-share quantities only.
    qty = min(risk_qty, equity_qty, max_dollar_qty)

    if qty < 1:
        return False, (
            f"Protected order requires at least 1 whole share; entry ${entry_price:.2f} "
            f"does not fit ${MAX_DOLLARS_PER_TRADE:.2f} trade cap"
        ), 0

    estimated_trade_value = round(qty * entry_price, 2)

    return True, (
        f"Risk approved - protected whole-share qty={qty}, "
        f"estimated value=${estimated_trade_value:.2f}, "
        f"max=${MAX_DOLLARS_PER_TRADE:.2f}"
    ), qty



def build_client_order_id(signal):
    """
    Add a short strategy tag to every new Alpaca entry order so the Coach T
    dashboard can separate Strategies 1 and 2 even though they share an account.
    """
    strategy_codes = {
        "breakout_momentum_v1": "s1_breakout",
        "pullback_reclaim_v1": "s2_pullback",
    }
    strategy_code = strategy_codes.get(signal.get("strategy", ""), "scanner")
    symbol = "".join(ch for ch in str(signal.get("symbol", "NA")).upper() if ch.isalnum())
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%y%m%d%H%M%S%f")
    return f"ct_{strategy_code}_{symbol}_{stamp}"

def place_trade(signal, qty):
    client_order_id = build_client_order_id(signal)

    if USE_TRAILING_STOP:
        from alpaca.trading.requests import TrailingStopOrderRequest

        order = TrailingStopOrderRequest(
            symbol=signal["symbol"],
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            trail_percent=TRAILING_STOP_PERCENT,
            client_order_id=client_order_id
        )

        submitted_order = trading_client.submit_order(order)

        log_trade_event(
            bot_group="DIRECT_SCANNER",
            strategy=signal.get("strategy", "unknown_strategy"),
            model=signal.get("model", "direct_scanner_live_v1"),
            symbol=signal["symbol"],
            side="buy",
            qty=qty,
            entry_price=signal.get("entry", ""),
            stop_loss="",
            take_profit="",
            status="ORDER_SUBMITTED",
            order_id=getattr(submitted_order, "id", ""),
            raw_payload={**signal, "client_order_id": client_order_id},
        )

        return submitted_order

    order = MarketOrderRequest(
        symbol=signal["symbol"],
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=signal["target"]),
        stop_loss=StopLossRequest(stop_price=signal["stop"])
    )

    submitted_order = trading_client.submit_order(order)

    log_trade_event(
        bot_group="DIRECT_SCANNER",
        strategy=signal.get("strategy", "unknown_strategy"),
        model=signal.get("model", "direct_scanner_live_v1"),
        symbol=signal["symbol"],
        side="buy",
        qty=qty,
        entry_price=signal.get("entry", ""),
        stop_loss=signal.get("stop", ""),
        take_profit=signal.get("target", ""),
        status="ORDER_SUBMITTED",
        order_id=getattr(submitted_order, "id", ""),
        raw_payload={**signal, "client_order_id": client_order_id},
    )

    return submitted_order


def trades_placed_today():
    # Count from the bot_events Postgres table rather than the local CSV,
    # which is wiped whenever Railway restarts the container.
    if db_engine is None:
        print("trades_placed_today: db_engine is None, returning 0", flush=True)
        return 0

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM bot_events
                    WHERE date(created_at) = current_date
                      AND status = 'ACCEPTED'
                      AND bot_name = :bot_name
                """),
                {"bot_name": "Alpaca Direct Bot - Auto Scanner"},
            )
            return result.scalar() or 0
    except Exception as e:
        print(f"trades_placed_today query failed: {e}", flush=True)
        return 0


def print_account_status():
    try:
        account = trading_client.get_account()

        equity = float(account.equity)
        last_equity = float(account.last_equity)
        cash = float(account.cash)

        daily_pl = equity - last_equity
        daily_pl_percent = (daily_pl / last_equity) * 100

        positions = trading_client.get_all_positions()

        print("\n===== ACCOUNT STATUS =====")
        print(f"Equity: ${equity:,.2f}")
        print(f"Cash: ${cash:,.2f}")
        print(f"Daily P/L: ${daily_pl:,.2f} ({daily_pl_percent:.2f}%)")
        print(f"Open Positions: {len(positions)}")
        print("==========================\n")

    except Exception as e:
        print(f"Account status error: {e}")


def close_positions_near_market_close():
    now = datetime.now(ZoneInfo("America/New_York")).time()

    if now < CLOSE_POSITIONS_AFTER:
        return False, "Not time to close positions yet"

    if now > CLOSE_POSITIONS_CUTOFF:
        return True, "Past EOD closeout cutoff — no new close orders submitted"

    positions = trading_client.get_all_positions()

    if not positions:
        return True, "No open positions to close"

    try:
        trading_client.cancel_orders()
        print("Canceled open orders before EOD closeout")
        log_event(
            "ACCOUNT",
            "CANCEL_ORDERS",
            "Canceled open orders before EOD closeout")
    except Exception as e:
        print(f"Cancel orders error: {e}")
        log_event("ACCOUNT", "CANCEL_ERROR", str(e))

    import time as sleep_time
    sleep_time.sleep(5)

    for position in positions:
        try:
            trading_client.close_position(position.symbol)
            print(f"{position.symbol}: CLOSE ORDER SENT before market close")
            log_event(
                position.symbol,
                "CLOSE_SENT_EOD",
                "Close order sent before market close")
        except Exception as e:
            print(f"{position.symbol}: CLOSE ERROR - {e}")
            log_event(position.symbol, "CLOSE_ERROR", str(e))

    return True, "End-of-day closeout attempted"


def trades_today_by_model(model_name):
    if not os.path.isfile(LOG_FILE):
        return 0

    df = pd.read_csv(LOG_FILE)

    today = datetime.now(ZoneInfo("America/New_York")).date()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df_today = df[df["timestamp"].dt.date == today]

    return len(df_today[(df_today["decision"] == "TRADE_PLACED") & (
        df_today["model"] == model_name)])


def run_bot():
    print("Starting Alpaca paper trading bot...")
    print_account_status()

    close_done, close_reason = close_positions_near_market_close()

    if close_done:
        print(close_reason)
        return

    if not PAPER_TRADING:
        raise RuntimeError("Live trading is disabled. Paper trading only.")

    if not market_is_open():
        print("Market is closed")
        return

    time_ok, time_reason = trading_time_window_check()

    if not time_ok:
        print(time_reason)
        log_event("TIME", "TIME_BLOCKED", time_reason)
        return

    print(time_reason)

    loss_ok, loss_reason = daily_loss_check()

    if not loss_ok:
        print(loss_reason)
        log_event("ACCOUNT", "DAILY_LOSS_BLOCKED", loss_reason)
        return

    print(loss_reason)

    market_ok, market_reason = spy_market_filter()

    if not market_ok:
        print(f"Market filter blocked trading: {market_reason}")
        log_event("SPY", "MARKET_BLOCKED", market_reason)
        return

    print(f"Market filter passed: {market_reason}")

    trades_today = trades_placed_today()

    if trades_today >= MAX_TRADES_PER_DAY:
        reason = f"Max trades per day reached: {trades_today}/{MAX_TRADES_PER_DAY}"
        print(reason)
        log_event("ACCOUNT", "MAX_TRADES_BLOCKED", reason)
        return

    print(f"Trades placed today: {trades_today}/{MAX_TRADES_PER_DAY}")

    symbols_to_check = build_auto_watchlist() if USE_AUTO_SCANNER else MANUAL_WATCHLIST

    if not symbols_to_check:
        print("No symbols passed scanner.")
        return

    cycle_stats = {
        "symbols_selected": len(symbols_to_check),
        "signals_found": 0,
        "orders_attempted": 0,
        "orders_submitted": 0,
        "orders_rejected": 0,
        "skipped": 0,
        "blocked": 0,
    }

    for symbol in symbols_to_check:
        in_position, position_reason = already_in_position(symbol)

        if in_position:
            cycle_stats["blocked"] += 1
            print(f"{symbol}: BLOCKED - {position_reason}")
            log_event(symbol, "BLOCKED", position_reason)
            continue

        signal = None
        reason = ""

        # Breakout first
        if ENABLE_BREAKOUT:
            signal, reason = breakout_signal(symbol)
            if signal is not None:
                signal["model"] = signal.get("model", "direct_breakout_live_v1")

        # Pullback second
        if signal is None and ENABLE_PULLBACK:
            pb_signal, pb_reason = pullback_signal(symbol)
            if pb_signal is not None:
                signal = pb_signal
                signal["model"] = signal.get("model", "direct_pullback_live_v1")
            else:
                reason = pb_reason

        if signal is None:
            cycle_stats["skipped"] += 1
            print(f"{symbol}: SKIPPED - {reason}")
            log_event(symbol, "SKIPPED", reason)
            continue

        cycle_stats["signals_found"] += 1

        # Risk check
        approved, risk_reason, qty = risk_check(signal)

        if not approved:
            cycle_stats["blocked"] += 1
            print(f"{symbol}: BLOCKED - {risk_reason}")
            log_event(symbol, "BLOCKED", risk_reason)
            log_db_event(
                event_type="SIGNAL_BLOCKED", symbol=symbol,
                strategy=signal.get("strategy"), model=signal.get("model"),
                status="BLOCKED", message=risk_reason, raw_payload=signal
            )
            continue

        cycle_stats["orders_attempted"] += 1
        try:
            submitted_order = place_trade(signal, qty)
            cycle_stats["orders_submitted"] += 1
            estimated_value = round(qty * signal["entry"], 2)
            print(f"{symbol}: TRADE PLACED qty={qty} estimated_value=${estimated_value:.2f}")

            log_event(
                symbol,
                "TRADE_PLACED",
                f"{signal.get('model', 'unknown')} trade",
                signal["entry"],
                signal["stop"],
                signal["target"],
                qty,
                signal.get("model", "unknown")
            )
            log_db_event(
                event_type="ORDER_SUBMITTED", symbol=symbol, side="buy",
                strategy=signal.get("strategy"), model=signal.get("model"),
                status="SUBMITTED", qty=qty, entry=signal.get("entry"),
                stop_loss=signal.get("stop"), take_profit=signal.get("target"),
                order_id=str(getattr(submitted_order, "id", "")),
                message=f"Protected paper order submitted: qty={qty}",
                raw_payload=signal
            )
            # Separate ACCEPTED event so trades_placed_today() can count from
            # bot_events consistently with the alligator/tradingview bots,
            # while leaving the ORDER_SUBMITTED/SUBMITTED row that the
            # dashboards (e.g. trading-dashboard /api/positions) depend on.
            log_db_event(
                event_type="TRADE_PLACED", symbol=symbol, side="buy",
                strategy=signal.get("strategy"), model=signal.get("model"),
                status="ACCEPTED", qty=qty, entry=signal.get("entry"),
                stop_loss=signal.get("stop"), take_profit=signal.get("target"),
                order_id=str(getattr(submitted_order, "id", "")),
                message=f"Protected paper order accepted: qty={qty}",
                raw_payload=signal
            )

        except Exception as e:
            cycle_stats["orders_rejected"] += 1
            print(f"{symbol}: ERROR - {e}")
            log_event(symbol, "ERROR", str(e))
            log_db_event(
                event_type="ORDER_REJECTED", symbol=symbol, side="buy",
                strategy=signal.get("strategy"), model=signal.get("model"),
                status="ERROR", qty=qty, entry=signal.get("entry"),
                stop_loss=signal.get("stop"), take_profit=signal.get("target"),
                message=str(e), raw_payload=signal
            )

    diagnostic_message = (
        f"Candidates={cycle_stats['symbols_selected']}; "
        f"signals={cycle_stats['signals_found']}; "
        f"attempted={cycle_stats['orders_attempted']}; "
        f"submitted={cycle_stats['orders_submitted']}; "
        f"rejected={cycle_stats['orders_rejected']}; "
        f"blocked={cycle_stats['blocked']}; skipped={cycle_stats['skipped']}"
    )
    print(f"Cycle diagnostics: {diagnostic_message}", flush=True)
    log_db_event(
        event_type="CYCLE_DIAGNOSTICS", status="COMPLETE",
        message=diagnostic_message, raw_payload=cycle_stats
    )


if __name__ == "__main__":
    log_db_event(
        event_type="BOT_STARTED",
        status="STARTED",
        message="Alpaca Direct Bot started on Railway/local runtime",
    )

    while True:
        try:
            if market_is_open():
                print("Market is open — running bot\n")

                log_db_event(
                    event_type="HEARTBEAT",
                    status="MARKET_OPEN",
                    message="Market is open — running Alpaca Direct scanner",
                )

                run_bot()

                log_db_event(
                    event_type="SCAN_COMPLETE",
                    status="COMPLETE",
                    message="Alpaca Direct scanner cycle completed",
                )

                sleep_time.sleep(300)

            else:
                print("Market is closed — sleeping 10 minutes\n")

                log_db_event(
                    event_type="HEARTBEAT",
                    status="MARKET_CLOSED",
                    message="Market is closed — sleeping 10 minutes",
                )

                sleep_time.sleep(600)

        except Exception as e:
            print(f"MAIN LOOP ERROR - {e}")

            log_db_event(
                event_type="ERROR",
                status="ERROR",
                message=f"Main loop error: {e}",
            )

            sleep_time.sleep(300)
