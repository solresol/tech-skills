#!/usr/bin/env python3

import argparse
import os
import sys
import openai
import time
import json
import pgconnect
import logging

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--openai-key-file",
                    default="~/.openai.key")
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")
parser.add_argument("--show-costs", action="store_true")
parser.add_argument("--mark-batch-complete", type=int, help="Manually mark a batch as completed without processing it")
args = parser.parse_args()

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

api_key = open(os.path.expanduser(args.openai_key_file)).read().strip()
client = openai.OpenAI(api_key=api_key)

conn = pgconnect.connect(args.database_config)
cursor = conn.cursor()
lookup_cursor = conn.cursor()
update_cursor = conn.cursor()

cursor.execute("select id, openai_batch_id from director_extract_batches where when_sent is not null and when_retrieved is null")

total_prompt_tokens = 0
total_completion_tokens = 0

# If we're just marking a batch as complete, do that and exit
if args.mark_batch_complete:
    update_cursor.execute("UPDATE director_extract_batches SET when_retrieved = current_timestamp WHERE id = %s", [args.mark_batch_complete])
    rows_updated = update_cursor.rowcount
    conn.commit()
    if rows_updated > 0:
        print(f"Successfully marked batch {args.mark_batch_complete} as completed")
        sys.exit(0)
    else:
        print(f"No batch with ID {args.mark_batch_complete} found or it was already completed")
        sys.exit(1)

# Function to clean null characters and other problematic Unicode
def clean_json_for_postgres(json_obj):
    if isinstance(json_obj, str):
        # Replace null bytes and other potentially problematic characters
        return json_obj.replace('\u0000', '')
    elif isinstance(json_obj, dict):
        return {k: clean_json_for_postgres(v) for k, v in json_obj.items()}
    elif isinstance(json_obj, list):
        return [clean_json_for_postgres(item) for item in json_obj]
    else:
        return json_obj

work_to_be_done = False

for local_batch_id, openai_batch_id in cursor:
    try:
        update_cursor.execute("BEGIN TRANSACTION")
        
        openai_result = client.batches.retrieve(openai_batch_id)
        if openai_result.status != 'completed' and openai_result.status != 'expired':
            conn.commit()  # Commit the empty transaction
            continue
        
        if openai_result.error_file_id is not None:
            try:
                error_file_response = client.files.content(openai_result.error_file_id)
                sys.stderr.write(error_file_response.text)
            except openai.NotFoundError:
                logging.warning(
                    "OpenAI returned error_file_id %s but the file was unavailable (likely expired)",
                    openai_result.error_file_id,
                )
        
        if openai_result.output_file_id is None:
            conn.commit()  # Commit the empty transaction
            continue
        
        file_response = client.files.content(openai_result.output_file_id)
        iterator = file_response.text.splitlines()
        
        # Print number of responses in the batch
        responses = list(file_response.text.splitlines())
        logging.info(f"Processing batch {local_batch_id} with {len(responses)} responses")
        
        for row in iterator:
            try:
                record = json.loads(row)
                if record['response']['status_code'] != 200:
                    continue
                
                # Get the URL (which was used as the custom_id)
                url = record['custom_id']

                # First, check if the URL exists in director_compensation
                lookup_cursor.execute("SELECT 1 FROM director_compensation WHERE url = %s", [url])
                url_exists = lookup_cursor.fetchone() is not None
                
                if not url_exists:
                    logging.warning(f"URL {url} not found in director_compensation table, skipping")
                    
                    # For debugging, let's check what URLs are actually in the table
                    if local_batch_id is not None:
                        lookup_cursor.execute("SELECT url FROM director_compensation WHERE batch_id = %s", [local_batch_id])
                        batch_urls = [row[0] for row in lookup_cursor.fetchall()]
                        logging.info(f"URLs in director_compensation for batch {local_batch_id}: {batch_urls}")
                    
                    continue

                # Get cikcode and accession number
                lookup_cursor.execute("SELECT cikcode, accessionNumber FROM filings WHERE document_storage_url = %s", [url])
                result = lookup_cursor.fetchone()
                if result is None:
                    logging.warning(f"URL {url} not found in filings table, skipping")
                    continue
                    
                cikcode, accession_number = result

                # Extract usage information
                usage = record['response']['body']['usage']
                model = record['response']['body']['model'] + " (batch)"

                # Extract the tool call arguments
                arguments = json.loads(record['response']['body']['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
                # Clean the arguments before storing
                arguments = clean_json_for_postgres(arguments)
                
                # Process directors
                if 'directors' in arguments:
                    for director in arguments['directors']:
                        # Insert director details
                        update_cursor.execute("""
                            INSERT INTO director_details (url, name, age, role, gender, compensation, source_excerpt)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, [
                            url, 
                            director.get('name', ''), 
                            director.get('age', 0),
                            director.get('role', ''),
                            director.get('gender', 'unknown'),
                            director.get('compensation', 0),
                            director.get('source_excerpt', '')
                        ])
                        
                        director_id = update_cursor.fetchone()[0]
                        
                        # Insert committee memberships
                        if 'committees' in director and director['committees']:
                            for committee in director['committees']:
                                if committee:  # Skip empty committee names
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
                
                total_prompt_tokens += usage['prompt_tokens']
                total_completion_tokens += usage['completion_tokens']
                
            except json.decoder.JSONDecodeError:
                logging.error(f"JSONDecodeError for {url}: {record['response']['body']['choices'][0]['message']['tool_calls'][0]['function']['arguments']}")
            except Exception as e:
                logging.error(f"Error processing response: {str(e)}")
                conn.rollback()
                update_cursor.execute("BEGIN TRANSACTION")  # Start a new transaction
        
        # Mark the batch as completed
        update_cursor.execute("UPDATE director_extract_batches SET when_retrieved = current_timestamp WHERE id = %s", [local_batch_id])
        rows_updated = update_cursor.rowcount
        conn.commit()
        logging.info(f"Marked batch {local_batch_id} as completed, updated {rows_updated} rows")
        
    except Exception as e:
        logging.error(f"Error processing batch {local_batch_id}: {str(e)}")
        conn.rollback()
        
# Final commit to be safe
try:
    conn.commit()
except Exception as e:
    logging.error(f"Error in final commit: {str(e)}")
    conn.rollback()

if args.show_costs:
    print(f"Prompt tokens:     {total_prompt_tokens}")
    print(f"Completion tokens: {total_completion_tokens}")
    prompt_pricing = 0.075 / 1000000  # Adjust pricing as needed for the model used
    completion_pricing = 0.3 / 1000000  # Adjust pricing as needed for the model used
    cost = prompt_pricing * total_prompt_tokens + completion_pricing * total_completion_tokens
    print(f"Cost (USD):        {cost:.2f}")

# No need to create or replace views in this script - that should be done in schema management scripts
conn.commit()
