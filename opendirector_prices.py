#!/usr/bin/env python3
"""Collect source-labelled ASX daily prices for the OpenDirector tracker.

The initial provider is Yahoo Finance via yfinance, which is appropriate for
the local research pilot but is not a licensed ASX redistribution feed. The
database model keeps provider provenance so licensed data can later coexist
with or replace these observations.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
import requests
import yfinance as yf
from psycopg2.extras import Json, execute_values

from opendirector_ingest import apply_schema, connect


PROVIDER = "yahoo"
PRICE_SOURCE = "yahoo_via_yfinance"
DEFAULT_SCHEMA = "opendirector_schema.sql"
DEFAULT_SEED = "opendirector_asx_seed.json"
ASX_DIRECTORY_URL = (
    "https://asx.api.markitdigital.com/asx-research/1.0/"
    "companies/directory/file"
)


@dataclass(frozen=True)
class Security:
    id: int
    exchange_code: str
    issuer_name: str
    provider_symbol: str
    currency: str


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def load_seed(filename: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("ASX seed must be a JSON array")
    seen_symbols: set[str] = set()
    seen_aliases: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("each ASX seed entry must be an object")
        required = {"exchange_code", "issuer_name", "provider_symbol", "aliases"}
        missing = sorted(required - set(entry))
        if missing:
            raise ValueError(f"ASX seed entry is missing {', '.join(missing)}")
        symbol = str(entry["provider_symbol"]).upper()
        if symbol in seen_symbols:
            raise ValueError(f"duplicate provider symbol in ASX seed: {symbol}")
        seen_symbols.add(symbol)
        aliases = entry["aliases"]
        if not isinstance(aliases, list) or not aliases:
            raise ValueError(f"{symbol} must have at least one organization alias")
        for alias in aliases:
            normalized = str(alias).strip().casefold()
            if not normalized:
                raise ValueError(f"{symbol} contains an empty organization alias")
            if normalized in seen_aliases:
                raise ValueError(f"duplicate organization alias in ASX seed: {alias}")
            seen_aliases.add(normalized)
    return payload


def parse_asx_directory_csv(content: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(content)):
        exchange_code = (row.get("ASX code") or "").strip().upper()
        issuer_name = (row.get("Company name") or "").strip()
        listing_date_text = (row.get("Listing date") or "").strip()
        if not exchange_code or not issuer_name or not listing_date_text:
            continue
        listing_date = datetime.strptime(listing_date_text, "%d/%m/%Y").date()
        market_cap_text = (
            (row.get("Market Cap") or "").strip().replace(",", "")
        )
        market_cap = (
            int(market_cap_text)
            if market_cap_text and market_cap_text not in {"-", "--"}
            else None
        )
        entries.append(
            {
                "exchange_code": exchange_code,
                "issuer_name": issuer_name,
                "provider_symbol": f"{exchange_code}.AX",
                "industry_group": (
                    row.get("GICs industry group") or ""
                ).strip()
                or None,
                "listing_date": listing_date,
                "market_cap": market_cap,
            }
        )
    if not entries:
        raise ValueError("ASX directory returned no usable companies")
    return entries


def fetch_asx_directory() -> list[dict[str, Any]]:
    response = requests.get(ASX_DIRECTORY_URL, timeout=60)
    response.raise_for_status()
    return parse_asx_directory_csv(response.text)


def sync_asx_directory(
    conn, entries: Sequence[dict[str, Any]], retrieved_at: datetime
) -> int:
    updated = 0
    with conn.cursor() as cursor:
        for entry in entries:
            cursor.execute(
                """
                SELECT id
                FROM opendirector.market_securities
                WHERE provider = %s
                  AND provider_symbol = %s
                  AND valid_to IS NULL
                """,
                (PROVIDER, entry["provider_symbol"]),
            )
            existing = cursor.fetchone()
            metadata = Json(
                {
                    "asx_directory_url": ASX_DIRECTORY_URL,
                    "asx_directory_retrieved_at": retrieved_at.isoformat(),
                    "industry_group": entry["industry_group"],
                    "market_cap": entry["market_cap"],
                }
            )
            if existing:
                cursor.execute(
                    """
                    UPDATE opendirector.market_securities
                    SET exchange_code = %s,
                        issuer_name = %s,
                        valid_from = %s,
                        active = TRUE,
                        source_metadata = source_metadata || %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        entry["exchange_code"],
                        entry["issuer_name"],
                        entry["listing_date"],
                        metadata,
                        existing[0],
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO opendirector.market_securities (
                        exchange,
                        exchange_code,
                        issuer_name,
                        instrument_type,
                        currency,
                        provider,
                        provider_symbol,
                        valid_from,
                        source_metadata
                    )
                    VALUES (
                        'ASX',
                        %s,
                        %s,
                        'ordinary_share',
                        'AUD',
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        entry["exchange_code"],
                        entry["issuer_name"],
                        PROVIDER,
                        entry["provider_symbol"],
                        entry["listing_date"],
                        metadata,
                    ),
                )
            updated += 1
    conn.commit()
    return updated


def apply_seed(conn, entries: Sequence[dict[str, Any]], seed_filename: str) -> int:
    mappings = 0
    with conn.cursor() as cursor:
        for entry in entries:
            exchange_code = str(entry["exchange_code"]).upper()
            provider_symbol = str(entry["provider_symbol"]).upper()
            cursor.execute(
                """
                SELECT id
                FROM opendirector.market_securities
                WHERE provider = %s
                  AND provider_symbol = %s
                  AND valid_to IS NULL
                """,
                (PROVIDER, provider_symbol),
            )
            existing = cursor.fetchone()
            metadata = Json(
                {
                    "seed_file": Path(seed_filename).name,
                    "mapping_scope": "OpenDirector pilot",
                }
            )
            if existing:
                security_id = existing[0]
                cursor.execute(
                    """
                    UPDATE opendirector.market_securities
                    SET exchange_code = %s,
                        active = TRUE,
                        source_metadata = source_metadata || %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (exchange_code, metadata, security_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO opendirector.market_securities (
                        exchange,
                        exchange_code,
                        issuer_name,
                        instrument_type,
                        currency,
                        provider,
                        provider_symbol,
                        source_metadata
                    )
                    VALUES (
                        'ASX',
                        %s,
                        %s,
                        'ordinary_share',
                        'AUD',
                        %s,
                        %s,
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        exchange_code,
                        entry["issuer_name"],
                        PROVIDER,
                        provider_symbol,
                        metadata,
                    ),
                )
                security_id = cursor.fetchone()[0]
            for alias in entry["aliases"]:
                cursor.execute(
                    """
                    INSERT INTO opendirector.organization_security_matches (
                        organization_name,
                        security_id,
                        mapping_method,
                        mapping_confidence,
                        review_status,
                        review_notes
                    )
                    VALUES (%s, %s, 'curated_seed', 1.000, 'confirmed', %s)
                    ON CONFLICT (organization_name, security_id, valid_from)
                    DO UPDATE SET
                        is_primary = TRUE,
                        mapping_method = EXCLUDED.mapping_method,
                        mapping_confidence = EXCLUDED.mapping_confidence,
                        review_status = EXCLUDED.review_status,
                        review_notes = EXCLUDED.review_notes,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        alias,
                        security_id,
                        f"Curated ASX code mapping from {Path(seed_filename).name}",
                    ),
                )
                mappings += 1
    conn.commit()
    return mappings


def earliest_newsletter_date(conn) -> date:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT min(received_at)::date FROM opendirector.newsletters"
        )
        value = cursor.fetchone()[0]
    if value is None:
        raise RuntimeError("the OpenDirector newsletter archive is empty")
    return value


def select_securities(
    conn,
    requested_symbols: Sequence[str] | None = None,
    only_missing: bool = False,
    mapped_only: bool = False,
    stale_first: bool = False,
    limit: int | None = None,
) -> list[Security]:
    parameters: list[Any] = [PROVIDER]
    where = "WHERE provider = %s AND active"
    if requested_symbols:
        normalized = [symbol.upper() for symbol in requested_symbols]
        where += (
            " AND (upper(exchange_code) = ANY(%s)"
            " OR upper(provider_symbol) = ANY(%s))"
        )
        parameters.extend((normalized, normalized))
    if only_missing:
        where += (
            " AND NOT EXISTS ("
            "SELECT 1 FROM opendirector.daily_prices AS prices"
            " WHERE prices.security_id = market_securities.id"
            ")"
        )
    if mapped_only:
        where += (
            " AND EXISTS ("
            "SELECT 1"
            " FROM opendirector.organization_security_matches AS matches"
            " WHERE matches.security_id = market_securities.id"
            "   AND matches.review_status = 'confirmed'"
            "   AND matches.is_primary"
            ")"
        )
    order_sql = "ORDER BY exchange_code"
    if stale_first:
        order_sql = """
            ORDER BY (
                SELECT max(prices.price_date)
                FROM opendirector.daily_prices AS prices
                WHERE prices.security_id = market_securities.id
                  AND prices.source = %s
            ) NULLS FIRST,
            exchange_code
        """
        parameters.append(PRICE_SOURCE)
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT %s"
        parameters.append(limit)
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT id, exchange_code, issuer_name, provider_symbol, currency
            FROM opendirector.market_securities AS market_securities
            {where}
            {order_sql}
            {limit_sql}
            """,
            parameters,
        )
        rows = cursor.fetchall()
    return [Security(*row) for row in rows]


def incremental_start_date(
    conn,
    securities: Sequence[Security],
    archive_start: date,
    overlap_days: int,
) -> date:
    security_ids = [security.id for security in securities]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT security_id, max(price_date)
            FROM opendirector.daily_prices
            WHERE security_id = ANY(%s)
              AND source = %s
            GROUP BY security_id
            """,
            (security_ids, PRICE_SOURCE),
        )
        latest_by_security = dict(cursor.fetchall())
    if any(security.id not in latest_by_security for security in securities):
        return archive_start
    earliest_latest = min(latest_by_security.values())
    return max(archive_start, earliest_latest - timedelta(days=overlap_days))


def optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def history_rows(
    security: Security, history: pd.DataFrame
) -> list[tuple[Any, ...]]:
    if history.empty:
        return []
    if history.index.duplicated().any():
        raise ValueError(f"{security.provider_symbol} returned duplicate price dates")
    rows: list[tuple[Any, ...]] = []
    for timestamp, values in history.iterrows():
        close_price = optional_float(values.get("Close"))
        if close_price is None or close_price <= 0:
            continue
        high_price = optional_float(values.get("High"))
        low_price = optional_float(values.get("Low"))
        if (
            high_price is not None
            and low_price is not None
            and high_price < low_price
        ):
            raise ValueError(
                f"{security.provider_symbol} has high below low on "
                f"{timestamp.date()}"
            )
        volume_value = optional_float(values.get("Volume"))
        volume = int(volume_value) if volume_value is not None else None
        rows.append(
            (
                security.id,
                timestamp.date(),
                optional_float(values.get("Open")),
                high_price,
                low_price,
                close_price,
                optional_float(values.get("Adj Close")),
                volume,
                optional_float(values.get("Dividends")),
                optional_float(values.get("Stock Splits")),
                security.currency,
                PRICE_SOURCE,
                security.provider_symbol,
            )
        )
    return rows


def fetch_history(
    security: Security, start_date: date, end_date: date
) -> pd.DataFrame:
    exclusive_end = end_date + timedelta(days=1)
    ticker = yf.Ticker(security.provider_symbol)
    parameters = {
        "start": start_date.isoformat(),
        "end": exclusive_end.isoformat(),
        "interval": "1d",
        "auto_adjust": False,
        "actions": True,
        "keepna": False,
        "timeout": 30,
    }
    try:
        return ticker.history(repair=True, **parameters)
    except (IndexError, ValueError):
        # yfinance's optional repair pass fails on a small number of otherwise
        # valid ASX histories. Preserve coverage using the provider's unmodified
        # observations and retain the same explicit source label.
        return ticker.history(repair=False, **parameters)


def upsert_history(conn, rows: Sequence[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cursor:
        execute_values(
            cursor,
            """
            INSERT INTO opendirector.daily_prices (
                security_id,
                price_date,
                open_price,
                high_price,
                low_price,
                close_price,
                adjusted_close,
                volume,
                dividend,
                split_ratio,
                currency,
                source,
                source_symbol
            )
            VALUES %s
            ON CONFLICT (security_id, price_date, source)
            DO UPDATE SET
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                adjusted_close = EXCLUDED.adjusted_close,
                volume = EXCLUDED.volume,
                dividend = EXCLUDED.dividend,
                split_ratio = EXCLUDED.split_ratio,
                currency = EXCLUDED.currency,
                source_symbol = EXCLUDED.source_symbol,
                ingested_at = CURRENT_TIMESTAMP
            """,
            rows,
            page_size=1000,
        )
    conn.commit()
    return len(rows)


def start_run(
    conn, start_date: date, end_date: date, securities_requested: int
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO opendirector.price_ingestion_runs (
                provider,
                requested_start,
                requested_end,
                securities_requested,
                notes
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                PROVIDER,
                start_date,
                end_date,
                securities_requested,
                Json(
                    {
                        "price_source": PRICE_SOURCE,
                        "yfinance_version": yf.__version__,
                    }
                ),
            ),
        )
        run_id = cursor.fetchone()[0]
    conn.commit()
    return run_id


def record_failure(
    conn, run_id: int, security: Security, failure_message: str
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO opendirector.price_ingestion_failures (
                run_id,
                security_id,
                provider_symbol,
                failure_message
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (run_id, provider_symbol)
            DO UPDATE SET failure_message = EXCLUDED.failure_message
            """,
            (run_id, security.id, security.provider_symbol, failure_message[:2000]),
        )
    conn.commit()


def finish_run(
    conn,
    run_id: int,
    securities_loaded: int,
    rows_upserted: int,
    failures: int,
) -> str:
    status = (
        "completed"
        if failures == 0
        else "partial"
        if securities_loaded > 0
        else "failed"
    )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE opendirector.price_ingestion_runs
            SET completed_at = CURRENT_TIMESTAMP,
                status = %s,
                securities_loaded = %s,
                rows_upserted = %s,
                failures = %s
            WHERE id = %s
            """,
            (status, securities_loaded, rows_upserted, failures, run_id),
        )
    conn.commit()
    return status


def collect(
    conn,
    securities: Sequence[Security],
    start_date: date,
    end_date: date,
    dry_run: bool = False,
    delay_seconds: float = 0.0,
) -> dict[str, Any]:
    run_id = None if dry_run else start_run(
        conn, start_date, end_date, len(securities)
    )
    securities_loaded = 0
    rows_upserted = 0
    failures: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    for index, security in enumerate(securities):
        try:
            history = fetch_history(security, start_date, end_date)
            rows = history_rows(security, history)
            if not rows:
                raise RuntimeError("provider returned no usable daily observations")
            if not dry_run:
                upsert_history(conn, rows)
            securities_loaded += 1
            rows_upserted += len(rows)
            results.append(
                {
                    "exchange_code": security.exchange_code,
                    "provider_symbol": security.provider_symbol,
                    "observations": len(rows),
                    "first_date": str(rows[0][1]),
                    "last_date": str(rows[-1][1]),
                }
            )
        except Exception as error:
            conn.rollback()
            failure = {
                "provider_symbol": security.provider_symbol,
                "error": str(error),
            }
            failures.append(failure)
            if run_id is not None:
                record_failure(conn, run_id, security, str(error))
        finally:
            if delay_seconds and index < len(securities) - 1:
                time.sleep(delay_seconds)
    status = (
        "dry_run"
        if dry_run
        else finish_run(
            conn,
            run_id,
            securities_loaded,
            rows_upserted,
            len(failures),
        )
    )
    return {
        "run_id": run_id,
        "status": status,
        "requested_start": str(start_date),
        "requested_end": str(end_date),
        "securities_requested": len(securities),
        "securities_loaded": securities_loaded,
        "rows_upserted": rows_upserted,
        "delay_seconds": delay_seconds,
        "failures": failures,
        "results": results,
    }


def database_stats(conn) -> dict[str, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*)
                 FROM opendirector.market_securities
                 WHERE active) AS configured_securities,
                count(DISTINCT security_id),
                count(*),
                min(price_date),
                max(price_date),
                count(*) FILTER (WHERE adjusted_close IS NOT NULL),
                count(*) FILTER (WHERE volume IS NOT NULL)
            FROM opendirector.daily_prices
            """
        )
        prices = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                count(*),
                count(*) FILTER (WHERE review_status = 'confirmed')
            FROM opendirector.organization_security_matches
            """
        )
        mappings = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM opendirector.movement_security_links"
        )
        movement_links = cursor.fetchone()[0]
    return {
        "configured_securities": prices[0],
        "securities_with_prices": prices[1],
        "securities_without_prices": prices[0] - prices[1],
        "daily_observations": prices[2],
        "first_price_date": str(prices[3]) if prices[3] else None,
        "latest_price_date": str(prices[4]) if prices[4] else None,
        "observations_with_adjusted_close": prices[5],
        "observations_with_volume": prices[6],
        "organization_mappings": mappings[0],
        "confirmed_organization_mappings": mappings[1],
        "linked_movement_events": movement_links,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect ASX daily prices for OpenDirector companies"
    )
    parser.add_argument("--database-config", default="db.conf")
    parser.add_argument("--schema-file", default=DEFAULT_SCHEMA)
    parser.add_argument("--seed-file", default=DEFAULT_SEED)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--sync-asx-directory", action="store_true")
    parser.add_argument(
        "--directory-only",
        action="store_true",
        help="update security reference data without collecting prices",
    )
    parser.add_argument(
        "--start",
        type=parse_date,
        help="first price date; defaults to the first OpenDirector newsletter",
    )
    parser.add_argument(
        "--end",
        type=parse_date,
        default=date.today(),
        help="inclusive final price date",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="optional ASX codes or provider symbols to collect",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="select only securities with no stored daily prices",
    )
    parser.add_argument(
        "--mapped-only",
        action="store_true",
        help="select only securities confirmed against OpenDirector names",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="resume after the least-current selected security with overlap",
    )
    parser.add_argument(
        "--stale-first",
        action="store_true",
        help="select securities with no or the oldest stored prices first",
    )
    parser.add_argument("--incremental-overlap-days", type=int, default=7)
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="pause between provider requests",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    conn = connect(args.database_config)
    try:
        if args.apply_schema:
            if args.dry_run:
                raise ValueError("--apply-schema cannot be combined with --dry-run")
            apply_schema(conn, args.schema_file)
        seed_entries: Sequence[dict[str, Any]] = []
        mappings_seeded = 0
        if args.seed:
            if args.dry_run:
                seed_entries = load_seed(args.seed_file)
            else:
                seed_entries = load_seed(args.seed_file)
                mappings_seeded = apply_seed(conn, seed_entries, args.seed_file)
        directory_entries = 0
        if args.sync_asx_directory:
            entries = fetch_asx_directory()
            directory_entries = len(entries)
            if not args.dry_run:
                sync_asx_directory(conn, entries, datetime.now().astimezone())
        if args.directory_only:
            if not args.sync_asx_directory:
                raise ValueError("--directory-only requires --sync-asx-directory")
            result: dict[str, Any] = {
                "status": "completed" if not args.dry_run else "dry_run",
                "asx_directory_entries": directory_entries,
                "mappings_seeded": mappings_seeded,
            }
            if args.stats and not args.dry_run:
                result["database_stats"] = database_stats(conn)
            print(json.dumps(result, indent=2))
            return
        securities = select_securities(
            conn,
            args.symbols,
            only_missing=args.only_missing,
            mapped_only=args.mapped_only,
            stale_first=args.stale_first,
            limit=args.limit,
        )
        if not securities:
            if args.dry_run and seed_entries:
                raise RuntimeError(
                    "seed preview validated, but dry-run does not write securities"
                )
            raise RuntimeError("no matching active ASX securities are configured")
        archive_start = earliest_newsletter_date(conn)
        if args.start and args.incremental:
            raise ValueError("--start cannot be combined with --incremental")
        if args.incremental_overlap_days < 0:
            raise ValueError("--incremental-overlap-days cannot be negative")
        if args.delay_seconds < 0:
            raise ValueError("--delay-seconds cannot be negative")
        start_date = (
            incremental_start_date(
                conn,
                securities,
                archive_start,
                args.incremental_overlap_days,
            )
            if args.incremental
            else args.start or archive_start
        )
        if args.end < start_date:
            raise ValueError("--end must be on or after --start")
        result = collect(
            conn,
            securities,
            start_date=start_date,
            end_date=args.end,
            dry_run=args.dry_run,
            delay_seconds=args.delay_seconds,
        )
        result["mappings_seeded"] = mappings_seeded
        if args.stats and not args.dry_run:
            result["database_stats"] = database_stats(conn)
        print(json.dumps(result, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
