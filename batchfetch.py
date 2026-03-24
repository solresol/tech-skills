#!/usr/bin/env python3

import argparse
import json
import logging
import openai
import openai_key
import pgconnect
import sqlite3
import sys
import time

from batch_response_parser import RetryableBatchRecordError, extract_tool_arguments

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--openai-key-file",
                    default=openai_key.DEFAULT_OPENAI_KEY_FILE)
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
else:
    # Enable logging at WARNING level by default so errors are visible
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.WARNING,
        datefmt='%Y-%m-%d %H:%M:%S')


api_key = openai_key.load_openai_api_key(args.openai_key_file)
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


def release_url_for_retry(local_batch_id, url):
    released = 0
    for table_name in ("director_extractions", "director_compensation"):
        update_cursor.execute(
            f"delete from {table_name} where batch_id = %s and url = %s",
            [local_batch_id, url],
        )
        released += update_cursor.rowcount
    return released


def format_record_context(error):
    context = []
    if getattr(error, "request_id", None):
        context.append(f"request_id={error.request_id}")
    if getattr(error, "finish_reason", None):
        context.append(f"finish_reason={error.finish_reason}")
    if context:
        return " (" + ", ".join(context) + ")"
    return ""

for local_batch_id, openai_batch_id in cursor:
    openai_result = client.batches.retrieve(openai_batch_id)
    if openai_result.status != 'completed' and openai_result.status != 'expired':
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
        logging.warning(
            "Batch %s (local_id=%s) has status=%s but no output_file_id; skipping",
            openai_batch_id,
            local_batch_id,
            openai_result.status,
        )
        continue

    try:
        file_response = client.files.content(openai_result.output_file_id)
    except openai.NotFoundError:
        logging.error(
            "Batch %s (local_id=%s) output file %s not found (likely expired). "
            "Marking batch as retrieved with no results.",
            openai_batch_id,
            local_batch_id,
            openai_result.output_file_id,
        )
        # Mark the batch as retrieved so we don't keep retrying a lost file
        update_cursor.execute(
            "update director_extract_batches set when_retrieved = current_timestamp where id = %s",
            [local_batch_id],
        )
        print(
            f"ERROR: Batch {local_batch_id} (openai_id={openai_batch_id}) output file expired. "
            f"File {openai_result.output_file_id} no longer available.",
            file=sys.stderr,
        )
        continue
    iterator = file_response.text.splitlines()
    
    for row in iterator:
        record = json.loads(row)
        url = record.get('custom_id')
        if url is None:
            logging.error(
                "Batch %s (local_id=%s) returned a record without custom_id; skipping unrecoverable row",
                openai_batch_id,
                local_batch_id,
            )
            continue

        response = record.get('response') or {}
        body = response.get('body')
        if not isinstance(body, dict):
            body = {}

        if response.get('status_code') != 200:
            lookup_cursor.execute(
                "select cikcode, accessionNumber, filingDate from filings where document_storage_url = %s",
                [url],
            )
            filing_info = lookup_cursor.fetchone()

            request_id = response.get('request_id')
            error_message = None
            if isinstance(body, dict):
                error = body.get('error')
                if isinstance(error, dict):
                    error_message = error.get('message')

            if filing_info:
                cikcode, accession_number, filing_date = filing_info
                sys.stderr.write(
                    f"Failed to download {url} (CIK {cikcode}, accession {accession_number}, filed {filing_date})"
                )
            else:
                sys.stderr.write(f"Failed to download {url}")

            if request_id:
                sys.stderr.write(f" request_id={request_id}")
            if error_message:
                sys.stderr.write(f": {error_message}")
            sys.stderr.write("\n")
            released = release_url_for_retry(local_batch_id, url)
            logging.warning(
                "Batch %s (local_id=%s) returned status_code=%s for %s and released %s queued row(s) for retry",
                openai_batch_id,
                local_batch_id,
                response.get('status_code'),
                url,
                released,
            )
            continue

        # Get the filename (which was used as the custom_id)
        lookup_cursor.execute(
            "select cikcode, accessionNumber from filings where document_storage_url = %s",
            [url],
        )
        filing = lookup_cursor.fetchone()
        if filing is None:
            released = release_url_for_retry(local_batch_id, url)
            logging.error(
                "Batch %s (local_id=%s) returned URL %s but no matching filing was found. Released %s queued row(s) for retry.",
                openai_batch_id,
                local_batch_id,
                url,
                released,
            )
            continue
        cikcode, accession_number = filing

        # Extract usage information
        usage = body.get('usage') or {}
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)

        # Extract the tool call arguments
        try:
            arguments = extract_tool_arguments(record)
            # Clean the arguments before storing
            arguments = clean_json_for_postgres(arguments)
        except RetryableBatchRecordError as exc:
            released = release_url_for_retry(local_batch_id, url)
            logging.warning(
                "Batch %s (local_id=%s) returned unusable structured output for %s: %s%s. Released %s queued row(s) for retry.",
                openai_batch_id,
                local_batch_id,
                url,
                exc.reason,
                format_record_context(exc),
                released,
            )
            print(
                f"WARNING: Batch {local_batch_id} (openai_id={openai_batch_id}) returned unusable structured output for {url}: {exc.reason}{format_record_context(exc)}",
                file=sys.stderr,
            )
            continue
            
        # Update the files table with the analysis results
        update_cursor.execute("""
             INSERT INTO director_extraction_raw (cikcode, accessionNumber, response, prompt_tokens, completion_tokens)
                         VALUES (%s, %s, %s, %s, %s)
                  ON CONFLICT (cikcode, accessionNumber)
                 DO UPDATE SET
                       response = excluded.response,
                       prompt_tokens = excluded.prompt_tokens,
                       completion_tokens = excluded.completion_tokens
        """, [cikcode, accession_number, json.dumps(arguments), prompt_tokens, completion_tokens])
        
        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
    
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
conn.commit()
