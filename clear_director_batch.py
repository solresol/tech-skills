#!/usr/bin/env python3

import argparse

import pgconnect


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear a director extraction batch so it can be re-run.")
    parser.add_argument("batch_id", type=int, help="The ID of the batch to clear")
    parser.add_argument(
        "--database-config",
        default="db.conf",
        help="Path to the database configuration file (default: db.conf)",
    )
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "select id, openai_batch_id, when_sent, when_retrieved from director_extract_batches where id = %s",
                [args.batch_id],
            )
            batch_row = cursor.fetchone()
            if batch_row is None:
                raise SystemExit(f"Batch {args.batch_id} does not exist")

        with conn.cursor() as cursor:
            cursor.execute(
                "select count(*) from director_extractions where batch_id = %s",
                [args.batch_id],
            )
            (url_count,) = cursor.fetchone()

        with conn.cursor() as cursor:
            cursor.execute(
                "delete from batchprogress where batch_id = %s",
                [args.batch_id],
            )

        with conn.cursor() as cursor:
            cursor.execute(
                "delete from director_extractions where batch_id = %s",
                [args.batch_id],
            )

        with conn.cursor() as cursor:
            cursor.execute(
                """
                update director_extract_batches
                   set openai_batch_id = null,
                       when_sent = null,
                       when_retrieved = null
                 where id = %s
                """,
                [args.batch_id],
            )

    print(
        "Cleared batch {batch_id}. Removed {url_count} queued URLs and reset batch metadata.".format(
            batch_id=args.batch_id,
            url_count=url_count,
        )
    )


if __name__ == "__main__":
    main()
