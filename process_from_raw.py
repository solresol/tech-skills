#!/usr/bin/env python3
"""
Process director extraction data from director_extraction_raw table
This script reads from director_extraction_raw and populates director_details
and director_committees tables, then marks URLs as processed in director_compensation.
"""

import argparse
import json
import logging
import pgconnect
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")
parser.add_argument("--stop-after", type=int,
                    help="Stop after processing N URLs")
args = parser.parse_args()

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

conn = pgconnect.connect(args.database_config)
cursor = conn.cursor()
lookup_cursor = conn.cursor()
update_cursor = conn.cursor()

# Find all URLs in director_compensation that are not processed but have data in director_extraction_raw
query = """
    SELECT der.cikcode, der.accessionnumber, der.response, f.document_storage_url
    FROM director_extraction_raw der
    JOIN filings f ON der.cikcode = f.cikcode AND der.accessionnumber = f.accessionnumber
    JOIN director_compensation dc ON f.document_storage_url = dc.url
    WHERE dc.processed = false
"""

if args.stop_after:
    query += f" LIMIT {args.stop_after}"

cursor.execute(query)

processed_count = 0
error_count = 0

for cikcode, accessionnumber, response_json, url in cursor:
    try:
        update_cursor.execute("BEGIN TRANSACTION")

        response = json.loads(response_json) if isinstance(response_json, str) else response_json

        # Get the directors array from the response
        directors = response.get('directors', [])

        if not directors:
            logging.warning(f"No directors found for {url}")
            # Still mark as processed since we have the data
            update_cursor.execute("""
                UPDATE director_compensation SET processed = TRUE
                WHERE url = %s
            """, [url])
            update_cursor.execute("COMMIT")
            processed_count += 1
            continue

        # Get filing date for this filing
        lookup_cursor.execute("SELECT filingDate FROM filings WHERE cikcode = %s AND accessionnumber = %s",
                             [cikcode, accessionnumber])
        filing_date = lookup_cursor.fetchone()[0]

        # Process each director
        for director in directors:
            # Skip malformed entries (strings instead of dicts)
            if not isinstance(director, dict):
                logging.warning(f"Skipping malformed director entry (type={type(director).__name__}) for {url}")
                continue

            # Check if this director already exists for this URL
            lookup_cursor.execute("""
                SELECT id FROM director_details
                WHERE url = %s AND name = %s
            """, [url, director.get('name')])

            existing = lookup_cursor.fetchone()
            if existing:
                director_id = existing[0]
            else:
                # Insert into director_details
                update_cursor.execute("""
                    INSERT INTO director_details
                    (url, name, age, role, gender, compensation, source_excerpt)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, [
                    url,
                    director.get('name'),
                    director.get('age'),
                    director.get('role'),
                    director.get('gender'),
                    director.get('total_compensation'),
                    director.get('source_excerpt')
                ])

                director_id = update_cursor.fetchone()[0]

            # Insert committees for this director
            committees = director.get('committees', [])
            if committees:
                for committee in committees:
                    if committee:  # Skip empty strings
                        update_cursor.execute("""
                            INSERT INTO director_committees (director_id, committee_name)
                            VALUES (%s, %s)
                            ON CONFLICT (director_id, committee_name) DO NOTHING
                        """, [director_id, committee])

        # Mark URL as processed
        update_cursor.execute("""
            UPDATE director_compensation SET processed = TRUE
            WHERE url = %s
        """, [url])

        update_cursor.execute("COMMIT")
        processed_count += 1

        if args.verbose and processed_count % 100 == 0:
            logging.info(f"Processed {processed_count} URLs")

    except Exception as e:
        logging.error(f"Error processing {url}: {str(e)}")
        update_cursor.execute("ROLLBACK")
        error_count += 1

conn.commit()

print(f"Processed {processed_count} URLs successfully")
if error_count > 0:
    print(f"Failed to process {error_count} URLs")

if processed_count > 0:
    logging.info("Refreshing materialized view director_mentions")
    cursor.execute("REFRESH MATERIALIZED VIEW director_mentions")
    conn.commit()
    logging.info("Done")
