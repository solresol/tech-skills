#!/usr/bin/env python3

import argparse
import json
import sys
import os
import openai
import pgconnect

parser = argparse.ArgumentParser(description="Diagnose batches with errors and provide detailed information")
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--openai-key-file",
                    default="~/.openai.key")
parser.add_argument("--show-batches", action="store_true",
                    help="Show all batches with unretrieved errors")
parser.add_argument("--batch-id", type=int,
                    help="Show detailed info for a specific local batch ID")
parser.add_argument("--error-json",
                    help="Parse an error JSON record and find its batch")
args = parser.parse_args()

# Connect to database
conn = pgconnect.connect(args.database_config)
cursor = conn.cursor()

# Set up OpenAI client if needed
client = None
if args.show_batches or args.batch_id:
    api_key = open(os.path.expanduser(args.openai_key_file)).read().strip()
    client = openai.OpenAI(api_key=api_key)

def parse_error_record(error_json_str):
    """Parse an error JSON record and extract key information"""
    try:
        record = json.loads(error_json_str)
        return {
            'batch_req_id': record.get('id'),
            'custom_id': record.get('custom_id'),
            'status_code': record.get('response', {}).get('status_code'),
            'error_message': record.get('response', {}).get('body', {}).get('error', {}).get('message'),
            'request_id': record.get('response', {}).get('request_id')
        }
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON - {e}")
        return None

def find_batch_for_url(url):
    """Find batch information for a given URL"""
    # Try director_extractions first (old table)
    cursor.execute("""
        SELECT de.batch_id, deb.openai_batch_id, deb.when_sent, deb.when_retrieved
        FROM director_extractions de
        JOIN director_extract_batches deb ON de.batch_id = deb.id
        WHERE de.url = %s
    """, [url])

    result = cursor.fetchone()
    if result:
        return {
            'batch_id': result[0],
            'openai_batch_id': result[1],
            'when_sent': result[2],
            'when_retrieved': result[3],
            'source_table': 'director_extractions'
        }

    # Try director_compensation (newer table)
    cursor.execute("""
        SELECT dc.batch_id, deb.openai_batch_id, deb.when_sent, deb.when_retrieved
        FROM director_compensation dc
        JOIN director_extract_batches deb ON dc.batch_id = deb.id
        WHERE dc.url = %s
    """, [url])

    result = cursor.fetchone()
    if result:
        return {
            'batch_id': result[0],
            'openai_batch_id': result[1],
            'when_sent': result[2],
            'when_retrieved': result[3],
            'source_table': 'director_compensation'
        }

    return None

def get_batch_details(local_batch_id):
    """Get detailed information about a batch"""
    cursor.execute("""
        SELECT id, openai_batch_id, when_created, when_sent, when_retrieved
        FROM director_extract_batches
        WHERE id = %s
    """, [local_batch_id])

    result = cursor.fetchone()
    if not result:
        return None

    batch_info = {
        'local_id': result[0],
        'openai_batch_id': result[1],
        'when_created': result[2],
        'when_sent': result[3],
        'when_retrieved': result[4]
    }

    # Get count of URLs in this batch from director_extractions
    cursor.execute("""
        SELECT COUNT(*) FROM director_extractions WHERE batch_id = %s
    """, [local_batch_id])
    batch_info['url_count_old'] = cursor.fetchone()[0]

    # Get count of URLs in this batch from director_compensation
    cursor.execute("""
        SELECT COUNT(*) FROM director_compensation WHERE batch_id = %s
    """, [local_batch_id])
    batch_info['url_count_new'] = cursor.fetchone()[0]

    return batch_info

def show_batch_error_details(local_batch_id, openai_batch_id):
    """Fetch and display error details from OpenAI for a batch"""
    openai_result = client.batches.retrieve(openai_batch_id)

    print(f"\nOpenAI Batch Status: {openai_result.status}")
    print(f"Request counts: {openai_result.request_counts}")

    if openai_result.error_file_id:
        print(f"\nError file ID: {openai_result.error_file_id}")
        error_file_response = client.files.content(openai_result.error_file_id)

        # Parse errors and categorize them
        errors_by_type = {}
        total_errors = 0

        for line in error_file_response.text.splitlines():
            total_errors += 1
            record = json.loads(line)
            error_msg = record.get('response', {}).get('body', {}).get('error', {}).get('message', 'Unknown')

            if error_msg not in errors_by_type:
                errors_by_type[error_msg] = []
            errors_by_type[error_msg].append(record.get('custom_id'))

        print(f"\nTotal errors: {total_errors}")
        print("\nError types:")
        for error_type, urls in errors_by_type.items():
            print(f"  {error_type}: {len(urls)} occurrences")
            if len(urls) <= 3:
                for url in urls:
                    print(f"    - {url}")
            else:
                print(f"    First 3 URLs:")
                for url in urls[:3]:
                    print(f"    - {url}")
    else:
        print("\nNo error file for this batch")

if args.error_json:
    # Parse error JSON and find batch
    if args.error_json == '-':
        error_json_str = sys.stdin.read().strip()
    else:
        error_json_str = args.error_json

    error_info = parse_error_record(error_json_str)
    if error_info:
        print(f"Error record information:")
        print(f"  Batch request ID: {error_info['batch_req_id']}")
        print(f"  URL (custom_id): {error_info['custom_id']}")
        print(f"  Status code: {error_info['status_code']}")
        print(f"  Error message: {error_info['error_message']}")
        print(f"  Request ID: {error_info['request_id']}")

        # Try to find the batch
        batch_info = find_batch_for_url(error_info['custom_id'])
        if batch_info:
            print(f"\nBatch information:")
            print(f"  Local batch ID: {batch_info['batch_id']}")
            print(f"  OpenAI batch ID: {batch_info['openai_batch_id']}")
            print(f"  When sent: {batch_info['when_sent']}")
            print(f"  When retrieved: {batch_info['when_retrieved']}")
            print(f"  Source table: {batch_info['source_table']}")
        else:
            print(f"\nNo batch found for URL: {error_info['custom_id']}")
            print("\nThis could mean:")
            print("  1. The URL was never added to director_extractions or director_compensation")
            print("  2. The batch was created but URLs weren't tracked properly")
            print("  3. The error occurred before the URL was recorded")

elif args.batch_id:
    # Show detailed info for a specific batch
    batch_info = get_batch_details(args.batch_id)
    if not batch_info:
        print(f"No batch found with ID {args.batch_id}")
        sys.exit(1)

    print(f"Batch {args.batch_id} details:")
    print(f"  OpenAI batch ID: {batch_info['openai_batch_id']}")
    print(f"  Created: {batch_info['when_created']}")
    print(f"  Sent: {batch_info['when_sent']}")
    print(f"  Retrieved: {batch_info['when_retrieved']}")
    print(f"  URLs in director_extractions: {batch_info['url_count_old']}")
    print(f"  URLs in director_compensation: {batch_info['url_count_new']}")

    if batch_info['openai_batch_id'] and client:
        show_batch_error_details(args.batch_id, batch_info['openai_batch_id'])

elif args.show_batches:
    # Show all batches with unretrieved errors
    cursor.execute("""
        SELECT id, openai_batch_id, when_created, when_sent, when_retrieved
        FROM director_extract_batches
        WHERE when_sent IS NOT NULL
        ORDER BY id DESC
        LIMIT 50
    """)

    print("Recent batches (last 50):")
    print(f"{'ID':<6} {'OpenAI Batch ID':<35} {'Sent':<20} {'Retrieved':<20}")
    print("-" * 90)

    batches_with_errors = []

    for row in cursor:
        local_id, openai_batch_id, when_created, when_sent, when_retrieved = row
        sent_str = str(when_sent) if when_sent else "Not sent"
        retrieved_str = str(when_retrieved) if when_retrieved else "Not retrieved"

        status = "✓" if when_retrieved else "⏳"
        print(f"{status} {local_id:<4} {openai_batch_id:<35} {sent_str:<20} {retrieved_str:<20}")

        # Check if batch has errors
        if openai_batch_id and when_sent and not when_retrieved:
            try:
                openai_result = client.batches.retrieve(openai_batch_id)
                if openai_result.error_file_id:
                    batches_with_errors.append((local_id, openai_batch_id))
            except Exception as e:
                print(f"  Error checking batch {local_id}: {e}")

    if batches_with_errors:
        print(f"\n\nBatches with errors (not retrieved): {len(batches_with_errors)}")
        for local_id, openai_batch_id in batches_with_errors:
            print(f"  Batch {local_id} ({openai_batch_id})")
            print(f"    Run: {sys.argv[0]} --batch-id {local_id} for details")

else:
    parser.print_help()
