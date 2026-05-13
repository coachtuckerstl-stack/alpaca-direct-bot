import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient


load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

LOG_FILE = "trade_log.csv"

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)

st.set_page_config(page_title="Alpaca Bot Dashboard", layout="wide")

st.title("Alpaca Trading Bot Dashboard")

# Account status
st.header("Account Status")

try:
    account = trading_client.get_account()
    positions = trading_client.get_all_positions()

    equity = float(account.equity)
    last_equity = float(account.last_equity)
    cash = float(account.cash)
    daily_pl = equity - last_equity
    daily_pl_pct = (daily_pl / last_equity) * 100 if last_equity else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Equity", f"${equity:,.2f}")
    col2.metric("Cash", f"${cash:,.2f}")
    col3.metric("Daily P/L", f"${daily_pl:,.2f}", f"{daily_pl_pct:.2f}%")
    col4.metric("Open Positions", len(positions))

except Exception as e:
    st.error(f"Could not load Alpaca account: {e}")

# Open positions
st.header("Open Positions")

try:
    position_rows = []

    for p in positions:
        position_rows.append({
            "Symbol": p.symbol,
            "Qty": p.qty,
            "Market Value": p.market_value,
            "Avg Entry": p.avg_entry_price,
            "Current Price": p.current_price,
            "Unrealized P/L": p.unrealized_pl,
            "Unrealized P/L %": p.unrealized_plpc,
        })

    if position_rows:
        st.dataframe(pd.DataFrame(position_rows), use_container_width=True)
    else:
        st.info("No open positions.")

except Exception as e:
    st.error(f"Could not load positions: {e}")

# Trade log
st.header("Bot Trade Log")

if os.path.isfile(LOG_FILE):
    df = pd.read_csv(LOG_FILE)

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.sort_values("timestamp", ascending=False)

        today = pd.Timestamp.now().date()
        df_today = df[df["timestamp"].dt.date == today]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Trades Today", len(df_today[df_today["decision"] == "TRADE_PLACED"]))
        col2.metric("Skipped Today", len(df_today[df_today["decision"] == "SKIPPED"]))
        col3.metric("Blocked Today", len(df_today[df_today["decision"].str.contains("BLOCKED", na=False)]))
        col4.metric("Errors Today", len(df_today[df_today["decision"] == "ERROR"]))

        st.subheader("Today")
        st.dataframe(df_today, use_container_width=True)

        st.subheader("Recent Activity")
        st.dataframe(df.head(100), use_container_width=True)

    else:
        st.info("Trade log is empty.")
else:
    st.warning("No trade_log.csv found yet. Run bot.py first.")

st.header("Strategy Trade Stats")

if os.path.isfile(LOG_FILE):
    df = pd.read_csv(LOG_FILE)

    if "model" in df.columns:
        trades = df[df["decision"] == "TRADE_PLACED"]

        if not trades.empty:
            strategy_stats = trades.groupby("model").agg(
                total_trades=("symbol", "count"),
                avg_entry=("entry", "mean"),
                avg_qty=("qty", "mean")
            ).reset_index()

            st.dataframe(strategy_stats, use_container_width=True)
        else:
            st.info("No strategy trades logged yet.")
    else:
        st.warning("No model column found yet. New trades will include strategy names.")

st.header("Strategy Trade Stats")

if os.path.isfile(LOG_FILE):
    df = pd.read_csv(LOG_FILE)

    if "model" in df.columns:
        trades = df[df["decision"] == "TRADE_PLACED"]

        if not trades.empty:
            strategy_stats = trades.groupby("model").agg(
                total_trades=("symbol", "count"),
                avg_entry=("entry", "mean"),
                avg_qty=("qty", "mean")
            ).reset_index()

            st.dataframe(strategy_stats, use_container_width=True)
        else:
            st.info("No strategy trades logged yet.")
    else:
        st.warning("No model column found yet. New trades will include strategy names.")