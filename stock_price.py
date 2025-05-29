#!/usr/bin/env python3
"""Fetch and store closing stock prices."""

import argparse
from datetime import datetime, timedelta, date as date_cls
import pgconnect
import yfinance as yf


def fetch_stock_price(conn, ticker: str, price_date, *, force: bool = False,
                       schema_file: str = "stock_price_schema.sql",
                       dummy_run: bool = False) -> float:
    """Fetch the closing price for ``ticker`` on ``price_date``.

    If ``dummy_run`` is False the value is stored in the ``stock_prices`` table.
    When ``force`` is False an existing value in the table is returned without
    contacting the network.
    """

    cur = conn.cursor()

    if isinstance(price_date, str):
        price_date = datetime.strptime(price_date, "%Y-%m-%d").date()
    elif isinstance(price_date, datetime):
        price_date = price_date.date()
    elif not isinstance(price_date, date_cls):
        raise TypeError("price_date must be a date or YYYY-MM-DD string")

    ticker = ticker.upper()

    if not force:
        cur.execute(
            "SELECT close_price FROM stock_prices WHERE ticker=%s AND price_date=%s",
            (ticker, price_date),
        )
        row = cur.fetchone()
        if row is not None:
            return float(row[0])

    start = price_date
    end = price_date + timedelta(days=1)
    data = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
    )
    if data.empty:
        raise RuntimeError("No data returned for the given ticker and date")
    # ``yf.download`` may return a DataFrame with a MultiIndex in some
    # situations.  Using ``iloc`` ensures we correctly pick the first row
    # regardless of whether ``data["Close"]`` yields a Series or a DataFrame.
    close_price = float(data["Close"].iloc[0])

    if not dummy_run:
        if force:
            cur.execute(
                "INSERT INTO stock_prices (ticker, price_date, close_price)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (ticker, price_date) DO UPDATE"
                " SET close_price = EXCLUDED.close_price",
                (ticker, price_date, close_price),
            )
        else:
            cur.execute(
                "INSERT INTO stock_prices (ticker, price_date, close_price)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (ticker, price_date, close_price),
            )
        conn.commit()

    return close_price


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch closing stock price for a given ticker and date")
    parser.add_argument("ticker", help="Stock ticker symbol, e.g. AAPL")
    parser.add_argument("date", help="Date in YYYY-MM-DD format")
    parser.add_argument("--database-config", default="db.conf",
                        help="Parameters to connect to the database")
    parser.add_argument("--schema-file", default="stock_price_schema.sql",
                        help="SQL schema file for the stock_prices table")
    parser.add_argument("--force", action="store_true",
                        help="Refetch price even if already stored")
    parser.add_argument("--dummy-run", action="store_true",
                        help="Don't store the result in the database")
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    price = fetch_stock_price(conn, args.ticker, args.date,
                              force=args.force,
                              schema_file=args.schema_file,
                              dummy_run=args.dummy_run)
    print(f"{args.ticker.upper()} {args.date} close price: {price}")


if __name__ == "__main__":
    main()
