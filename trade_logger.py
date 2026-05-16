import os
import csv
from datetime import datetime
from zoneinfo import ZoneInfo

LOG_FILE = "unified_trade_log.csv"

FIELDNAMES = [
    "timestamp_et",
    "date_et",
    "bot_group",
    "strategy",
    "model",
    "environment",
    "symbol",
    "side",
    "qty",
    "entry_price",
    "exit_price",
    "stop_loss",
    "take_profit",
    "pnl_dollars",
    "pnl_r",
    "status",
    "reason",
    "order_id",
    "parent_order_id",
    "raw_payload",
]


def now_et():
    return datetime.now(ZoneInfo("America/New_York"))


def log_trade_event(
    bot_group,
    strategy,
    model,
    symbol="",
    side="",
    qty="",
    entry_price="",
    exit_price="",
    stop_loss="",
    take_profit="",
    pnl_dollars="",
    pnl_r="",
    status="",
    reason="",
    order_id="",
    parent_order_id="",
    raw_payload="",
    environment="paper",
):
    ts = now_et()

    row = {
        "timestamp_et": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "date_et": ts.strftime("%Y-%m-%d"),
        "bot_group": bot_group,
        "strategy": strategy,
        "model": model,
        "environment": environment,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "pnl_dollars": pnl_dollars,
        "pnl_r": pnl_r,
        "status": status,
        "reason": reason,
        "order_id": order_id,
        "parent_order_id": parent_order_id,
        "raw_payload": str(raw_payload),
    }

    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)