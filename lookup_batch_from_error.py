#!/usr/bin/env python3

import argparse
import json
import pgconnect

parser = argparse.ArgumentParser(description="Look up batch ID from OpenAI error record")
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("error_json",
                    nargs='?',
                    help="JSON error record (if not provided, reads from stdin)")
args = parser.parse_args()

# Read the error JSON
if args.error_json:
    error_json = args.error_json
else:
    import sys
    error_json = sys.stdin.read().strip()

# Parse the JSON
try:
    record = json.loads(error_json)
except json.JSONDecodeError as e:
    print(f"Error: Invalid JSON - {e}")
    exit(1)

# Extract the batch request ID
batch_req_id = record.get('id')
if not batch_req_id:
    print("Error: No 'id' field found in JSON")
    exit(1)

# Extract the custom_id (URL)
url = record.get('custom_id')
if not url:
    print("Error: No 'custom_id' field found in JSON")
    exit(1)

# Connect to database
conn = pgconnect.connect(args.database_config)
cursor = conn.cursor()

# Look up the batch ID from the URL
cursor.execute("""
    SELECT de.batch_id, deb.openai_batch_id, deb.when_sent, deb.when_retrieved
    FROM director_extractions de
    JOIN director_extract_batches deb ON de.batch_id = deb.id
    WHERE de.url = %s
""", [url])

result = cursor.fetchone()

if result:
    batch_id, openai_batch_id, when_sent, when_retrieved = result
    print(f"Batch ID: {batch_id}")
    print(f"OpenAI Batch ID: {openai_batch_id}")
    print(f"When sent: {when_sent}")
    print(f"When retrieved: {when_retrieved}")
    print(f"URL: {url}")

    # Show error details
    error_info = record.get('response', {})
    status_code = error_info.get('status_code')
    error_body = error_info.get('body', {})
    error_message = error_body.get('error', {}).get('message')

    if status_code:
        print(f"Status code: {status_code}")
    if error_message:
        print(f"Error message: {error_message}")
else:
    print(f"No batch found for URL: {url}")
    exit(1)
