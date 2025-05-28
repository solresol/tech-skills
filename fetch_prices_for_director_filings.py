#!/usr/bin/env python3
"""Fetch stock prices for processed director filings."""

import argparse
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
        fetch_stock_price(conn, ticker, filing_date,
                          force=args.force, dummy_run=args.dummy_run)
        count += 1
        if args.stop_after and count >= args.stop_after:
            break


if __name__ == "__main__":
    main()
