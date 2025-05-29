#!/usr/bin/env python3
"""Fetch stock prices for processed director filings.

Failed downloads are recorded in ``stock_price_failures`` so they aren't
retried on subsequent runs.  Using ``--force`` clears any existing
failure record and retries the download.
"""

import argparse
import logging

import pgconnect
from stock_price import fetch_stock_price


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch prices for processed DEF 14A filings")
    parser.add_argument("--database-config", default="db.conf",
                        help="Parameters to connect to the database")
    parser.add_argument("--stop-after", type=int,
                        help="Limit the number of prices fetched")
    parser.add_argument("--force", action="store_true",
                        help="Refetch price even if already stored")
    parser.add_argument("--dummy-run", action="store_true",
                        help="Don't store prices in the database")
    parser.add_argument("--progress", action="store_true",
                        help="Show a progress bar")
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    cur = conn.cursor()

    query = """
        SELECT DISTINCT f.filingDate, t.ticker
          FROM filings f
          JOIN director_compensation dc ON f.document_storage_url = dc.url
          JOIN cik_to_ticker t ON f.cikcode = t.cikcode
         WHERE f.form = 'DEF 14A' AND dc.processed = TRUE
         ORDER BY f.filingDate
    """
    cur.execute(query)
    rows = cur.fetchall()

    if args.progress:
        import tqdm
        iterator = tqdm.tqdm(rows)
    else:
        iterator = rows

    count = 0
    for filing_date, ticker in iterator:
        if args.force:
            cur.execute(
                "DELETE FROM stock_price_failures WHERE ticker=%s AND price_date=%s",
                (ticker, filing_date),
            )
        else:
            cur.execute(
                "SELECT 1 FROM stock_price_failures WHERE ticker=%s AND price_date=%s",
                (ticker, filing_date),
            )
            if cur.fetchone():
                continue

        try:
            fetch_stock_price(conn, ticker, filing_date,
                              force=args.force, dummy_run=args.dummy_run)
        except RuntimeError as exc:
            cur.execute(
                "INSERT INTO stock_price_failures (ticker, price_date, failure_msg)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (ticker, price_date) DO UPDATE"
                " SET failure_msg = EXCLUDED.failure_msg",
                (ticker, filing_date, str(exc)),
            )
            conn.commit()
            logging.error("Failed to fetch %s on %s: %s", ticker, filing_date, exc)
        else:
            conn.commit()
            count += 1
            if args.stop_after and count >= args.stop_after:
                break


if __name__ == "__main__":
    main()
