#!/usr/bin/env python3

"""Fetch and store closing stock prices.

This script retrieves the closing price for a given ticker and date using
`yfinance`, stores it in a PostgreSQL table and prints the result. If the
record already exists in the database, it is returned without calling
`yfinance`.
"""

import argparse
from datetime import datetime, timedelta
import pgconnect
import yfinance as yf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch closing stock price for a given ticker and date")
    parser.add_argument("ticker", help="Stock ticker symbol, e.g. AAPL")
    parser.add_argument("date", help="Date in YYYY-MM-DD format")
    parser.add_argument(
        "--database-config",
        default="db.conf",
        help="Parameters to connect to the database")
    parser.add_argument(
        "--schema-file",
        default="stock_price_schema.sql",
        help="SQL schema file for the stock_prices table")
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    cur = conn.cursor()

    # Ensure the schema exists
    with open(args.schema_file, "r") as f:
        cur.execute(f.read())
    conn.commit()

    price_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    ticker = args.ticker.upper()

    cur.execute(
        "SELECT close_price FROM stock_prices WHERE ticker=%s AND price_date=%s",
        (ticker, price_date),
    )
    row = cur.fetchone()
    if row is not None:
        print(f"{ticker} {price_date} close price: {row[0]}")
        return

    # Fetch from yfinance. The end date is exclusive so we add one day.
    start = price_date
    end = price_date + timedelta(days=1)
    data = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
    )
    if data.empty:
        raise SystemExit("No data returned for the given ticker and date")
    close_price = float(data["Close"].iloc[0])

    cur.execute(
        "INSERT INTO stock_prices (ticker, price_date, close_price)"
        " VALUES (%s, %s, %s)",
        (ticker, price_date, close_price),
    )
    conn.commit()

    print(f"{ticker} {price_date} close price: {close_price}")


if __name__ == "__main__":
    main()
