#!/usr/bin/env python3

import argparse
import psycopg2
import psycopg2.extras
import zipfile
import pgconnect
import logging
import json
import os

parser = argparse.ArgumentParser(description="Extract ticker information from SEC submissions.zip file")
parser.add_argument("--submissions-zip",
                    help="Path to the SEC submissions.zip file",
                    default="data/usa/submissions.zip")
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--schema-file",
                    default="ticker_schema.sql",
                    help="SQL file containing the schema for the ticker table")
parser.add_argument("--progress",
                    action="store_true",
                    help="Show a progress bar")
parser.add_argument("--only-cikcode",
                    type=int,
                    help="Only process one cikcode (for debugging)")
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")

args = parser.parse_args()

# Set up logging
if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting ticker extraction")
else:
    logging.basicConfig(level=logging.WARNING)

# Verify the submissions.zip file exists
if not os.path.exists(args.submissions_zip):
    logging.error(f"Submissions ZIP file not found at {args.submissions_zip}")
    exit(1)

# Open the submissions.zip file
submissions = zipfile.ZipFile(args.submissions_zip)

# Connect to the database
conn = pgconnect.connect(args.database_config)
cursor = conn.cursor()

# Create the schema if it doesn't exist
with open(args.schema_file, 'r') as schema_file:
    schema_sql = schema_file.read()
    cursor.execute(schema_sql)
    conn.commit()
    logging.info("Schema created or verified")

# Prepare the ticker insertion query
ticker_insert_query = """
INSERT INTO cik_to_ticker (cikcode, ticker)
VALUES (%s, %s)
ON CONFLICT ON CONSTRAINT cik_to_ticker_pkey DO NOTHING
"""

# Get the ZIP entries
zip_entries = [entry for entry in submissions.namelist() if entry.startswith("CIK") and entry.endswith(".json")]

if args.only_cikcode:
    zip_entries = [f"CIK{args.only_cikcode:010d}.json"]

# Set up progress bar if requested
if args.progress:
    import tqdm
    iterator = tqdm.tqdm(zip_entries)
else:
    iterator = zip_entries

# Process each entry
ticker_count = 0
cik_count = 0

for entry in iterator:
    # Check if filename is of the right format (CIK followed by numbers and .json)
    if not (entry.startswith("CIK") and entry[3:-5].isdigit() and entry.endswith(".json")):
        continue
        
    cikcode = int(entry[3:-5])
    
    try:
        source_data = submissions.read(entry)
        json_data = json.loads(source_data)
        
        # Skip entries without "tickers" key or with empty tickers
        if "tickers" not in json_data or not json_data["tickers"]:
            logging.info(f"Skipping {entry}: No tickers found")
            continue
        
        # Add all tickers for this CIK
        cik_count += 1
        for ticker in json_data["tickers"]:
            if ticker:  # Only process non-empty tickers
                cursor.execute(ticker_insert_query, [cikcode, ticker])
                ticker_count += 1
        
        # Commit each CIK to avoid large transactions
        conn.commit()
            
    except Exception as e:
        logging.error(f"Error processing {entry}: {str(e)}")
        continue

# Final commit
conn.commit()

logging.info(f"Extraction complete. Added {ticker_count} tickers for {cik_count} companies.")
print(f"Extraction complete. Added {ticker_count} tickers for {cik_count} companies.")

# Close connections
cursor.close()
conn.close()