#!/usr/bin/env python3

import argparse
import os
import sys
import openai
import sqlite3
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

update_cursor.execute("begin transaction")
work_to_be_done = False

for local_batch_id, openai_batch_id in cursor:
    openai_result = client.batches.retrieve(openai_batch_id)
    if openai_result.status != 'completed':
        continue
    if openai_result.error_file_id is not None:
        error_file_response = client.files.content(openai_result.error_file_id)
        sys.stderr.write(error_file_response.text)
    if openai_result.output_file_id is None:
        continue
    
    file_response = client.files.content(openai_result.output_file_id)
    iterator = file_response.text.splitlines()
    
    for row in iterator:
        record = json.loads(row)
        if record['response']['status_code'] != 200:
            continue
        
        # Extract the tool call arguments
        arguments = json.loads(record['response']['body']['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        
        # Get the filename (which was used as the custom_id)
        url = record['custom_id']

        lookup_cursor.execute("select cikcode, accessionNumber from filings where document_storage_url = %s", [url])
        cikcode, accession_number = lookup_cursor.fetchone()
        # Just assume it works. Unless OpenAI makes something up, we're just getting back something we gave it
        
        # Extract usage information
        usage = record['response']['body']['usage']
        model = record['response']['body']['model'] + " (batch)"

        # Update the files table with the analysis results
        update_cursor.execute("""
             INSERT INTO director_extraction_raw (cikcode, accessionNumber, response, prompt_tokens, completion_tokens)
                         VALUES (%s, %s, %s, %s, %s)
                  ON CONFLICT (cikcode, accessionNumber)
                 DO UPDATE SET
                       response = excluded.response,
                       prompt_tokens = excluded.prompt_tokens,
                       completion_tokens = excluded.completion_tokens
        """, [cikcode, accession_number, json.dumps(arguments), usage['prompt_tokens'], usage['completion_tokens']])
        
        total_prompt_tokens += usage['prompt_tokens']
        total_completion_tokens += usage['completion_tokens']
    
    # Mark the batch as retrieved
    update_cursor.execute("update director_extract_batches set when_retrieved = current_timestamp where id = %s", [local_batch_id])

conn.commit()

if args.show_costs:
    print(f"Prompt tokens:     {total_prompt_tokens}")
    print(f"Completion tokens: {total_completion_tokens}")
    prompt_pricing = 0.075 / 1000000  # Adjust pricing as needed
    completion_pricing = 0.3 / 1000000  # Adjust pricing as needed
    cost = prompt_pricing * total_prompt_tokens + completion_pricing * total_completion_tokens
    print(f"Cost (USD):        {cost:.2f}")

cursor.execute("refresh materialized view director_mentions")
