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

TERMINAL_BATCH_STATUSES = {"completed", "expired", "failed", "cancelled"}

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
total_failed_records = 0
total_released_for_retry = 0
retrieved_batch_count = 0
failure_examples = []

update_cursor.execute("begin transaction")
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
    update_cursor.execute(
        """
        delete from director_extractions queued
        where queued.batch_id = %s
          and queued.url = %s
          and not exists (
              select 1
              from filings
              join director_extraction_raw raw
                on raw.cikcode = filings.cikcode
               and raw.accessionnumber = filings.accessionnumber
              where filings.document_storage_url = queued.url
          )
        """,
        [local_batch_id, url],
    )
    released = update_cursor.rowcount
    update_cursor.execute(
        """
        delete from director_compensation queued
        where queued.batch_id = %s
          and queued.url = %s
          and queued.processed is not true
          and not exists (
              select 1 from director_details
              where director_details.url = queued.url
          )
        """,
        [local_batch_id, url],
    )
    released += update_cursor.rowcount
    return released


def release_batch_for_retry(local_batch_id):
    update_cursor.execute(
        """
        delete from director_extractions queued
        where queued.batch_id = %s
          and not exists (
              select 1
              from filings
              join director_extraction_raw raw
                on raw.cikcode = filings.cikcode
               and raw.accessionnumber = filings.accessionnumber
              where filings.document_storage_url = queued.url
          )
        """,
        [local_batch_id],
    )
    released = update_cursor.rowcount
    update_cursor.execute(
        """
        delete from director_compensation queued
        where queued.batch_id = %s
          and queued.processed is not true
          and not exists (
              select 1 from director_details
              where director_details.url = queued.url
          )
        """,
        [local_batch_id],
    )
    released += update_cursor.rowcount
    return released


def handle_failed_record(local_batch_id, openai_batch_id, record):
    url = record.get("custom_id")
    response = record.get("response") or {}
    body = response.get("body")
    if not isinstance(body, dict):
        body = {}
    error = body.get("error")
    error_message = error.get("message") if isinstance(error, dict) else None
    request_id = response.get("request_id")

    if url is None:
        logging.error(
            "Batch %s (local_id=%s) returned a failed record without custom_id",
            openai_batch_id,
            local_batch_id,
        )
        return 0

    released = release_url_for_retry(local_batch_id, url)
    if len(failure_examples) < 10:
        context = [f"url={url}"]
        if request_id:
            context.append(f"request_id={request_id}")
        if error_message:
            context.append(f"error={error_message}")
        failure_examples.append(", ".join(context))
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
    if openai_result.status not in TERMINAL_BATCH_STATUSES:
        continue
    batch_failed_records = 0
    batch_released_for_retry = 0
    request_counts = getattr(openai_result, "request_counts", None)
    reported_failed_records = getattr(
        request_counts,
        "failed",
        0,
    ) or 0
    if openai_result.error_file_id is not None:
        try:
            error_file_response = client.files.content(openai_result.error_file_id)
        except openai.NotFoundError:
            logging.warning(
                "OpenAI returned error_file_id %s but the file was unavailable (likely expired)",
                openai_result.error_file_id,
            )
        else:
            for row in error_file_response.text.splitlines():
                if not row.strip():
                    continue
                record = json.loads(row)
                batch_failed_records += 1
                batch_released_for_retry += handle_failed_record(
                    local_batch_id,
                    openai_batch_id,
                    record,
                )
    if openai_result.output_file_id is None:
        batch_released_for_retry += release_batch_for_retry(local_batch_id)
        batch_failed_records = max(
            batch_failed_records,
            reported_failed_records,
            1,
        )
        logging.warning(
            "Batch %s (local_id=%s) has status=%s and no output_file_id; "
            "released %s queued row(s) for retry and marked it retrieved",
            openai_batch_id,
            local_batch_id,
            openai_result.status,
            batch_released_for_retry,
        )
        update_cursor.execute(
            "update director_extract_batches set when_retrieved = current_timestamp where id = %s",
            [local_batch_id],
        )
        total_failed_records += batch_failed_records
        total_released_for_retry += batch_released_for_retry
        retrieved_batch_count += 1
        continue

    try:
        file_response = client.files.content(openai_result.output_file_id)
    except openai.NotFoundError:
        batch_released_for_retry += release_batch_for_retry(local_batch_id)
        reported_total_records = getattr(
            request_counts,
            "total",
            0,
        ) or 0
        batch_failed_records = max(
            batch_failed_records,
            reported_failed_records,
            reported_total_records,
            1,
        )
        logging.error(
            "Batch %s (local_id=%s) output file %s not found (likely expired). "
            "Released %s queued row(s) for retry and marked it retrieved.",
            openai_batch_id,
            local_batch_id,
            openai_result.output_file_id,
            batch_released_for_retry,
        )
        update_cursor.execute(
            "update director_extract_batches set when_retrieved = current_timestamp where id = %s",
            [local_batch_id],
        )
        print(
            f"ERROR: Batch {local_batch_id} (openai_id={openai_batch_id}) output file expired. "
            f"File {openai_result.output_file_id} no longer available.",
            file=sys.stderr,
        )
        total_failed_records += batch_failed_records
        total_released_for_retry += batch_released_for_retry
        retrieved_batch_count += 1
        continue
    iterator = file_response.text.splitlines()
    
    for row in iterator:
        record = json.loads(row)
        url = record.get('custom_id')
        if url is None:
            batch_failed_records += 1
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
            batch_failed_records += 1
            batch_released_for_retry += handle_failed_record(
                local_batch_id,
                openai_batch_id,
                record,
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
            batch_failed_records += 1
            batch_released_for_retry += released
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
            batch_failed_records += 1
            batch_released_for_retry += released
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
    batch_failed_records = max(batch_failed_records, reported_failed_records)
    total_failed_records += batch_failed_records
    total_released_for_retry += batch_released_for_retry
    retrieved_batch_count += 1
    if batch_failed_records:
        logging.warning(
            "Batch %s (local_id=%s) had %s failed request(s) and released %s queued row(s) for retry",
            openai_batch_id,
            local_batch_id,
            batch_failed_records,
            batch_released_for_retry,
        )

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

if total_failed_records:
    print(
        f"ERROR: Retrieved {retrieved_batch_count} batch(es) with "
        f"{total_failed_records} failed request(s); released "
        f"{total_released_for_retry} queued row(s) for retry.",
        file=sys.stderr,
    )
    for example in failure_examples:
        print(f"ERROR EXAMPLE: {example}", file=sys.stderr)
    sys.exit(1)
