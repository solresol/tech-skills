#!/usr/bin/env python3
"""Fetch and store the industry sector for a stock ticker."""

import argparse

import pgconnect
import yfinance as yf


def fetch_sector(conn, ticker: str, *, force: bool = False,
                 dummy_run: bool = False) -> str:
    """Fetch the sector for ``ticker`` and store it in the ``ticker_sector`` table.

    When ``force`` is False an existing value is returned without contacting the
    network.
    """

    ticker = ticker.upper()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ticker_sector ("
        " ticker TEXT PRIMARY KEY,"
        " sector TEXT"
        ")"
    )
    conn.commit()
    if not force:
        cur.execute(
            "SELECT sector FROM ticker_sector WHERE ticker=%s",
            (ticker,),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]

    info = yf.Ticker(ticker).info
    sector = info.get("sector")
    if not sector:
        raise RuntimeError("Sector information unavailable")

    if not dummy_run:
        cur.execute(
            "INSERT INTO ticker_sector (ticker, sector) VALUES (%s, %s) "
            "ON CONFLICT (ticker) DO UPDATE SET sector = EXCLUDED.sector",
            (ticker, sector),
        )
        conn.commit()

    return sector


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and store the sector for a stock ticker",
    )
    parser.add_argument("ticker", help="Stock ticker symbol, e.g. AAPL")
    parser.add_argument("--database-config", default="db.conf",
                        help="Parameters to connect to the database")
    parser.add_argument("--force", action="store_true",
                        help="Refetch sector even if already stored")
    parser.add_argument("--dummy-run", action="store_true",
                        help="Don't store the result in the database")
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    sector = fetch_sector(
        conn,
        args.ticker,
        force=args.force,
        dummy_run=args.dummy_run,
    )
    print(f"{args.ticker.upper()} sector: {sector}")


if __name__ == "__main__":
    main()
