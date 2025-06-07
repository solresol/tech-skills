#!/usr/bin/env python3
"""Fetch sector information for all tickers in the database."""

import argparse
import logging
from typing import Iterable

import pgconnect

from fetch_sector import fetch_sector


def iter_tickers(cur, *, force: bool) -> Iterable[str]:
    """Yield tickers needing sector information."""
    if force:
        query = "SELECT DISTINCT ticker FROM cik_to_ticker ORDER BY ticker"
        cur.execute(query)
    else:
        query = (
            "SELECT DISTINCT c.ticker FROM cik_to_ticker c "
            "LEFT JOIN ticker_sector s ON c.ticker = s.ticker "
            "WHERE s.ticker IS NULL ORDER BY c.ticker"
        )
        cur.execute(query)
    for (ticker,) in cur.fetchall():
        yield ticker


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch sectors for all tickers")
    parser.add_argument("--database-config", default="db.conf",
                        help="Parameters to connect to the database")
    parser.add_argument("--schema-file", default="schema.sql",
                        help="SQL schema file to ensure tables exist")
    parser.add_argument("--stop-after", type=int,
                        help="Limit number of tickers processed")
    parser.add_argument("--progress", action="store_true",
                        help="Show a progress bar")
    parser.add_argument("--force", action="store_true",
                        help="Refetch sector even if already stored")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    conn = pgconnect.connect(args.database_config)
    cur = conn.cursor()

    tickers = list(iter_tickers(cur, force=args.force))

    if args.progress:
        import tqdm

        iterator = tqdm.tqdm(tickers)
    else:
        iterator = tickers

    count = 0
    for ticker in iterator:
        if args.stop_after and count >= args.stop_after:
            break
        try:
            fetch_sector(
                conn,
                ticker,
                force=args.force,
                schema_file=args.schema_file,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to fetch sector for %s: %s", ticker, exc)
        else:
            count += 1

    conn.close()


if __name__ == "__main__":
    main()
